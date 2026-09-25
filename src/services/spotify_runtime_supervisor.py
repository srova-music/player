"""Direct supervisor for SROVA's isolated Spotify PipeWire graph.

This module intentionally does not know about Spotify credentials, Soloist,
the Spotify ownership coordinator, native SROVA playback, or HTTP APIs.
"""

from __future__ import annotations

import os
import stat
import subprocess
import threading
import time
from typing import Dict, Optional, Sequence


class SpotifyRuntimeError(RuntimeError):
    """The isolated Spotify audio runtime could not be managed safely."""


class SpotifyRuntimeSupervisor:
    """Own an isolated PipeWire + WirePlumber process graph.

    Construction is side-effect free. The graph is created only by
    start_private_graph() and can remain alive while no PCM is owned.
    """

    DEFAULT_RUNTIME_PARENT = "/run/srova"
    PRIVATE_RUNTIME_NAME = "spotify"
    PIPEWIRE_SOCKET_NAME = "pipewire-0"

    PIPEWIRE_BINARY = "/usr/bin/pipewire"
    WIREPLUMBER_BINARY = "/usr/bin/wireplumber"
    WIREPLUMBER_PROFILE = "main-systemwide"

    PIPEWIRE_READY_TIMEOUT_SECONDS = 5.0
    WIREPLUMBER_STABILITY_SECONDS = 0.25
    PROCESS_STOP_TIMEOUT_SECONDS = 3.0
    READY_POLL_SECONDS = 0.05
    CHILD_ENVIRONMENT_KEYS = (
        "HOME",
        "USER",
        "LOGNAME",
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "XDG_DATA_DIRS",
    )

    RUNTIME_ENDPOINT_NAMES = (
        "pipewire-0",
        "pipewire-0.lock",
        "pipewire-0-manager",
        "pipewire-0-manager.lock",
    )

    def __init__(
        self,
        *,
        runtime_dir: Optional[str] = None,
        pipewire_binary: Optional[str] = None,
        wireplumber_binary: Optional[str] = None,
    ) -> None:
        self._lock = threading.RLock()

        self._runtime_dir = self._resolve_runtime_dir(
            runtime_dir
        )
        self._pipewire_binary = os.path.abspath(
            pipewire_binary or self.PIPEWIRE_BINARY
        )
        self._wireplumber_binary = os.path.abspath(
            wireplumber_binary or self.WIREPLUMBER_BINARY
        )

        self._pipewire_process = None
        self._wireplumber_process = None

    @classmethod
    def _resolve_runtime_dir(
        cls,
        explicit: Optional[str],
    ) -> str:
        if explicit is not None:
            value = str(explicit).strip()
        else:
            override = str(
                os.environ.get(
                    "SROVA_SPOTIFY_RUNTIME_DIR",
                    "",
                )
                or ""
            ).strip()

            if override:
                value = override
            else:
                systemd_runtime = str(
                    os.environ.get(
                        "RUNTIME_DIRECTORY",
                        "",
                    )
                    or ""
                ).strip()

                # systemd represents multiple RuntimeDirectory entries
                # as a colon-separated path list in this environment.
                if systemd_runtime:
                    parent = systemd_runtime.split(":", 1)[0]
                else:
                    parent = cls.DEFAULT_RUNTIME_PARENT

                value = os.path.join(
                    parent,
                    cls.PRIVATE_RUNTIME_NAME,
                )

        if not value or not os.path.isabs(value):
            raise SpotifyRuntimeError(
                "Spotify runtime directory must be absolute"
            )

        return os.path.normpath(value)

    @property
    def runtime_dir(self) -> str:
        return self._runtime_dir

    @property
    def pipewire_socket(self) -> str:
        return os.path.join(
            self._runtime_dir,
            self.PIPEWIRE_SOCKET_NAME,
        )

    def status_snapshot(self) -> Dict[str, bool]:
        """Return non-secret internal process health."""
        with self._lock:
            return {
                "pipewire_running": self._process_alive(
                    self._pipewire_process
                ),
                "wireplumber_running": self._process_alive(
                    self._wireplumber_process
                ),
            }

    def private_environment(self) -> Dict[str, str]:
        """Return the environment used only for the private audio graph."""
        env = {
            name: os.environ[name]
            for name in self.CHILD_ENVIRONMENT_KEYS
            if name in os.environ
        }

        env["XDG_RUNTIME_DIR"] = self._runtime_dir
        env["PIPEWIRE_RUNTIME_DIR"] = self._runtime_dir

        return env

    def pipewire_command(self) -> Sequence[str]:
        return (
            self._pipewire_binary,
        )

    def wireplumber_command(self) -> Sequence[str]:
        return (
            self._wireplumber_binary,
            "--profile",
            self.WIREPLUMBER_PROFILE,
        )

    def start_private_graph(self) -> bool:
        """Start PipeWire then WirePlumber.

        Returns True when this call started the graph, False when an already
        healthy graph owned by this supervisor was left running.
        """
        with self._lock:
            if self._graph_healthy_locked():
                return False

            # A partial/crashed graph must not be stacked with new children.
            self._stop_private_graph_locked()

            self._prepare_runtime_dir()
            self._clear_stale_runtime_endpoints()
            env = self.private_environment()

            try:
                self._pipewire_process = self._spawn(
                    self.pipewire_command(),
                    env,
                )

                self._wait_for_pipewire_ready()

                self._wireplumber_process = self._spawn(
                    self.wireplumber_command(),
                    env,
                )

                self._wait_for_wireplumber_ready()

            except Exception as exc:
                self._stop_private_graph_locked()

                if isinstance(exc, SpotifyRuntimeError):
                    raise

                raise SpotifyRuntimeError(
                    "Spotify private audio graph failed to start"
                ) from exc

            return True

    def stop_private_graph(self) -> None:
        with self._lock:
            self._stop_private_graph_locked()

    def _prepare_runtime_dir(self) -> None:
        try:
            os.makedirs(
                self._runtime_dir,
                mode=0o700,
                exist_ok=True,
            )
            info = os.lstat(self._runtime_dir)
        except OSError as exc:
            raise SpotifyRuntimeError(
                "Spotify runtime directory is unavailable"
            ) from exc

        if not stat.S_ISDIR(info.st_mode):
            raise SpotifyRuntimeError(
                "Spotify runtime directory is invalid"
            )

        try:
            os.chmod(
                self._runtime_dir,
                0o700,
            )
        except OSError as exc:
            raise SpotifyRuntimeError(
                "Spotify runtime directory permissions could not be secured"
            ) from exc

    def _clear_stale_runtime_endpoints(self) -> None:
        """Remove only known stale PipeWire endpoint artifacts."""

        for name in self.RUNTIME_ENDPOINT_NAMES:
            path = os.path.join(
                self._runtime_dir,
                name,
            )

            try:
                info = os.lstat(path)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise SpotifyRuntimeError(
                    "Spotify runtime endpoint could not be inspected"
                ) from exc

            if not (
                stat.S_ISSOCK(info.st_mode)
                or stat.S_ISREG(info.st_mode)
            ):
                raise SpotifyRuntimeError(
                    "Spotify runtime endpoint artifact is invalid"
                )

            try:
                os.unlink(path)
            except OSError as exc:
                raise SpotifyRuntimeError(
                    "Spotify stale runtime endpoint could not be removed"
                ) from exc

    def _spawn(
        self,
        command: Sequence[str],
        env: Dict[str, str],
    ):
        for executable in (
            self._pipewire_binary,
            self._wireplumber_binary,
        ):
            if not os.path.isabs(executable):
                raise SpotifyRuntimeError(
                    "Spotify runtime executable path is invalid"
                )

        try:
            return subprocess.Popen(
                list(command),
                env=env,
                stdin=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as exc:
            raise SpotifyRuntimeError(
                "Spotify runtime process could not be started"
            ) from exc

    def _wait_for_pipewire_ready(self) -> None:
        deadline = (
            time.monotonic()
            + self.PIPEWIRE_READY_TIMEOUT_SECONDS
        )

        while time.monotonic() < deadline:
            if not self._process_alive(
                self._pipewire_process
            ):
                raise SpotifyRuntimeError(
                    "PipeWire exited during startup"
                )

            try:
                info = os.stat(
                    self.pipewire_socket,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                info = None
            except OSError as exc:
                raise SpotifyRuntimeError(
                    "PipeWire runtime socket could not be inspected"
                ) from exc

            if (
                info is not None
                and stat.S_ISSOCK(info.st_mode)
            ):
                return

            time.sleep(
                self.READY_POLL_SECONDS
            )

        raise SpotifyRuntimeError(
            "PipeWire did not become ready"
        )

    def _wait_for_wireplumber_ready(self) -> None:
        """Require WirePlumber to remain alive for a bounded interval."""

        deadline = (
            time.monotonic()
            + self.WIREPLUMBER_STABILITY_SECONDS
        )

        while time.monotonic() < deadline:
            if not self._process_alive(
                self._wireplumber_process
            ):
                raise SpotifyRuntimeError(
                    "WirePlumber exited during startup"
                )

            remaining = max(
                0.0,
                deadline - time.monotonic(),
            )
            if remaining <= 0:
                break

            time.sleep(
                min(
                    self.READY_POLL_SECONDS,
                    remaining,
                )
            )

        if not self._process_alive(
            self._wireplumber_process
        ):
            raise SpotifyRuntimeError(
                "WirePlumber exited during startup"
            )

    def _stop_private_graph_locked(self) -> None:
        # Policy manager first, audio server second.
        self._terminate_process(
            self._wireplumber_process
        )
        self._wireplumber_process = None

        self._terminate_process(
            self._pipewire_process
        )
        self._pipewire_process = None

    def _terminate_process(self, process) -> None:
        if not self._process_alive(process):
            return

        try:
            process.terminate()
            process.wait(
                timeout=self.PROCESS_STOP_TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                return

            try:
                process.wait(
                    timeout=self.PROCESS_STOP_TIMEOUT_SECONDS
                )
            except subprocess.TimeoutExpired as exc:
                raise SpotifyRuntimeError(
                    "Spotify runtime process did not terminate"
                ) from exc
        except ProcessLookupError:
            return
        except OSError as exc:
            raise SpotifyRuntimeError(
                "Spotify runtime process could not be terminated"
            ) from exc

    def _graph_healthy_locked(self) -> bool:
        return (
            self._process_alive(
                self._pipewire_process
            )
            and self._process_alive(
                self._wireplumber_process
            )
        )

    @staticmethod
    def _process_alive(process) -> bool:
        if process is None:
            return False

        try:
            return process.poll() is None
        except Exception:
            return False


__all__ = [
    "SpotifyRuntimeError",
    "SpotifyRuntimeSupervisor",
]
