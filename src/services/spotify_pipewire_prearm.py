"""Verified pre-arm barriers for the private Spotify PipeWire graph."""

from __future__ import annotations

import json
import math
import os
import re
import stat
import subprocess
from collections.abc import Mapping
from typing import Any


class SpotifyPipeWirePrearmError(RuntimeError):
    """The private PipeWire graph could not be pre-armed safely."""


class SpotifyPipeWirePrearm:
    """Apply and verify rate and volume barriers before Soloist starts."""

    PW_DUMP_BINARY = "/usr/bin/pw-dump"
    PW_METADATA_BINARY = "/usr/bin/pw-metadata"
    WPCTL_BINARY = "/usr/bin/wpctl"
    FORCE_RATE = 44100
    UNITY_TOLERANCE = 0.000001
    _VOLUME_PATTERN = re.compile(
        r"^\s*Volume:\s*([0-9]+(?:\.[0-9]+)?)\s*$"
    )

    def __init__(
        self,
        *,
        pw_dump_binary: str = PW_DUMP_BINARY,
        pw_metadata_binary: str = PW_METADATA_BINARY,
        wpctl_binary: str = WPCTL_BINARY,
        command_timeout_seconds: float = 2.0,
    ) -> None:
        self._pw_dump_binary = self._absolute_path(pw_dump_binary)
        self._pw_metadata_binary = self._absolute_path(pw_metadata_binary)
        self._wpctl_binary = self._absolute_path(wpctl_binary)
        self._command_timeout_seconds = self._positive_seconds(
            command_timeout_seconds
        )

    def prearm(
        self,
        *,
        card_number: int,
        device_number: int,
        pipewire_node_name: str,
        environment: Mapping[str, str],
    ) -> None:
        card = self._device_number(card_number)
        device = self._device_number(device_number)
        node_name = self._node_name(pipewire_node_name)
        child_environment = self._copy_environment(environment)
        self._validate_binaries()

        graph = self._read_graph(child_environment)
        self._exact_sink_id(graph, card, device, node_name)

        self._run(
            [
                self._pw_metadata_binary,
                "-n",
                "settings",
                "0",
                "clock.force-rate",
                str(self.FORCE_RATE),
            ],
            child_environment,
        )

        verified_graph = self._read_graph(child_environment)
        sink_id = self._exact_sink_id(
            verified_graph,
            card,
            device,
            node_name,
        )
        self._verify_force_rate(verified_graph)

        self._run(
            [self._wpctl_binary, "set-volume", str(sink_id), "1.0"],
            child_environment,
        )
        self._run(
            [self._wpctl_binary, "set-mute", str(sink_id), "0"],
            child_environment,
        )
        completed = self._run(
            [self._wpctl_binary, "get-volume", str(sink_id)],
            child_environment,
        )
        self._verify_unity_volume(completed.stdout)

    @staticmethod
    def _absolute_path(value: object) -> str:
        if not isinstance(value, str) or not value or not os.path.isabs(value):
            raise SpotifyPipeWirePrearmError(
                "Invalid PipeWire pre-arm configuration"
            )
        return value

    @staticmethod
    def _positive_seconds(value: object) -> float:
        if isinstance(value, bool):
            raise SpotifyPipeWirePrearmError(
                "Invalid PipeWire pre-arm configuration"
            )
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            raise SpotifyPipeWirePrearmError(
                "Invalid PipeWire pre-arm configuration"
            ) from None
        if not math.isfinite(seconds) or seconds <= 0:
            raise SpotifyPipeWirePrearmError(
                "Invalid PipeWire pre-arm configuration"
            )
        return seconds

    @staticmethod
    def _device_number(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SpotifyPipeWirePrearmError("Invalid PipeWire pre-arm input")
        return value

    @staticmethod
    def _node_name(value: object) -> str:
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > 512
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise SpotifyPipeWirePrearmError("Invalid PipeWire pre-arm input")
        return value

    @staticmethod
    def _copy_environment(environment: object) -> dict[str, str]:
        if not isinstance(environment, Mapping):
            raise SpotifyPipeWirePrearmError("Invalid PipeWire pre-arm input")
        try:
            copied = dict(environment)
        except Exception:
            raise SpotifyPipeWirePrearmError(
                "Invalid PipeWire pre-arm input"
            ) from None
        if not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in copied.items()
        ):
            raise SpotifyPipeWirePrearmError("Invalid PipeWire pre-arm input")
        return copied

    def _validate_binaries(self) -> None:
        for binary in (
            self._pw_dump_binary,
            self._pw_metadata_binary,
            self._wpctl_binary,
        ):
            try:
                mode = os.lstat(binary).st_mode
            except OSError:
                raise SpotifyPipeWirePrearmError(
                    "PipeWire pre-arm binary is unavailable"
                ) from None
            if (
                stat.S_ISLNK(mode)
                or not stat.S_ISREG(mode)
                or not os.access(binary, os.X_OK)
            ):
                raise SpotifyPipeWirePrearmError(
                    "PipeWire pre-arm binary is unavailable"
                )

    def _run(
        self,
        command: list[str],
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess:
        try:
            completed = subprocess.run(
                command,
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
            raise SpotifyPipeWirePrearmError(
                "Private PipeWire pre-arm command failed"
            ) from None
        if completed.returncode != 0 or not isinstance(completed.stdout, str):
            raise SpotifyPipeWirePrearmError(
                "Private PipeWire pre-arm command failed"
            )
        return completed

    def _read_graph(self, environment: dict[str, str]) -> list[Any]:
        completed = self._run([self._pw_dump_binary], environment)
        try:
            graph = json.loads(completed.stdout)
        except (TypeError, ValueError):
            raise SpotifyPipeWirePrearmError(
                "Private PipeWire pre-arm graph is invalid"
            ) from None
        if not isinstance(graph, list):
            raise SpotifyPipeWirePrearmError(
                "Private PipeWire pre-arm graph is invalid"
            )
        return graph

    def _exact_sink_id(
        self,
        graph: list[Any],
        card_number: int,
        device_number: int,
        node_name: str,
    ) -> int:
        matches: list[int] = []
        for graph_object in graph:
            if not isinstance(graph_object, dict):
                raise SpotifyPipeWirePrearmError(
                    "Private PipeWire pre-arm graph is invalid"
                )
            object_type = graph_object.get("type")
            if not isinstance(object_type, str):
                raise SpotifyPipeWirePrearmError(
                    "Private PipeWire pre-arm graph is invalid"
                )
            if object_type != "PipeWire:Interface:Node":
                continue

            info = graph_object.get("info")
            properties = info.get("props") if isinstance(info, dict) else None
            if not isinstance(properties, dict):
                raise SpotifyPipeWirePrearmError(
                    "Private PipeWire pre-arm graph is invalid"
                )
            if properties.get("media.class") != "Audio/Sink":
                continue
            if properties.get("node.name") != node_name:
                continue
            if self._numeric_property(properties.get("alsa.card")) != card_number:
                raise SpotifyPipeWirePrearmError(
                    "Private PipeWire sink identity is unsafe"
                )
            if (
                self._numeric_property(properties.get("alsa.device"))
                != device_number
                or properties.get("api.alsa.pcm.stream") != "playback"
            ):
                raise SpotifyPipeWirePrearmError(
                    "Private PipeWire sink identity is unsafe"
                )
            if (
                "api.alsa.pcm.card" in properties
                and properties["api.alsa.pcm.card"] is not None
                and self._numeric_property(properties["api.alsa.pcm.card"])
                != card_number
            ):
                raise SpotifyPipeWirePrearmError(
                    "Private PipeWire sink identity is unsafe"
                )

            object_id = graph_object.get("id")
            if (
                isinstance(object_id, bool)
                or not isinstance(object_id, int)
                or object_id < 0
            ):
                raise SpotifyPipeWirePrearmError(
                    "Private PipeWire sink identity is unsafe"
                )
            matches.append(object_id)

        if len(matches) != 1:
            raise SpotifyPipeWirePrearmError(
                "Private PipeWire sink identity is unavailable"
            )
        return matches[0]

    def _verify_force_rate(self, graph: list[Any]) -> None:
        settings_objects: list[dict[str, Any]] = []
        for graph_object in graph:
            if not isinstance(graph_object, dict):
                raise SpotifyPipeWirePrearmError(
                    "Private PipeWire pre-arm graph is invalid"
                )
            if graph_object.get("type") != "PipeWire:Interface:Metadata":
                continue
            properties = graph_object.get("props")
            if not isinstance(properties, dict):
                info = graph_object.get("info")
                properties = info.get("props") if isinstance(info, dict) else None
            if isinstance(properties, dict) and properties.get("metadata.name") == "settings":
                settings_objects.append(graph_object)

        if len(settings_objects) != 1:
            raise SpotifyPipeWirePrearmError(
                "Private PipeWire rate verification failed"
            )
        metadata = settings_objects[0].get("metadata")
        if not isinstance(metadata, list):
            raise SpotifyPipeWirePrearmError(
                "Private PipeWire rate verification failed"
            )
        values = []
        for entry in metadata:
            if not isinstance(entry, dict):
                raise SpotifyPipeWirePrearmError(
                    "Private PipeWire rate verification failed"
                )
            if entry.get("subject") == 0 and entry.get("key") == "clock.force-rate":
                values.append(entry.get("value"))
        if len(values) != 1 or not (
            (type(values[0]) is int and values[0] == self.FORCE_RATE)
            or values[0] == str(self.FORCE_RATE)
        ):
            raise SpotifyPipeWirePrearmError(
                "Private PipeWire rate verification failed"
            )

    def _verify_unity_volume(self, output: str) -> None:
        match = self._VOLUME_PATTERN.fullmatch(output)
        if match is None:
            raise SpotifyPipeWirePrearmError(
                "Private PipeWire volume verification failed"
            )
        try:
            volume = float(match.group(1))
        except (TypeError, ValueError):
            raise SpotifyPipeWirePrearmError(
                "Private PipeWire volume verification failed"
            ) from None
        if not math.isfinite(volume) or abs(volume - 1.0) > self.UNITY_TOLERANCE:
            raise SpotifyPipeWirePrearmError(
                "Private PipeWire volume verification failed"
            )

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


__all__ = ["SpotifyPipeWirePrearm", "SpotifyPipeWirePrearmError"]
