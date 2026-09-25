"""Portable firewall policy for the optional Spotify LAN listener."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence


class FirewallClassification(str, Enum):
    """Stable compatibility states exposed to later integration layers."""

    NO_FIREWALL = "no_firewall"
    UFW_INACTIVE = "ufw_inactive"
    UFW_ACTIVE = "ufw_active"
    UNSUPPORTED_FIREWALL = "unsupported_firewall"
    UNKNOWN = "unknown"


class SpotifyFirewallCompatibilityError(RuntimeError):
    """The current firewall cannot be managed safely for Spotify."""


@dataclass(frozen=True)
class _Lease:
    interface: str
    source_cidr: str
    destination_ipv4: str
    port: int

    def payload(self) -> dict:
        return {
            "interface": self.interface,
            "source_cidr": self.source_cidr,
            "destination_ipv4": self.destination_ipv4,
            "port": self.port,
        }


_INTERFACE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,14}\Z")
_ENABLED_RE = re.compile(
    r"^\s*ENABLED\s*=\s*(yes|no)\s*(?:#.*)?$", re.IGNORECASE
)
_ENABLED_ASSIGNMENT_RE = re.compile(r"^\s*ENABLED\s*=", re.IGNORECASE)


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


class SpotifyFirewallManager:
    """Manage at most one temporary, helper-owned Spotify firewall lease."""

    def __init__(
        self,
        *,
        ufw_config_path: str = "/etc/ufw/ufw.conf",
        ufw_binary_paths: Sequence[str] = ("/usr/sbin/ufw", "/sbin/ufw"),
        firewalld_binary_paths: Sequence[str] = (
            "/usr/bin/firewall-cmd",
            "/bin/firewall-cmd",
        ),
        helper_path: str = "/usr/lib/srova/srova-spotify-firewall-helper",
        sudo_path: str = "/usr/bin/sudo",
        path_exists: Callable[[str], bool] = os.path.exists,
        read_text: Callable[[str], str] = _read_text,
        command_runner: Callable = subprocess.run,
        command_timeout: float = 10.0,
    ) -> None:
        self._ufw_config_path = str(ufw_config_path)
        self._ufw_binary_paths = tuple(str(path) for path in ufw_binary_paths)
        self._firewalld_binary_paths = tuple(
            str(path) for path in firewalld_binary_paths
        )
        self._helper_path = str(helper_path)
        self._sudo_path = str(sudo_path)
        self._path_exists = path_exists
        self._read_text = read_text
        self._run = command_runner
        self._timeout = float(command_timeout)
        self._lease: Optional[_Lease] = None
        self._lock = threading.RLock()

    def inspect(self) -> FirewallClassification:
        """Classify the current firewall without making a mutation."""
        with self._lock:
            firewalld = self._probe_firewalld()
            if firewalld is True:
                return FirewallClassification.UNSUPPORTED_FIREWALL
            if firewalld is None:
                return FirewallClassification.UNKNOWN

            ufw_binary = self._first_existing(self._ufw_binary_paths)
            config_exists = self._path_exists(self._ufw_config_path)
            if ufw_binary is None and not config_exists:
                return FirewallClassification.NO_FIREWALL
            if ufw_binary is None or not config_exists:
                return FirewallClassification.UNKNOWN

            enabled = self._read_ufw_enabled()
            if enabled is None:
                return FirewallClassification.UNKNOWN
            if enabled is False:
                return FirewallClassification.UFW_INACTIVE

            response = self._invoke_helper("status", {})
            available = response.get("available")
            active = response.get("active")
            if type(available) is not bool or type(active) is not bool:
                raise SpotifyFirewallCompatibilityError(
                    "Spotify firewall status response is invalid"
                )
            if not available:
                raise SpotifyFirewallCompatibilityError(
                    "Enabled UFW cannot be managed by the Spotify firewall helper"
                )
            if active:
                return FirewallClassification.UFW_ACTIVE
            return FirewallClassification.UFW_INACTIVE

    classify = inspect

    def prepare(
        self,
        *,
        interface: str,
        source_cidr: str,
        destination_ipv4: str,
        port: int,
    ) -> bool:
        """Open the exact lease when active UFW requires it.

        Returns True only when a helper mutation was requested.
        """
        requested = self._validated_lease(
            interface, source_cidr, destination_ipv4, port
        )
        with self._lock:
            classification = self.inspect()
            if classification in (
                FirewallClassification.NO_FIREWALL,
                FirewallClassification.UFW_INACTIVE,
            ):
                return False
            if classification is FirewallClassification.UNSUPPORTED_FIREWALL:
                raise SpotifyFirewallCompatibilityError(
                    "The active firewall is not supported for Spotify access"
                )
            if classification is FirewallClassification.UNKNOWN:
                raise SpotifyFirewallCompatibilityError(
                    "The firewall state is unknown; Spotify access was not changed"
                )

            if self._lease == requested:
                return False
            if self._lease is not None:
                previous = self._lease
                self._invoke_helper("close", previous.payload())
                self._lease = None

            self._invoke_helper("open", requested.payload())
            self._lease = requested
            return True

    prepare_access = prepare

    def release(self) -> bool:
        """Close the currently managed lease; absence is idempotent."""
        with self._lock:
            if self._lease is None:
                return False
            lease = self._lease
            self._invoke_helper("close", lease.payload())
            self._lease = None
            return True

    close = release

    def cleanup(self) -> bool:
        """Remove stale owned rules only when UFW is confirmed active."""
        with self._lock:
            classification = self.inspect()
            if classification in (
                FirewallClassification.NO_FIREWALL,
                FirewallClassification.UFW_INACTIVE,
            ):
                return False
            if classification is not FirewallClassification.UFW_ACTIVE:
                raise SpotifyFirewallCompatibilityError(
                    "The firewall state does not permit safe Spotify cleanup"
                )
            self._invoke_helper("cleanup", {})
            self._lease = None
            return True

    cleanup_stale = cleanup

    def status_snapshot(self) -> dict:
        """Return a bounded snapshot containing no command output or lease data."""
        with self._lock:
            try:
                classification = self.inspect()
                error = False
            except SpotifyFirewallCompatibilityError:
                classification = FirewallClassification.UNKNOWN
                error = True
            return {
                "classification": classification.value,
                "compatible": classification in (
                    FirewallClassification.NO_FIREWALL,
                    FirewallClassification.UFW_INACTIVE,
                    FirewallClassification.UFW_ACTIVE,
                ),
                "helper_required": (
                    classification is FirewallClassification.UFW_ACTIVE
                ),
                "lease_active": self._lease is not None,
                "error": error,
            }

    def _probe_firewalld(self) -> Optional[bool]:
        binary = self._first_existing(self._firewalld_binary_paths)
        if binary is None:
            return False
        try:
            completed = self._run(
                [binary, "--state"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=self._timeout,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        output = completed.stdout.strip().lower()
        if completed.returncode == 0 and output == "running":
            return True
        if output in ("not running", "") and completed.returncode != 0:
            return False
        return None

    def _read_ufw_enabled(self) -> Optional[bool]:
        try:
            text = self._read_text(self._ufw_config_path)
        except (OSError, UnicodeError):
            return None
        values = []
        for line in text.splitlines():
            match = _ENABLED_RE.match(line)
            if match:
                values.append(match.group(1).lower() == "yes")
            elif _ENABLED_ASSIGNMENT_RE.match(line):
                return None
        if len(values) != 1:
            return None
        return values[0]

    def _invoke_helper(self, action: str, payload: Mapping) -> dict:
        if action not in ("status", "open", "close", "cleanup"):
            raise SpotifyFirewallCompatibilityError(
                "Invalid Spotify firewall helper action"
            )
        if not self._path_exists(self._helper_path):
            raise SpotifyFirewallCompatibilityError(
                "Spotify firewall helper is unavailable"
            )
        if not self._path_exists(self._sudo_path):
            raise SpotifyFirewallCompatibilityError(
                "Non-interactive privilege execution is unavailable"
            )
        try:
            completed = self._run(
                [self._sudo_path, "-n", self._helper_path, action],
                input=json.dumps(dict(payload), separators=(",", ":")) + "\n",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self._timeout,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            raise SpotifyFirewallCompatibilityError(
                "Spotify firewall helper could not be executed"
            ) from None
        if completed.returncode != 0:
            raise SpotifyFirewallCompatibilityError(
                "Spotify firewall helper operation failed"
            )
        try:
            response = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError):
            raise SpotifyFirewallCompatibilityError(
                "Spotify firewall helper returned an invalid response"
            ) from None
        if not isinstance(response, dict) or type(response.get("ok")) is not bool:
            raise SpotifyFirewallCompatibilityError(
                "Spotify firewall helper returned an invalid response"
            )
        if response["ok"] is not True:
            raise SpotifyFirewallCompatibilityError(
                "Spotify firewall helper operation failed"
            )
        return response

    def _first_existing(self, paths: Sequence[str]) -> Optional[str]:
        for path in paths:
            if self._path_exists(path):
                return path
        return None

    @staticmethod
    def _validated_lease(
        interface: str,
        source_cidr: str,
        destination_ipv4: str,
        port: int,
    ) -> _Lease:
        if not isinstance(interface, str) or not _INTERFACE_RE.fullmatch(interface):
            raise ValueError("invalid LAN interface")
        if interface == "lo":
            raise ValueError("loopback is not a LAN interface")
        if not isinstance(source_cidr, str):
            raise ValueError("invalid IPv4 source network")
        try:
            network = ipaddress.ip_network(source_cidr, strict=True)
        except ValueError:
            raise ValueError("invalid IPv4 source network") from None
        if network.version != 4 or network.prefixlen == 0:
            raise ValueError("invalid IPv4 source network")
        if network.is_loopback or network.is_multicast or network.is_unspecified:
            raise ValueError("invalid IPv4 source network")
        if not isinstance(destination_ipv4, str):
            raise ValueError("invalid destination IPv4 address")
        try:
            destination = ipaddress.ip_address(destination_ipv4)
        except ValueError:
            raise ValueError("invalid destination IPv4 address") from None
        if destination.version != 4 or destination not in network:
            raise ValueError("destination must be IPv4 within the source network")
        if destination.is_loopback or destination.is_multicast or destination.is_unspecified:
            raise ValueError("invalid destination IPv4 address")
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("invalid TCP port")
        return _Lease(interface, str(network), str(destination), port)
