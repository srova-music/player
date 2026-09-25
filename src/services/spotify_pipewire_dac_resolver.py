"""Resolve a numeric ALSA device to one private PipeWire playback sink."""

from __future__ import annotations

import json
import math
import os
import stat
import subprocess
import time
from collections.abc import Mapping
from typing import Any


class SpotifyPipeWireDacResolutionError(RuntimeError):
    """Raised when a private PipeWire DAC node cannot be resolved safely."""


class SpotifyPipeWireDacResolver:
    """Resolve one normalized ALSA card/device pair from an existing graph."""

    def __init__(
        self,
        *,
        pw_dump_binary: str = "/usr/bin/pw-dump",
        ready_timeout_seconds: float = 3.0,
        poll_seconds: float = 0.05,
        command_timeout_seconds: float = 2.0,
    ) -> None:
        self._pw_dump_binary = self._absolute_path(pw_dump_binary)
        self._ready_timeout_seconds = self._positive_seconds(
            ready_timeout_seconds
        )
        self._poll_seconds = self._positive_seconds(poll_seconds)
        self._command_timeout_seconds = self._positive_seconds(
            command_timeout_seconds
        )

    @property
    def pw_dump_binary(self) -> str:
        return self._pw_dump_binary

    def resolve(
        self,
        *,
        card_number: int,
        device_number: int,
        environment: Mapping[str, str],
    ) -> str:
        card = self._device_number(card_number)
        device = self._device_number(device_number)
        child_environment = self._copy_environment(environment)
        self._validate_binary()

        deadline = time.monotonic() + self._ready_timeout_seconds
        while True:
            graph = self._read_graph(child_environment)
            node_name = self._resolve_graph(graph, card, device)
            if node_name is not None:
                return node_name

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SpotifyPipeWireDacResolutionError(
                    "Private PipeWire sink was not ready"
                )
            time.sleep(min(self._poll_seconds, remaining))

    @staticmethod
    def _absolute_path(value: object) -> str:
        if not isinstance(value, str) or not value or not os.path.isabs(value):
            raise SpotifyPipeWireDacResolutionError(
                "Invalid PipeWire resolver configuration"
            )
        return value

    @staticmethod
    def _positive_seconds(value: object) -> float:
        if isinstance(value, bool):
            raise SpotifyPipeWireDacResolutionError(
                "Invalid PipeWire resolver configuration"
            )
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            raise SpotifyPipeWireDacResolutionError(
                "Invalid PipeWire resolver configuration"
            ) from None
        if not math.isfinite(seconds) or seconds <= 0:
            raise SpotifyPipeWireDacResolutionError(
                "Invalid PipeWire resolver configuration"
            )
        return seconds

    @staticmethod
    def _device_number(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SpotifyPipeWireDacResolutionError(
                "Invalid PipeWire resolver input"
            )
        return value

    @staticmethod
    def _copy_environment(environment: object) -> dict[str, str]:
        if not isinstance(environment, Mapping):
            raise SpotifyPipeWireDacResolutionError(
                "Invalid PipeWire resolver input"
            )
        try:
            copied = dict(environment)
        except Exception:
            raise SpotifyPipeWireDacResolutionError(
                "Invalid PipeWire resolver input"
            ) from None
        if not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in copied.items()
        ):
            raise SpotifyPipeWireDacResolutionError(
                "Invalid PipeWire resolver input"
            )
        return copied

    def _validate_binary(self) -> None:
        try:
            mode = os.lstat(self._pw_dump_binary).st_mode
        except OSError:
            raise SpotifyPipeWireDacResolutionError(
                "pw-dump binary is unavailable"
            ) from None
        if (
            stat.S_ISLNK(mode)
            or not stat.S_ISREG(mode)
            or not os.access(self._pw_dump_binary, os.X_OK)
        ):
            raise SpotifyPipeWireDacResolutionError(
                "pw-dump binary is unavailable"
            )

    def _read_graph(self, environment: dict[str, str]) -> list[Any]:
        try:
            completed = subprocess.run(
                [self._pw_dump_binary],
                check=False,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                close_fds=True,
                shell=False,
                timeout=self._command_timeout_seconds,
            )
        except Exception:
            raise SpotifyPipeWireDacResolutionError(
                "Private PipeWire graph inspection failed"
            ) from None

        if completed.returncode != 0 or not isinstance(completed.stdout, str):
            raise SpotifyPipeWireDacResolutionError(
                "Private PipeWire graph inspection failed"
            )
        try:
            graph = json.loads(completed.stdout)
        except (TypeError, ValueError):
            raise SpotifyPipeWireDacResolutionError(
                "Private PipeWire graph is invalid"
            ) from None
        if not isinstance(graph, list):
            raise SpotifyPipeWireDacResolutionError(
                "Private PipeWire graph is invalid"
            )
        return graph

    def _resolve_graph(
        self,
        graph: list[Any],
        card_number: int,
        device_number: int,
    ) -> str | None:
        matches: list[str] = []
        for graph_object in graph:
            properties = self._properties(graph_object)
            if properties is None:
                continue
            if properties.get("media.class") != "Audio/Sink":
                continue
            if self._numeric_property(properties.get("alsa.card")) != card_number:
                continue
            if (
                self._numeric_property(properties.get("alsa.device"))
                != device_number
            ):
                continue
            if properties.get("api.alsa.pcm.stream") != "playback":
                continue

            if (
                "api.alsa.pcm.card" in properties
                and properties["api.alsa.pcm.card"] is not None
            ):
                cross_check = self._numeric_property(
                    properties["api.alsa.pcm.card"]
                )
                if cross_check != card_number:
                    raise SpotifyPipeWireDacResolutionError(
                        "Private PipeWire sink identity is unsafe"
                    )

            node_name = properties.get("node.name")
            if not isinstance(node_name, str) or not node_name.strip():
                raise SpotifyPipeWireDacResolutionError(
                    "Private PipeWire sink identity is unsafe"
                )
            matches.append(node_name)
            if len(matches) > 1:
                raise SpotifyPipeWireDacResolutionError(
                    "Private PipeWire sink resolution is ambiguous"
                )

        return matches[0] if matches else None

    @staticmethod
    def _properties(graph_object: object) -> dict[str, Any] | None:
        if not isinstance(graph_object, dict):
            raise SpotifyPipeWireDacResolutionError(
                "Private PipeWire graph is invalid"
            )
        if "type" in graph_object:
            object_type = graph_object["type"]
            if not isinstance(object_type, str):
                raise SpotifyPipeWireDacResolutionError(
                    "Private PipeWire graph is invalid"
                )
            if object_type != "PipeWire:Interface:Node":
                return None
        info = graph_object.get("info")
        if not isinstance(info, dict):
            raise SpotifyPipeWireDacResolutionError(
                "Private PipeWire graph is invalid"
            )
        properties = info.get("props")
        if not isinstance(properties, dict):
            raise SpotifyPipeWireDacResolutionError(
                "Private PipeWire graph is invalid"
            )
        return properties

    @staticmethod
    def _numeric_property(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value >= 0 else None
        if (
            isinstance(value, str)
            and value
            and value.isascii()
            and value.isdecimal()
        ):
            return int(value)
        return None
