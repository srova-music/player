"""Resolve the physical IPv4 LAN selected by Linux's main route table."""

from __future__ import annotations

import fcntl
import ipaddress
import os
import re
import socket
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class SpotifyLanNetworkResolutionError(RuntimeError):
    """The host LAN could not be resolved safely."""


@dataclass(frozen=True)
class SpotifyLanNetwork:
    interface: str
    source_cidr: str
    destination_ipv4: str


_INTERFACE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,14}\Z")


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="ascii")


class SpotifyLanNetworkResolver:
    """Resolve one main-table default interface to its canonical IPv4 LAN."""

    ROUTE_PATH = "/proc/net/route"
    SIOCGIFADDR = 0x8915
    SIOCGIFNETMASK = 0x891B

    def __init__(
        self,
        *,
        route_path: str = ROUTE_PATH,
        read_text: Callable[[str], str] = _read_text,
        socket_factory: Callable = socket.socket,
        ioctl: Callable = fcntl.ioctl,
    ) -> None:
        if not isinstance(route_path, str) or not os.path.isabs(route_path):
            raise SpotifyLanNetworkResolutionError(
                "Invalid LAN resolver configuration"
            )
        self._route_path = route_path
        self._read_text = read_text
        self._socket_factory = socket_factory
        self._ioctl = ioctl

    def resolve(self) -> SpotifyLanNetwork:
        try:
            route_text = self._read_text(self._route_path)
            interface = self._default_interface(route_text)
            address, netmask = self._interface_ipv4(interface)
            ip = ipaddress.IPv4Address(address)
            mask = ipaddress.IPv4Address(netmask)
            network = ipaddress.IPv4Network((str(ip), str(mask)), strict=False)
        except SpotifyLanNetworkResolutionError:
            raise
        except Exception:
            raise SpotifyLanNetworkResolutionError(
                "LAN network resolution failed"
            ) from None

        if (
            ip.is_loopback
            or ip.is_multicast
            or ip.is_unspecified
            or network.is_loopback
            or network.is_multicast
            or network.is_unspecified
            or network.prefixlen == 0
            or ip not in network
            or ip == network.network_address
            or ip == network.broadcast_address
        ):
            raise SpotifyLanNetworkResolutionError(
                "LAN network resolution failed"
            )
        return SpotifyLanNetwork(
            interface=interface,
            source_cidr=str(network),
            destination_ipv4=str(ip),
        )

    @staticmethod
    def _default_interface(route_text: object) -> str:
        if not isinstance(route_text, str):
            raise SpotifyLanNetworkResolutionError(
                "Main route table is unavailable"
            )
        lines = route_text.splitlines()
        if not lines or lines[0].split()[:2] != ["Iface", "Destination"]:
            raise SpotifyLanNetworkResolutionError(
                "Main route table is invalid"
            )

        candidates: list[tuple[int, str]] = []
        for line in lines[1:]:
            if not line.strip():
                continue
            fields = line.split()
            if len(fields) < 8:
                raise SpotifyLanNetworkResolutionError(
                    "Main route table is invalid"
                )
            interface = fields[0]
            try:
                destination = int(fields[1], 16)
                flags = int(fields[3], 16)
                metric = int(fields[6], 10)
                mask = int(fields[7], 16)
            except (TypeError, ValueError):
                raise SpotifyLanNetworkResolutionError(
                    "Main route table is invalid"
                ) from None
            if destination != 0 or mask != 0 or flags & 0x1 == 0:
                continue
            if (
                not _INTERFACE_PATTERN.fullmatch(interface)
                or interface == "lo"
                or metric < 0
            ):
                raise SpotifyLanNetworkResolutionError(
                    "Main route table is invalid"
                )
            candidates.append((metric, interface))

        if not candidates:
            raise SpotifyLanNetworkResolutionError(
                "Main default route is unavailable"
            )
        best_metric = min(metric for metric, _interface in candidates)
        interfaces = {
            interface
            for metric, interface in candidates
            if metric == best_metric
        }
        if len(interfaces) != 1:
            raise SpotifyLanNetworkResolutionError(
                "Main default route is ambiguous"
            )
        return next(iter(interfaces))

    def _interface_ipv4(self, interface: str) -> tuple[str, str]:
        descriptor = None
        try:
            descriptor = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
            request = struct.pack("256s", interface.encode("ascii"))
            address_raw = self._ioctl(
                descriptor.fileno(),
                self.SIOCGIFADDR,
                request,
            )
            netmask_raw = self._ioctl(
                descriptor.fileno(),
                self.SIOCGIFNETMASK,
                request,
            )
            if len(address_raw) < 24 or len(netmask_raw) < 24:
                raise ValueError("short ioctl response")
            return (
                socket.inet_ntoa(address_raw[20:24]),
                socket.inet_ntoa(netmask_raw[20:24]),
            )
        except Exception:
            raise SpotifyLanNetworkResolutionError(
                "LAN interface address is unavailable"
            ) from None
        finally:
            if descriptor is not None:
                try:
                    descriptor.close()
                except Exception:
                    pass


__all__ = [
    "SpotifyLanNetwork",
    "SpotifyLanNetworkResolutionError",
    "SpotifyLanNetworkResolver",
]
