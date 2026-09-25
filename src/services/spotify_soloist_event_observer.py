"""Passive event observer for an existing Soloist daemon."""

from __future__ import annotations

import json
import math
import os
import stat
import subprocess
import threading
import time
from typing import Any


class SpotifySoloistEventObserverError(RuntimeError):
    """The Soloist event stream could not be observed safely."""


class SpotifySoloistEventObserver:
    """Observe allowlisted state from one official trace child."""

    def __init__(
        self,
        *,
        binary_path: str,
        ready_timeout_seconds: float = 2.0,
        stop_timeout_seconds: float = 2.0,
        max_line_chars: int = 1048576,
    ) -> None:
        self._binary_path = self._absolute_path(binary_path)
        self._ready_timeout_seconds = self._positive_seconds(
            ready_timeout_seconds
        )
        self._stop_timeout_seconds = self._positive_seconds(
            stop_timeout_seconds
        )
        self._max_line_chars = self._positive_int(max_line_chars)

        self._condition = threading.Condition(threading.RLock())
        self._process = None
        self._reader_thread = None
        self._ws_port = None
        self._stopping = False
        self._reset_observation_locked()

    def start(self, *, ws_port: int) -> bool:
        port = self._valid_port(ws_port)

        with self._condition:
            if self._healthy_locked() and self._ws_port == port:
                return False

        self.stop()
        self._validate_binary()

        command = [
            self._binary_path,
            "ctl",
            "-w",
            f"127.0.0.1:{port}",
            "trace",
        ]

        with self._condition:
            self._reset_observation_locked()
            self._stopping = False

        try:
            process = self._spawn(command)
        except Exception:
            raise SpotifySoloistEventObserverError(
                "Soloist event observer could not be started"
            ) from None

        reader = threading.Thread(
            target=self._reader_main,
            args=(process,),
            name="srova-soloist-event-observer",
            daemon=True,
        )
        with self._condition:
            self._process = process
            self._reader_thread = reader
            self._ws_port = port

        try:
            reader.start()
        except Exception:
            with self._condition:
                self._fault_observation_locked()
            self._cleanup_failed_start()
            raise SpotifySoloistEventObserverError(
                "Soloist event observer could not be started"
            ) from None

        deadline = time.monotonic() + self._ready_timeout_seconds
        with self._condition:
            while True:
                if (
                    self._process is process
                    and self._ready
                    and not self._faulted
                    and self._process_alive(process)
                ):
                    return True
                if self._process is not process or self._faulted:
                    break
                if not self._process_alive(process):
                    self._fault_observation_locked()
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)

        self._cleanup_failed_start()
        raise SpotifySoloistEventObserverError(
            "Soloist event observer did not become ready"
        )

    def stop(self) -> None:
        with self._condition:
            process = self._process
            reader = self._reader_thread
            self._stopping = True
            self._ready = False
            self._condition.notify_all()

        child_stopped = self._terminate_process(process)
        if child_stopped:
            self._close_stdout(process)
        reader_stopped = self._join_reader(reader)

        with self._condition:
            if not child_stopped:
                self._process = process
                self._ws_port = None
                self._fault_observation_locked()
                self._condition.notify_all()
                raise SpotifySoloistEventObserverError(
                    "Soloist event observer could not be stopped"
                )

            if self._process is process:
                self._process = None
            if reader_stopped and self._reader_thread is reader:
                self._reader_thread = None
            self._ws_port = None
            self._stopping = False
            if not reader_stopped:
                self._fault_observation_locked()
                self._condition.notify_all()
                raise SpotifySoloistEventObserverError(
                    "Soloist event observer could not be stopped"
                )
            self._reset_observation_locked()
            self._condition.notify_all()

    def status_snapshot(self) -> dict[str, object]:
        with self._condition:
            running = self._process_alive(self._process)
            if self._process is not None and not running and not self._stopping:
                self._fault_observation_locked()
            return {
                "observer_running": running,
                "ready": self._ready,
                "faulted": self._faulted,
                "logged_in": self._logged_in,
                "is_active": self._is_active,
                "playback_status": self._playback_status,
                "device_name": self._device_name,
                "last_event_type": self._last_event_type,
                "event_sequence": self._event_sequence,
            }

    @staticmethod
    def _absolute_path(value: object) -> str:
        if not isinstance(value, str) or not value or not os.path.isabs(value):
            raise SpotifySoloistEventObserverError(
                "Soloist event observer path is invalid"
            )
        return os.path.normpath(value)

    @staticmethod
    def _positive_seconds(value: object) -> float:
        if isinstance(value, bool):
            raise SpotifySoloistEventObserverError(
                "Soloist event observer configuration is invalid"
            )
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            raise SpotifySoloistEventObserverError(
                "Soloist event observer configuration is invalid"
            ) from None
        if not math.isfinite(seconds) or seconds <= 0:
            raise SpotifySoloistEventObserverError(
                "Soloist event observer configuration is invalid"
            )
        return seconds

    @staticmethod
    def _positive_int(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise SpotifySoloistEventObserverError(
                "Soloist event observer configuration is invalid"
            )
        return value

    @staticmethod
    def _valid_port(value: object) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
            or value > 65535
        ):
            raise SpotifySoloistEventObserverError(
                "Soloist event observer port is invalid"
            )
        return value

    def _validate_binary(self) -> None:
        try:
            info = os.lstat(self._binary_path)
        except OSError:
            raise SpotifySoloistEventObserverError(
                "Soloist executable is unavailable"
            ) from None
        if (
            not stat.S_ISREG(info.st_mode)
            or not os.access(self._binary_path, os.X_OK)
        ):
            raise SpotifySoloistEventObserverError(
                "Soloist executable is invalid"
            )

    @staticmethod
    def _spawn(command: list[str]):
        try:
            return subprocess.Popen(
                command,
                env={},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                close_fds=True,
                start_new_session=True,
                shell=False,
            )
        except OSError:
            raise SpotifySoloistEventObserverError(
                "Soloist event observer could not be started"
            ) from None

    def _reader_main(self, process) -> None:
        try:
            while True:
                with self._condition:
                    if self._stopping or self._process is not process:
                        return
                try:
                    line = process.stdout.readline(self._max_line_chars + 1)
                except Exception:
                    self._reader_fault(process)
                    return
                if line == "":
                    self._reader_fault(process)
                    return
                try:
                    self._consume_line(process, line)
                except Exception:
                    self._reader_fault(process)
                    return
        finally:
            with self._condition:
                if self._reader_thread is threading.current_thread():
                    self._reader_thread = None
                self._condition.notify_all()

    def _consume_line(self, process, line: object) -> None:
        event = self._parse_line(line)
        with self._condition:
            if self._stopping or self._process is not process:
                return
            self._apply_event_locked(event)
            self._condition.notify_all()

    def _parse_line(self, line: object) -> dict[str, Any]:
        if not isinstance(line, str):
            raise SpotifySoloistEventObserverError(
                "Soloist event stream is invalid"
            )
        text = line.rstrip("\r\n")
        if not text or len(text) > self._max_line_chars:
            raise SpotifySoloistEventObserverError(
                "Soloist event stream is invalid"
            )
        timestamp, separator, encoded = text.partition(" ")
        if (
            separator != " "
            or not timestamp
            or not timestamp.isascii()
            or not timestamp.isdecimal()
            or not encoded
        ):
            raise SpotifySoloistEventObserverError(
                "Soloist event stream is invalid"
            )
        try:
            if int(timestamp) < 0:
                raise ValueError
            event = json.loads(encoded)
        except (TypeError, ValueError):
            raise SpotifySoloistEventObserverError(
                "Soloist event stream is invalid"
            ) from None
        if not isinstance(event, dict):
            raise SpotifySoloistEventObserverError(
                "Soloist event stream is invalid"
            )
        event_type = event.get("type")
        if not isinstance(event_type, str) or not event_type.strip():
            raise SpotifySoloistEventObserverError(
                "Soloist event stream is invalid"
            )
        return event

    def _apply_event_locked(self, event: dict[str, Any]) -> None:
        event_type = event["type"]
        if event_type == "auth_state":
            logged_in = self._required_bool(event, "logged_in")
            is_active = self._required_bool(event, "is_active")
            device_name = self._required_text(event, "device_name")
            self._logged_in = logged_in
            self._is_active = is_active
            self._device_name = device_name
            if not logged_in:
                self._playback_status = None
            self._ready = True
        elif event_type == "playback_state":
            self._is_active = self._required_bool(event, "is_active")
            self._playback_status = self._required_text(event, "status")
        elif event_type == "device_changed":
            self._is_active = self._required_bool(event, "is_active")
            self._device_name = self._required_text(event, "device_name")
        elif event_type == "playback_changed":
            self._playback_status = self._required_text(event, "status")

        self._last_event_type = event_type
        self._event_sequence += 1

    @staticmethod
    def _required_bool(event: dict[str, Any], key: str) -> bool:
        value = event.get(key)
        if not isinstance(value, bool):
            raise SpotifySoloistEventObserverError(
                "Soloist event stream is invalid"
            )
        return value

    @staticmethod
    def _required_text(event: dict[str, Any], key: str) -> str:
        value = event.get(key)
        if not isinstance(value, str) or not value.strip():
            raise SpotifySoloistEventObserverError(
                "Soloist event stream is invalid"
            )
        return value

    def _reader_fault(self, process) -> None:
        with self._condition:
            if not self._stopping and self._process is process:
                self._fault_observation_locked()
                self._condition.notify_all()

    def _fault_observation_locked(self) -> None:
        self._ready = False
        self._faulted = True
        self._logged_in = None
        self._is_active = None
        self._playback_status = None
        self._device_name = None

    def _reset_observation_locked(self) -> None:
        self._ready = False
        self._faulted = False
        self._logged_in = None
        self._is_active = None
        self._playback_status = None
        self._device_name = None
        self._last_event_type = None
        self._event_sequence = 0

    def _healthy_locked(self) -> bool:
        return bool(
            self._ready
            and not self._faulted
            and self._process_alive(self._process)
            and self._reader_thread is not None
            and self._reader_thread.is_alive()
        )

    def _terminate_process(self, process) -> bool:
        if not self._process_alive(process):
            return True
        try:
            process.terminate()
            process.wait(timeout=self._stop_timeout_seconds)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except (ProcessLookupError, OSError):
                pass
            else:
                try:
                    process.wait(timeout=self._stop_timeout_seconds)
                except (ProcessLookupError, subprocess.TimeoutExpired, OSError):
                    pass
        except ProcessLookupError:
            pass
        except OSError:
            pass
        return not self._process_alive(process)

    def _join_reader(self, reader) -> bool:
        if reader is None or reader is threading.current_thread():
            return True
        try:
            if reader.ident is None:
                return True
            reader.join(timeout=self._stop_timeout_seconds)
            return not reader.is_alive()
        except (RuntimeError, OSError):
            return False

    @staticmethod
    def _close_stdout(process) -> None:
        if process is None:
            return
        try:
            stream = process.stdout
            if stream is not None:
                stream.close()
        except Exception:
            pass

    def _cleanup_failed_start(self) -> None:
        try:
            self.stop()
        except SpotifySoloistEventObserverError:
            pass

    @staticmethod
    def _process_alive(process) -> bool:
        if process is None:
            return False
        try:
            return process.poll() is None
        except Exception:
            return True


__all__ = [
    "SpotifySoloistEventObserver",
    "SpotifySoloistEventObserverError",
]
