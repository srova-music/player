import inspect
import json
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from services import spotify_soloist_event_observer as observer_module  # noqa: E402
from services.spotify_soloist_event_observer import (  # noqa: E402
    SpotifySoloistEventObserver,
    SpotifySoloistEventObserverError,
)


PRIVATE_DETAIL = "synthetic-private-process-detail"
PRIVATE_PAYLOAD = "synthetic-private-event-payload"
EOF = object()


def _event(event_type, timestamp=1720000000000, **fields):
    payload = {"type": event_type, **fields}
    return f"{timestamp} {json.dumps(payload, separators=(',', ':'))}\n"


def _auth(
    *,
    logged_in=False,
    is_active=False,
    device_name="Synthetic Observer",
):
    return _event(
        "auth_state",
        logged_in=logged_in,
        is_active=is_active,
        device_name=device_name,
    )


class FakeStdout:
    def __init__(self, lines=()):
        self._condition = threading.Condition()
        self._items = deque(lines)
        self._closed = False
        self._on_eof = None
        self.read_sizes = []

    def set_eof_callback(self, callback):
        self._on_eof = callback

    def feed(self, item):
        with self._condition:
            self._items.append(item)
            self._condition.notify_all()

    def eof(self):
        self.feed(EOF)

    def readline(self, size=-1):
        with self._condition:
            self.read_sizes.append(size)
            while not self._items and not self._closed:
                self._condition.wait()
            if not self._items:
                return ""
            item = self._items.popleft()
            if item is EOF:
                if self._on_eof is not None:
                    self._on_eof()
                return ""
            if isinstance(item, BaseException):
                raise item
            if size >= 0 and len(item) > size:
                self._items.appendleft(item[size:])
                return item[:size]
            return item

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify_all()


class FakeProcess:
    def __init__(self, lines=(), *, behavior="normal"):
        self.stdout = FakeStdout(lines)
        self.stdout.set_eof_callback(self._natural_exit)
        self.behavior = behavior
        self.running = True
        self.events = []
        self.wait_calls = 0

    def _natural_exit(self):
        self.running = False

    def poll(self):
        return None if self.running else 0

    def terminate(self):
        self.events.append(("terminate",))
        if self.behavior == "terminate_oserror":
            raise OSError(PRIVATE_DETAIL)

    def kill(self):
        self.events.append(("kill",))
        if self.behavior == "kill_oserror":
            raise OSError(PRIVATE_DETAIL)
        if self.behavior == "double_timeout":
            return
        self.running = False
        self.stdout.close()

    def wait(self, timeout=None):
        self.wait_calls += 1
        self.events.append(("wait", timeout))
        if self.behavior == "double_timeout":
            raise subprocess.TimeoutExpired("trace", timeout)
        if self.behavior in {"first_timeout", "kill_oserror"} and self.wait_calls == 1:
            raise subprocess.TimeoutExpired("trace", timeout)
        self.running = False
        self.stdout.close()
        return 0


def _make_binary(path):
    path.write_bytes(b"synthetic executable")
    path.chmod(0o700)
    return path


def _observer(tmp_path, **kwargs):
    binary = _make_binary(tmp_path / "soloist")
    return SpotifySoloistEventObserver(
        binary_path=str(binary),
        ready_timeout_seconds=kwargs.pop("ready_timeout_seconds", 0.1),
        stop_timeout_seconds=kwargs.pop("stop_timeout_seconds", 0.02),
        max_line_chars=kwargs.pop("max_line_chars", 4096),
        **kwargs,
    )


def _install_process(monkeypatch, observer, process):
    commands = []

    def spawn(command):
        commands.append(list(command))
        return process

    monkeypatch.setattr(observer, "_spawn", spawn)
    return commands


def _start(monkeypatch, observer, process, *, port=43123):
    commands = _install_process(monkeypatch, observer, process)
    started = observer.start(ws_port=port)
    return started, commands


def _wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.001)
    raise AssertionError("condition did not become true")


def _initial_snapshot():
    return {
        "observer_running": False,
        "ready": False,
        "faulted": False,
        "logged_in": None,
        "is_active": None,
        "playback_status": None,
        "device_name": None,
        "last_event_type": None,
        "event_sequence": 0,
    }


def test_constructor_is_side_effect_free_and_snapshot_is_exact(tmp_path):
    binary = tmp_path / "not-created"

    observer = SpotifySoloistEventObserver(binary_path=str(binary))

    assert not binary.exists()
    assert observer.status_snapshot() == _initial_snapshot()


def test_relative_binary_is_rejected():
    with pytest.raises(SpotifySoloistEventObserverError):
        SpotifySoloistEventObserver(binary_path="relative/soloist")


def test_missing_binary_is_rejected_at_start(tmp_path):
    observer = SpotifySoloistEventObserver(
        binary_path=str(tmp_path / "missing")
    )

    with pytest.raises(SpotifySoloistEventObserverError):
        observer.start(ws_port=43123)


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_invalid_binary_object_is_rejected(tmp_path, kind):
    binary = tmp_path / "soloist"
    if kind == "directory":
        binary.mkdir()
    else:
        target = _make_binary(tmp_path / "target")
        binary.symlink_to(target)
    observer = SpotifySoloistEventObserver(binary_path=str(binary))

    with pytest.raises(SpotifySoloistEventObserverError):
        observer.start(ws_port=43123)


def test_non_executable_binary_is_rejected(tmp_path):
    binary = tmp_path / "soloist"
    binary.write_bytes(b"not executable")
    binary.chmod(0o600)
    observer = SpotifySoloistEventObserver(binary_path=str(binary))

    with pytest.raises(SpotifySoloistEventObserverError):
        observer.start(ws_port=43123)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ready_timeout_seconds", 0),
        ("ready_timeout_seconds", -1),
        ("ready_timeout_seconds", True),
        ("ready_timeout_seconds", float("nan")),
        ("ready_timeout_seconds", float("inf")),
        ("ready_timeout_seconds", "invalid"),
        ("stop_timeout_seconds", 0),
        ("stop_timeout_seconds", -1),
        ("stop_timeout_seconds", False),
        ("stop_timeout_seconds", float("nan")),
        ("stop_timeout_seconds", float("inf")),
    ],
)
def test_invalid_timeout_values_are_rejected(tmp_path, field, value):
    values = {
        "binary_path": str(tmp_path / "soloist"),
        "ready_timeout_seconds": 1,
        "stop_timeout_seconds": 1,
    }
    values[field] = value

    with pytest.raises(SpotifySoloistEventObserverError):
        SpotifySoloistEventObserver(**values)


@pytest.mark.parametrize("value", [0, -1, True, False, 1.0, "1024"])
def test_invalid_max_line_size_is_rejected(tmp_path, value):
    with pytest.raises(SpotifySoloistEventObserverError):
        SpotifySoloistEventObserver(
            binary_path=str(tmp_path / "soloist"),
            max_line_chars=value,
        )


@pytest.mark.parametrize("port", [1, 65535])
def test_boundary_ports_are_accepted(tmp_path, monkeypatch, port):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth()])

    assert _start(monkeypatch, observer, process, port=port)[0] is True
    assert observer.status_snapshot()["ready"] is True
    observer.stop()


@pytest.mark.parametrize("port", [0, 65536, -1, "43123", True, False, 1.0])
def test_invalid_ports_are_rejected_before_spawn(tmp_path, monkeypatch, port):
    observer = _observer(tmp_path)
    calls = []
    monkeypatch.setattr(observer, "_spawn", lambda *_args: calls.append(True))

    with pytest.raises(SpotifySoloistEventObserverError):
        observer.start(ws_port=port)

    assert calls == []


def test_exact_command_and_popen_contract(tmp_path, monkeypatch):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth()])
    captured = {}

    def popen(command, **kwargs):
        captured["command"] = list(command)
        captured["kwargs"] = kwargs
        return process

    monkeypatch.setattr(observer_module.subprocess, "Popen", popen)

    assert observer.start(ws_port=43123) is True
    assert captured["command"] == [
        str(tmp_path / "soloist"),
        "ctl",
        "-w",
        "127.0.0.1:43123",
        "trace",
    ]
    assert captured["kwargs"] == {
        "env": {},
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,
        "text": True,
        "close_fds": True,
        "start_new_session": True,
        "shell": False,
    }
    assert "-D" not in captured["command"]
    assert "-k" not in captured["command"]
    assert "api_key" not in inspect.signature(observer.start).parameters
    observer.stop()


def test_real_observed_auth_state_establishes_readiness(tmp_path, monkeypatch):
    observer = _observer(tmp_path)
    line = (
        '1720000000000 {"type":"auth_state","logged_in":false,'
        '"is_active":false,"device_name":"SROVA SP2C8A Observer Audit"}\n'
    )
    process = FakeProcess([line])

    assert _start(monkeypatch, observer, process)[0] is True
    assert observer.status_snapshot() == {
        "observer_running": True,
        "ready": True,
        "faulted": False,
        "logged_in": False,
        "is_active": False,
        "playback_status": None,
        "device_name": "SROVA SP2C8A Observer Audit",
        "last_event_type": "auth_state",
        "event_sequence": 1,
    }
    observer.stop()


def test_second_healthy_start_is_idempotent_without_duplicate_reader(
    tmp_path,
    monkeypatch,
):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth()])
    started, commands = _start(monkeypatch, observer, process)
    reader = observer._reader_thread

    assert started is True
    assert observer.start(ws_port=43123) is False
    assert commands == [[
        str(tmp_path / "soloist"),
        "ctl",
        "-w",
        "127.0.0.1:43123",
        "trace",
    ]]
    assert observer._reader_thread is reader
    observer.stop()


def test_trace_exit_before_auth_state_fails_and_cleans(tmp_path, monkeypatch):
    observer = _observer(tmp_path)
    process = FakeProcess([EOF])
    _install_process(monkeypatch, observer, process)

    with pytest.raises(SpotifySoloistEventObserverError):
        observer.start(ws_port=43123)

    assert observer.status_snapshot() == _initial_snapshot()


def test_timeout_before_auth_state_fails_and_cleans(tmp_path, monkeypatch):
    observer = _observer(tmp_path, ready_timeout_seconds=0.01)
    process = FakeProcess()
    _install_process(monkeypatch, observer, process)

    with pytest.raises(SpotifySoloistEventObserverError):
        observer.start(ws_port=43123)

    assert process.events[0][0] == "terminate"
    assert observer.status_snapshot() == _initial_snapshot()


def test_malformed_first_line_fails_without_echo(tmp_path, monkeypatch):
    observer = _observer(tmp_path)
    process = FakeProcess([f"bad {PRIVATE_PAYLOAD}\n"])
    _install_process(monkeypatch, observer, process)

    with pytest.raises(SpotifySoloistEventObserverError) as raised:
        observer.start(ws_port=43123)

    assert PRIVATE_PAYLOAD not in str(raised.value)
    assert observer.status_snapshot() == _initial_snapshot()


def test_unknown_event_before_auth_is_recorded_but_not_ready_until_auth(
    tmp_path,
    monkeypatch,
):
    observer = _observer(tmp_path)
    process = FakeProcess([
        _event("future_event", ignored=True),
        _auth(),
    ])

    assert _start(monkeypatch, observer, process)[0] is True
    snapshot = observer.status_snapshot()
    assert snapshot["ready"] is True
    assert snapshot["event_sequence"] == 2
    assert snapshot["last_event_type"] == "auth_state"
    observer.stop()


@pytest.mark.parametrize(
    "fields",
    [
        {"is_active": False, "device_name": "Device"},
        {"logged_in": "false", "is_active": False, "device_name": "Device"},
        {"logged_in": False, "device_name": "Device"},
        {"logged_in": False, "is_active": 0, "device_name": "Device"},
        {"logged_in": False, "is_active": False},
        {"logged_in": False, "is_active": False, "device_name": ""},
        {"logged_in": False, "is_active": False, "device_name": "   "},
        {"logged_in": False, "is_active": False, "device_name": 123},
    ],
)
def test_malformed_auth_state_faults_after_readiness(
    tmp_path,
    monkeypatch,
    fields,
):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth(logged_in=True)])
    _start(monkeypatch, observer, process)

    process.stdout.feed(_event("auth_state", **fields))
    _wait_for(lambda: observer.status_snapshot()["faulted"])
    snapshot = observer.status_snapshot()
    assert snapshot["ready"] is False
    assert snapshot["logged_in"] is None
    assert snapshot["is_active"] is None
    observer.stop()


def test_logged_out_auth_state_clears_previous_playback_status(
    tmp_path,
    monkeypatch,
):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth(logged_in=True, is_active=True)])
    _start(monkeypatch, observer, process)
    process.stdout.feed(_event("playback_changed", status="playing"))
    _wait_for(lambda: observer.status_snapshot()["event_sequence"] == 2)
    process.stdout.feed(_auth(logged_in=False, is_active=False))
    _wait_for(lambda: observer.status_snapshot()["event_sequence"] == 3)

    snapshot = observer.status_snapshot()
    assert snapshot["logged_in"] is False
    assert snapshot["is_active"] is False
    assert snapshot["playback_status"] is None
    observer.stop()


def test_valid_playback_state_updates_allowlisted_fields(tmp_path, monkeypatch):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth()])
    _start(monkeypatch, observer, process)
    process.stdout.feed(
        _event(
            "playback_state",
            is_active=True,
            status="playing",
            uri=PRIVATE_PAYLOAD,
            queue=[PRIVATE_PAYLOAD],
        )
    )
    _wait_for(lambda: observer.status_snapshot()["event_sequence"] == 2)

    snapshot = observer.status_snapshot()
    assert snapshot["is_active"] is True
    assert snapshot["playback_status"] == "playing"
    assert snapshot["last_event_type"] == "playback_state"
    assert PRIVATE_PAYLOAD not in repr(observer.__dict__)
    observer.stop()


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "playing"},
        {"is_active": "yes", "status": "playing"},
        {"is_active": True},
        {"is_active": True, "status": ""},
        {"is_active": True, "status": "   "},
        {"is_active": True, "status": 1},
    ],
)
def test_malformed_playback_state_faults(tmp_path, monkeypatch, fields):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth()])
    _start(monkeypatch, observer, process)

    process.stdout.feed(_event("playback_state", **fields))
    _wait_for(lambda: observer.status_snapshot()["faulted"])
    assert observer.status_snapshot()["is_active"] is None
    observer.stop()


def test_valid_device_changed_updates_allowlisted_fields(tmp_path, monkeypatch):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth()])
    _start(monkeypatch, observer, process)
    process.stdout.feed(
        _event("device_changed", is_active=True, device_name="New Device")
    )
    _wait_for(lambda: observer.status_snapshot()["event_sequence"] == 2)

    snapshot = observer.status_snapshot()
    assert snapshot["is_active"] is True
    assert snapshot["device_name"] == "New Device"
    observer.stop()


@pytest.mark.parametrize(
    "fields",
    [
        {"device_name": "Device"},
        {"is_active": "false", "device_name": "Device"},
        {"is_active": False},
        {"is_active": False, "device_name": ""},
        {"is_active": False, "device_name": 2},
    ],
)
def test_malformed_device_changed_faults(tmp_path, monkeypatch, fields):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth()])
    _start(monkeypatch, observer, process)

    process.stdout.feed(_event("device_changed", **fields))
    _wait_for(lambda: observer.status_snapshot()["faulted"])
    assert observer.status_snapshot()["device_name"] is None
    observer.stop()


def test_valid_playback_changed_updates_status(tmp_path, monkeypatch):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth()])
    _start(monkeypatch, observer, process)
    process.stdout.feed(_event("playback_changed", status="paused"))
    _wait_for(lambda: observer.status_snapshot()["event_sequence"] == 2)

    assert observer.status_snapshot()["playback_status"] == "paused"
    observer.stop()


@pytest.mark.parametrize("fields", [{}, {"status": ""}, {"status": "   "}, {"status": 1}])
def test_malformed_playback_changed_faults(tmp_path, monkeypatch, fields):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth()])
    _start(monkeypatch, observer, process)

    process.stdout.feed(_event("playback_changed", **fields))
    _wait_for(lambda: observer.status_snapshot()["faulted"])
    assert observer.status_snapshot()["playback_status"] is None
    observer.stop()


@pytest.mark.parametrize(
    "event_type",
    [
        "track_changed",
        "position_sync",
        "volume_changed",
        "context_changed",
        "options_changed",
        "queue_changed",
        "command_result",
        "error",
        "future_unknown_type",
    ],
)
def test_unknown_events_only_update_sequence_and_type(
    tmp_path,
    monkeypatch,
    event_type,
):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth()])
    _start(monkeypatch, observer, process)
    before = observer.status_snapshot()
    process.stdout.feed(
        _event(
            event_type,
            uri=PRIVATE_PAYLOAD,
            queue=[PRIVATE_PAYLOAD],
            metadata={"private": PRIVATE_PAYLOAD},
        )
    )
    _wait_for(lambda: observer.status_snapshot()["event_sequence"] == 2)

    after = observer.status_snapshot()
    assert after["last_event_type"] == event_type
    assert after["event_sequence"] == 2
    for key in (
        "logged_in",
        "is_active",
        "playback_status",
        "device_name",
    ):
        assert after[key] == before[key]
    assert PRIVATE_PAYLOAD not in repr(observer.__dict__)
    observer.stop()


@pytest.mark.parametrize("timestamp", ["0", "1720000000000"])
def test_parser_accepts_decimal_timestamps(tmp_path, timestamp):
    observer = _observer(tmp_path)

    parsed = observer._parse_line(
        f'{timestamp} {{"type":"future_event"}}\r\n'
    )

    assert parsed == {"type": "future_event"}


@pytest.mark.parametrize(
    "line",
    [
        "",
        "\n",
        '-1 {"type":"event"}\n',
        '1.5 {"type":"event"}\n',
        'abc {"type":"event"}\n',
        '١ {"type":"event"}\n',
        '1{"type":"event"}\n',
        "1 \n",
        "1 not-json\n",
        "1 []\n",
        "1 {}\n",
        '1 {"type":""}\n',
        '1 {"type":"   "}\n',
        '1 {"type":2}\n',
    ],
)
def test_parser_rejects_malformed_lines(tmp_path, line):
    observer = _observer(tmp_path)

    with pytest.raises(SpotifySoloistEventObserverError):
        observer._parse_line(line)


def test_oversized_line_faults_and_read_is_bounded(tmp_path, monkeypatch):
    observer = _observer(tmp_path, max_line_chars=32)
    process = FakeProcess(["1 " + "x" * 40 + "\n"])
    _install_process(monkeypatch, observer, process)

    with pytest.raises(SpotifySoloistEventObserverError):
        observer.start(ws_port=43123)

    assert process.stdout.read_sizes[0] == 33


def test_sequence_increments_once_per_accepted_event(tmp_path, monkeypatch):
    observer = _observer(tmp_path)
    process = FakeProcess([_event("future"), _auth()])
    _start(monkeypatch, observer, process)
    process.stdout.feed(_event("playback_changed", status="stopped"))
    process.stdout.feed(_event("another_future"))
    _wait_for(lambda: observer.status_snapshot()["event_sequence"] == 4)

    assert observer.status_snapshot()["event_sequence"] == 4
    observer.stop()


def test_snapshot_is_a_copy(tmp_path, monkeypatch):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth()])
    _start(monkeypatch, observer, process)
    snapshot = observer.status_snapshot()
    snapshot["is_active"] = "mutated"
    snapshot["event_sequence"] = 999

    current = observer.status_snapshot()
    assert current["is_active"] is False
    assert current["event_sequence"] == 1
    observer.stop()


def test_unexpected_death_clears_inactive_state_and_faults_closed(
    tmp_path,
    monkeypatch,
):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth(logged_in=True, is_active=False)])
    _start(monkeypatch, observer, process)
    assert observer.status_snapshot()["is_active"] is False

    process.stdout.eof()
    _wait_for(lambda: observer.status_snapshot()["faulted"])
    snapshot = observer.status_snapshot()
    assert snapshot["observer_running"] is False
    assert snapshot["ready"] is False
    assert snapshot["faulted"] is True
    assert snapshot["logged_in"] is None
    assert snapshot["is_active"] is None
    assert snapshot["playback_status"] is None
    assert snapshot["device_name"] is None
    observer.stop()


def test_graceful_stop_resets_state_without_fault(tmp_path, monkeypatch):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth(logged_in=True, is_active=True)])
    _start(monkeypatch, observer, process)

    observer.stop()

    assert process.events == [
        ("terminate",),
        ("wait", observer._stop_timeout_seconds),
    ]
    assert observer.status_snapshot() == _initial_snapshot()


def test_stop_uses_kill_after_first_wait_timeout(tmp_path, monkeypatch):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth()], behavior="first_timeout")
    _start(monkeypatch, observer, process)

    observer.stop()

    assert process.events == [
        ("terminate",),
        ("wait", observer._stop_timeout_seconds),
        ("kill",),
        ("wait", observer._stop_timeout_seconds),
    ]
    assert observer.status_snapshot() == _initial_snapshot()


def test_double_timeout_retains_exact_child_handle(tmp_path, monkeypatch):
    observer = _observer(tmp_path, stop_timeout_seconds=0.005)
    process = FakeProcess([_auth()], behavior="double_timeout")
    _start(monkeypatch, observer, process)

    with pytest.raises(SpotifySoloistEventObserverError):
        observer.stop()

    assert observer._process is process
    snapshot = observer.status_snapshot()
    assert snapshot["observer_running"] is True
    assert snapshot["ready"] is False
    assert snapshot["faulted"] is True
    assert snapshot["is_active"] is None
    process.stdout.feed(_auth(logged_in=True, is_active=True))
    time.sleep(0.01)
    assert observer.status_snapshot()["is_active"] is None
    process.behavior = "normal"
    observer.stop()


def test_kill_oserror_retains_exact_child_handle(tmp_path, monkeypatch):
    observer = _observer(tmp_path, stop_timeout_seconds=0.005)
    process = FakeProcess([_auth()], behavior="kill_oserror")
    _start(monkeypatch, observer, process)

    with pytest.raises(SpotifySoloistEventObserverError) as raised:
        observer.stop()

    assert PRIVATE_DETAIL not in str(raised.value)
    assert observer._process is process
    process.behavior = "normal"
    observer.stop()


def test_terminate_oserror_retains_exact_child_handle(tmp_path, monkeypatch):
    observer = _observer(tmp_path, stop_timeout_seconds=0.005)
    process = FakeProcess([_auth()], behavior="terminate_oserror")
    _start(monkeypatch, observer, process)

    with pytest.raises(SpotifySoloistEventObserverError) as raised:
        observer.stop()

    assert PRIVATE_DETAIL not in str(raised.value)
    assert observer._process is process
    process.behavior = "normal"
    observer.stop()


def test_later_stop_retries_same_retained_process(tmp_path, monkeypatch):
    observer = _observer(tmp_path, stop_timeout_seconds=0.005)
    process = FakeProcess([_auth()], behavior="terminate_oserror")
    _start(monkeypatch, observer, process)

    with pytest.raises(SpotifySoloistEventObserverError):
        observer.stop()
    process.behavior = "normal"
    observer.stop()

    assert process.events == [
        ("terminate",),
        ("terminate",),
        ("wait", observer._stop_timeout_seconds),
    ]
    assert observer._process is None
    assert observer.status_snapshot() == _initial_snapshot()


def test_start_cannot_stack_over_unresolved_child(tmp_path, monkeypatch):
    observer = _observer(tmp_path, stop_timeout_seconds=0.005)
    process = FakeProcess([_auth()], behavior="terminate_oserror")
    _start(monkeypatch, observer, process)
    with pytest.raises(SpotifySoloistEventObserverError):
        observer.stop()
    spawn_calls = []
    monkeypatch.setattr(observer, "_spawn", lambda *_args: spawn_calls.append(True))

    with pytest.raises(SpotifySoloistEventObserverError):
        observer.start(ws_port=43124)

    assert spawn_calls == []
    assert observer._process is process
    process.behavior = "normal"
    observer.stop()


def test_stdout_read_error_after_readiness_faults(tmp_path, monkeypatch):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth()])
    _start(monkeypatch, observer, process)
    process.stdout.feed(OSError(PRIVATE_DETAIL))

    _wait_for(lambda: observer.status_snapshot()["faulted"])
    assert observer.status_snapshot()["is_active"] is None
    observer.stop()


def test_reader_thread_exits_after_explicit_stop(tmp_path, monkeypatch):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth()])
    _start(monkeypatch, observer, process)
    reader = observer._reader_thread

    observer.stop()

    assert not reader.is_alive()
    assert observer._reader_thread is None
    assert observer.status_snapshot()["faulted"] is False


def test_spawn_error_is_generic_and_contains_no_private_detail(
    tmp_path,
    monkeypatch,
):
    observer = _observer(tmp_path)

    def fail(_command):
        raise OSError(PRIVATE_DETAIL)

    monkeypatch.setattr(observer, "_spawn", fail)

    with pytest.raises(SpotifySoloistEventObserverError) as raised:
        observer.start(ws_port=43123)

    assert PRIVATE_DETAIL not in str(raised.value)


def test_public_snapshot_contains_no_process_details(tmp_path, monkeypatch):
    observer = _observer(tmp_path)
    process = FakeProcess([_auth()])
    _start(monkeypatch, observer, process)

    snapshot_text = repr(observer.status_snapshot()).lower()
    for forbidden in ("pid", "argv", "command", "environment", "43123"):
        assert forbidden not in snapshot_text
    observer.stop()


def test_component_has_no_forbidden_architecture_references():
    source = Path(observer_module.__file__).read_text(encoding="utf-8").lower()
    forbidden = (
        "spotifycoordinator",
        "spotify_runtime_supervisor",
        "spotifysoloistsupervisor",
        "spotify_soloist_supervisor",
        "spotifypipewiredacresolver",
        "spotify_pipewire_dac_resolver",
        "spotifysecretstore",
        "main_headless",
        "audioplayer",
        "native audio",
        "alsa",
        "pipewire",
        "websocket",
        "aiohttp",
        "firewall",
        "ufw",
        "tailscale",
        "http",
        "systemctl",
        "sudo",
        "package",
        "install",
        "download",
        "api_key",
    )
    assert not any(token in source for token in forbidden)
