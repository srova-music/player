"""Narrow child-process supervisor for the official Soloist executable."""

from __future__ import annotations

import os
import socket
import stat
import subprocess
import threading
import time
from collections.abc import Mapping
from typing import Optional


class SpotifySoloistError(RuntimeError):
    """The Soloist child could not be managed safely."""


class SpotifySoloistSupervisor:
    """Own one Soloist child and its bounded readiness artifacts."""

    CONTROL_ARTIFACTS = (
        "ws.port",
        "ws.addr",
        "soloist.pid",
    )
    MAX_WS_PORT_BYTES = 16
    REDACTED_ARGUMENT = "<redacted>"

    def __init__(
        self,
        *,
        binary_path: str,
        data_dir: str,
        cache_dir: str,
        ready_timeout_seconds: float = 5.0,
        stop_timeout_seconds: float = 3.0,
        poll_seconds: float = 0.05,
    ) -> None:
        self._binary_path = self._absolute_path(
            binary_path,
            "Soloist binary path",
        )
        self._data_dir = self._absolute_path(
            data_dir,
            "Soloist data directory",
        )
        self._cache_dir = self._absolute_path(
            cache_dir,
            "Soloist cache directory",
        )
        if os.path.normcase(self._data_dir) == os.path.normcase(
            self._cache_dir
        ):
            raise SpotifySoloistError(
                "Soloist data and cache directories must be distinct"
            )

        self._ready_timeout_seconds = self._positive_seconds(
            ready_timeout_seconds,
            "Soloist readiness timeout",
        )
        self._stop_timeout_seconds = self._positive_seconds(
            stop_timeout_seconds,
            "Soloist stop timeout",
        )
        self._poll_seconds = self._positive_seconds(
            poll_seconds,
            "Soloist poll interval",
        )

        self._lock = threading.RLock()
        self._process = None
        self._ready = False
        self._ws_port = None

    @staticmethod
    def _absolute_path(value: str, label: str) -> str:
        path = str(value or "").strip()
        if not path or not os.path.isabs(path):
            raise SpotifySoloistError(f"{label} must be absolute")
        return os.path.normpath(path)

    @staticmethod
    def _positive_seconds(value: float, label: str) -> float:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            raise SpotifySoloistError(f"{label} is invalid") from None
        if seconds <= 0:
            raise SpotifySoloistError(f"{label} is invalid")
        return seconds

    @property
    def data_dir(self) -> str:
        return self._data_dir

    @property
    def cache_dir(self) -> str:
        return self._cache_dir

    @property
    def ws_port(self) -> Optional[int]:
        with self._lock:
            if not self._process_alive(self._process):
                return None
            return self._ws_port if self._ready else None

    @property
    def process_id(self) -> Optional[int]:
        with self._lock:
            process = self._process
            try:
                if process is None or process.poll() is not None:
                    return None
                process_id = process.pid
            except Exception:
                return None
            if type(process_id) is not int or process_id <= 0:
                return None
            return process_id

    def status_snapshot(self) -> dict:
        with self._lock:
            running = self._process_alive(self._process)
            if not running:
                self._ready = False
                self._ws_port = None
            return {
                "soloist_running": running,
                "ready": bool(running and self._ready),
                "ws_port": self._ws_port if running and self._ready else None,
            }

    def start(
        self,
        *,
        api_key: str,
        device_name: str,
        pipewire_node_name: str,
        environment: Mapping[str, str],
    ) -> bool:
        with self._lock:
            if self._healthy_locked():
                return False

            self._stop_locked()
            self._prepare_directory(self._data_dir)
            self._prepare_directory(self._cache_dir)
            self._validate_binary()
            self._clear_control_artifacts()

            if not isinstance(environment, Mapping):
                raise SpotifySoloistError(
                    "Soloist environment is invalid"
                )
            if not all(
                isinstance(value, str) and value
                for value in (
                    api_key,
                    device_name,
                    pipewire_node_name,
                )
            ):
                raise SpotifySoloistError(
                    "Soloist launch parameters are invalid"
                )

            child_environment = dict(environment)
            command = [
                self._binary_path,
                "-n",
                device_name,
                "-D",
                self._data_dir,
                "-C",
                self._cache_dir,
                "-d",
                pipewire_node_name,
                "-w",
                "127.0.0.1:0",
                "-k",
                api_key,
            ]

            process = None
            try:
                process = self._spawn(
                    command,
                    child_environment,
                )
                self._process = process
            except Exception:
                self._redact_command(command, process)
                self._process = None
                self._ready = False
                self._ws_port = None
                self._clear_control_artifacts()
                raise SpotifySoloistError(
                    "Soloist process could not be started"
                ) from None

            self._redact_command(command, process)

            try:
                port = self._wait_until_ready()
            except Exception:
                try:
                    self._stop_locked()
                except SpotifySoloistError:
                    pass
                raise SpotifySoloistError(
                    "Soloist did not become ready"
                ) from None

            self._ready = True
            self._ws_port = port
            return True

    def deactivate(self) -> bool:
        """Give up active Spotify Connect status without stopping Soloist."""

        with self._lock:
            if not self._healthy_locked():
                raise SpotifySoloistError(
                    "Soloist control is unavailable"
                )

            port = self._ws_port
            if (
                isinstance(port, bool)
                or not isinstance(port, int)
                or port < 1
                or port > 65535
            ):
                raise SpotifySoloistError(
                    "Soloist control is unavailable"
                )

            command = [
                self._binary_path,
                "ctl",
                "-w",
                f"127.0.0.1:{port}",
                "deactivate",
            ]

            try:
                completed = subprocess.run(
                    command,
                    env={},
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=self._stop_timeout_seconds,
                    close_fds=True,
                    start_new_session=True,
                    shell=False,
                    check=False,
                )
            except Exception:
                raise SpotifySoloistError(
                    "Soloist active device could not be released"
                ) from None

            if completed.returncode != 0:
                raise SpotifySoloistError(
                    "Soloist active device could not be released"
                )

            return True

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _prepare_directory(self, path: str) -> None:
        try:
            os.makedirs(path, mode=0o700, exist_ok=True)
            info = os.lstat(path)
        except OSError:
            raise SpotifySoloistError(
                "Soloist private directory is unavailable"
            ) from None

        if not stat.S_ISDIR(info.st_mode):
            raise SpotifySoloistError(
                "Soloist private directory is invalid"
            )

        try:
            os.chmod(path, 0o700)
        except OSError:
            raise SpotifySoloistError(
                "Soloist private directory could not be secured"
            ) from None

    def _validate_binary(self) -> None:
        try:
            info = os.lstat(self._binary_path)
        except OSError:
            raise SpotifySoloistError(
                "Soloist executable is unavailable"
            ) from None

        if (
            not stat.S_ISREG(info.st_mode)
            or not os.access(self._binary_path, os.X_OK)
        ):
            raise SpotifySoloistError(
                "Soloist executable is invalid"
            )

    def _clear_control_artifacts(self) -> None:
        for name in self.CONTROL_ARTIFACTS:
            path = os.path.join(self._data_dir, name)
            try:
                info = os.lstat(path)
            except FileNotFoundError:
                continue
            except OSError:
                raise SpotifySoloistError(
                    "Soloist control artifact could not be inspected"
                ) from None

            if not stat.S_ISREG(info.st_mode):
                raise SpotifySoloistError(
                    "Soloist control artifact is invalid"
                )

            try:
                os.unlink(path)
            except OSError:
                raise SpotifySoloistError(
                    "Soloist control artifact could not be removed"
                ) from None

    def _spawn(self, command: list[str], environment: dict[str, str]):
        try:
            return subprocess.Popen(
                command,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
                shell=False,
            )
        except OSError:
            raise SpotifySoloistError(
                "Soloist process could not be started"
            ) from None

    @classmethod
    def _redact_command(cls, command, process) -> None:
        cls._redact_argument_list(command)
        if process is None:
            return
        try:
            retained = process.args
        except Exception:
            return
        try:
            if isinstance(retained, list):
                cls._redact_argument_list(retained)
            elif isinstance(retained, tuple):
                mutable = list(retained)
                cls._redact_argument_list(mutable)
                process.args = tuple(mutable)
        except Exception:
            pass

    @classmethod
    def _redact_argument_list(cls, command) -> None:
        try:
            index = command.index("-k")
            if index + 1 < len(command):
                command[index + 1] = cls.REDACTED_ARGUMENT
        except (AttributeError, ValueError):
            pass

    def _wait_until_ready(self) -> int:
        deadline = time.monotonic() + self._ready_timeout_seconds

        while True:
            if not self._process_alive(self._process):
                raise SpotifySoloistError(
                    "Soloist exited during startup"
                )

            port = self._read_ws_port()
            if port is not None and self._tcp_ready(port, deadline):
                if not self._process_alive(self._process):
                    raise SpotifySoloistError(
                        "Soloist exited during startup"
                    )
                return port

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SpotifySoloistError(
                    "Soloist readiness timed out"
                )
            time.sleep(min(self._poll_seconds, remaining))

    def _read_ws_port(self) -> Optional[int]:
        path = os.path.join(self._data_dir, "ws.port")
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return None
        except OSError:
            raise SpotifySoloistError(
                "Soloist readiness artifact could not be inspected"
            ) from None

        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size <= 0
            or info.st_size > self.MAX_WS_PORT_BYTES
        ):
            raise SpotifySoloistError(
                "Soloist readiness artifact is invalid"
            )

        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW

        descriptor = None
        try:
            descriptor = os.open(path, flags)
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_size <= 0
                or opened.st_size > self.MAX_WS_PORT_BYTES
            ):
                raise SpotifySoloistError(
                    "Soloist readiness artifact is invalid"
                )
            raw = os.read(descriptor, self.MAX_WS_PORT_BYTES + 1)
        except SpotifySoloistError:
            raise
        except OSError:
            raise SpotifySoloistError(
                "Soloist readiness artifact could not be read"
            ) from None
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

        if len(raw) > self.MAX_WS_PORT_BYTES:
            raise SpotifySoloistError(
                "Soloist readiness artifact is invalid"
            )
        try:
            text = raw.decode("ascii").rstrip("\r\n")
        except UnicodeDecodeError:
            raise SpotifySoloistError(
                "Soloist readiness artifact is invalid"
            ) from None
        if not text or not text.isdecimal():
            raise SpotifySoloistError(
                "Soloist readiness artifact is invalid"
            )

        port = int(text)
        if port < 1 or port > 65535:
            raise SpotifySoloistError(
                "Soloist readiness artifact is invalid"
            )
        return port

    def _tcp_ready(self, port: int, deadline: float) -> bool:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        timeout = min(self._poll_seconds, remaining)
        try:
            connection = socket.create_connection(
                ("127.0.0.1", port),
                timeout=timeout,
            )
        except OSError:
            return False
        try:
            return True
        finally:
            connection.close()

    def _stop_locked(self) -> None:
        process = self._process
        self._ready = False
        self._ws_port = None

        if self._process_alive(process):
            try:
                process.terminate()
                process.wait(timeout=self._stop_timeout_seconds)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                except OSError:
                    pass
                else:
                    try:
                        process.wait(timeout=self._stop_timeout_seconds)
                    except ProcessLookupError:
                        pass
                    except subprocess.TimeoutExpired:
                        pass
                    except OSError:
                        pass
            except ProcessLookupError:
                pass
            except OSError:
                pass

        if self._process_alive(process):
            # Retain the only handle to an unresolved live child. Its control
            # artifacts may still belong to that process and must remain.
            self._process = process
            raise SpotifySoloistError(
                "Soloist process could not be terminated"
            )

        self._process = None
        self._clear_control_artifacts()

    def _healthy_locked(self) -> bool:
        return bool(
            self._ready
            and self._ws_port is not None
            and self._process_alive(self._process)
        )

    @staticmethod
    def _process_alive(process) -> bool:
        if process is None:
            return False
        try:
            return process.poll() is None
        except Exception:
            # Unknown liveness is treated as live so the only child handle is
            # never discarded on an inspection failure.
            return True


__all__ = [
    "SpotifySoloistError",
    "SpotifySoloistSupervisor",
]
