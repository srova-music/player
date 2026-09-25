"""Resolve Soloist's process-owned IPv4 LAN listener from procfs."""

from __future__ import annotations

import ipaddress
import math
import os
import re
import socket
import time
from pathlib import Path
from typing import Callable


class SpotifySoloistListenerResolutionError(RuntimeError):
    """Soloist's LAN listener could not be resolved safely."""


_SOCKET_LINK_PATTERN = re.compile(r"socket:\[([0-9]+)\]\Z")


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="ascii")


class SpotifySoloistLanListenerResolver:
    """Map one live PID's socket inodes to one non-loopback TCP listener."""

    def __init__(
        self,
        *,
        proc_root: str = "/proc",
        timeout_seconds: float = 2.0,
        poll_seconds: float = 0.05,
        read_text: Callable[[str], str] = _read_text,
        readlink: Callable[[str], str] = os.readlink,
        listdir: Callable[[str], list[str]] = os.listdir,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(proc_root, str) or not os.path.isabs(proc_root):
            raise SpotifySoloistListenerResolutionError(
                "Invalid Soloist listener resolver configuration"
            )
        self._proc_root = proc_root
        self._timeout_seconds = self._positive_seconds(timeout_seconds)
        self._poll_seconds = self._positive_seconds(poll_seconds)
        self._read_text = read_text
        self._readlink = readlink
        self._listdir = listdir
        self._monotonic = monotonic
        self._sleep = sleep

    def resolve(self, *, process_id: int) -> int:
        if type(process_id) is not int or process_id <= 0:
            raise SpotifySoloistListenerResolutionError(
                "Invalid Soloist listener resolver input"
            )
        deadline = self._monotonic() + self._timeout_seconds
        while True:
            inodes = self._owned_socket_inodes(process_id)
            table = self._read_tcp_table()
            listeners = self._qualifying_listeners(table, inodes)
            self._assert_process_live(process_id)
            if len(listeners) == 1:
                return listeners[0]
            if len(listeners) > 1:
                raise SpotifySoloistListenerResolutionError(
                    "Soloist LAN listener is ambiguous"
                )

            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise SpotifySoloistListenerResolutionError(
                    "Soloist LAN listener is unavailable"
                )
            self._sleep(min(self._poll_seconds, remaining))

    @staticmethod
    def _positive_seconds(value: object) -> float:
        if isinstance(value, bool):
            raise SpotifySoloistListenerResolutionError(
                "Invalid Soloist listener resolver configuration"
            )
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            raise SpotifySoloistListenerResolutionError(
                "Invalid Soloist listener resolver configuration"
            ) from None
        if not math.isfinite(seconds) or seconds <= 0:
            raise SpotifySoloistListenerResolutionError(
                "Invalid Soloist listener resolver configuration"
            )
        return seconds

    def _fd_path(self, process_id: int) -> str:
        return os.path.join(self._proc_root, str(process_id), "fd")

    def _assert_process_live(self, process_id: int) -> None:
        try:
            self._listdir(self._fd_path(process_id))
        except Exception:
            raise SpotifySoloistListenerResolutionError(
                "Soloist process is unavailable"
            ) from None

    def _owned_socket_inodes(self, process_id: int) -> set[str]:
        fd_path = self._fd_path(process_id)
        try:
            names = self._listdir(fd_path)
        except Exception:
            raise SpotifySoloistListenerResolutionError(
                "Soloist process is unavailable"
            ) from None
        if not isinstance(names, (list, tuple)):
            raise SpotifySoloistListenerResolutionError(
                "Soloist process descriptors are invalid"
            )

        inodes = set()
        for name in names:
            if not isinstance(name, str) or not name.isdecimal():
                raise SpotifySoloistListenerResolutionError(
                    "Soloist process descriptors are invalid"
                )
            try:
                target = self._readlink(os.path.join(fd_path, name))
            except FileNotFoundError:
                continue
            except Exception:
                raise SpotifySoloistListenerResolutionError(
                    "Soloist process descriptors are unavailable"
                ) from None
            if not isinstance(target, str):
                raise SpotifySoloistListenerResolutionError(
                    "Soloist process descriptors are invalid"
                )
            match = _SOCKET_LINK_PATTERN.fullmatch(target)
            if match is not None:
                inodes.add(match.group(1))
        return inodes

    def _read_tcp_table(self) -> str:
        try:
            table = self._read_text(os.path.join(self._proc_root, "net", "tcp"))
        except Exception:
            raise SpotifySoloistListenerResolutionError(
                "TCP listener table is unavailable"
            ) from None
        if not isinstance(table, str):
            raise SpotifySoloistListenerResolutionError(
                "TCP listener table is invalid"
            )
        return table

    @staticmethod
    def _qualifying_listeners(table: str, owned_inodes: set[str]) -> list[int]:
        lines = table.splitlines()
        if not lines or "local_address" not in lines[0] or "inode" not in lines[0]:
            raise SpotifySoloistListenerResolutionError(
                "TCP listener table is invalid"
            )

        listeners = set()
        for line in lines[1:]:
            if not line.strip():
                continue
            fields = line.split()
            if len(fields) < 10:
                raise SpotifySoloistListenerResolutionError(
                    "TCP listener table is invalid"
                )
            local = fields[1]
            state = fields[3]
            inode = fields[9]
            if not inode.isdecimal() or re.fullmatch(r"[0-9A-Fa-f]{2}", state) is None:
                raise SpotifySoloistListenerResolutionError(
                    "TCP listener table is invalid"
                )
            try:
                address_hex, port_hex = local.split(":", 1)
                if len(address_hex) != 8 or len(port_hex) != 4:
                    raise ValueError
                address = ipaddress.IPv4Address(
                    socket.inet_ntoa(bytes.fromhex(address_hex)[::-1])
                )
                port = int(port_hex, 16)
            except (OSError, TypeError, ValueError):
                raise SpotifySoloistListenerResolutionError(
                    "TCP listener table is invalid"
                ) from None
            if not 1 <= port <= 65535:
                raise SpotifySoloistListenerResolutionError(
                    "TCP listener table is invalid"
                )
            if state.upper() != "0A" or inode not in owned_inodes:
                continue
            if address.is_loopback:
                continue
            if address.is_multicast:
                raise SpotifySoloistListenerResolutionError(
                    "Soloist LAN listener is invalid"
                )
            listeners.add(port)
        return sorted(listeners)


__all__ = [
    "SpotifySoloistLanListenerResolver",
    "SpotifySoloistListenerResolutionError",
]
