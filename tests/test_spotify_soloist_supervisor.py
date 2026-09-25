import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from services import spotify_soloist_supervisor as soloist_module  # noqa: E402
from services.spotify_soloist_supervisor import (  # noqa: E402
    SpotifySoloistError,
    SpotifySoloistSupervisor,
)


SYNTHETIC_KEY = "synthetic-test-key-not-a-real-secret"


class FakeProcess:
    def __init__(
        self,
        args,
        events=None,
        *,
        running=True,
        first_wait_times_out=False,
        terminate_lookup_error=False,
    ):
        self.args = list(args)
        self.events = events if events is not None else []
        self.running = bool(running)
        self.first_wait_times_out = bool(first_wait_times_out)
        self.terminate_lookup_error = bool(terminate_lookup_error)
        self.wait_calls = 0

    def poll(self):
        return None if self.running else 1

    def terminate(self):
        self.events.append(("terminate",))
        if self.terminate_lookup_error:
            self.running = False
            raise ProcessLookupError()

    def kill(self):
        self.events.append(("kill",))
        self.running = False

    def wait(self, timeout=None):
        self.wait_calls += 1
        self.events.append(("wait", timeout))
        if self.first_wait_times_out and self.wait_calls == 1:
            raise subprocess.TimeoutExpired("soloist", timeout)
        self.running = False
        return 0


def _make_binary(path):
    path.write_bytes(b"synthetic executable")
    path.chmod(0o700)
    return path


def _supervisor(tmp_path, **kwargs):
    binary = _make_binary(tmp_path / "soloist")
    return SpotifySoloistSupervisor(
        binary_path=str(binary),
        data_dir=str(tmp_path / "data"),
        cache_dir=str(tmp_path / "cache"),
        ready_timeout_seconds=kwargs.pop("ready_timeout_seconds", 0.05),
        stop_timeout_seconds=kwargs.pop("stop_timeout_seconds", 0.02),
        poll_seconds=kwargs.pop("poll_seconds", 0.001),
        **kwargs,
    )


def _install_successful_spawn(
    monkeypatch,
    supervisor,
    *,
    port=43123,
    environment=None,
):
    launches = []

    def spawn(command, child_environment):
        launches.append((list(command), dict(child_environment)))
        Path(supervisor.data_dir, "ws.port").write_text(
            f"{port}\n",
            encoding="ascii",
        )
        return FakeProcess(command)

    monkeypatch.setattr(supervisor, "_spawn", spawn)
    monkeypatch.setattr(supervisor, "_tcp_ready", lambda *_args: True)
    started = supervisor.start(
        api_key=SYNTHETIC_KEY,
        device_name="SROVA Test Device",
        pipewire_node_name="alsa_output.synthetic",
        environment=environment or {"ONLY": "caller"},
    )
    return started, launches, supervisor._process


def _create_control_artifacts(supervisor):
    supervisor._prepare_directory(supervisor.data_dir)
    data = Path(supervisor.data_dir)
    for name in supervisor.CONTROL_ARTIFACTS:
        (data / name).write_text("live", encoding="ascii")
    return data


def _assert_live_child_retained(supervisor, process, data):
    assert supervisor._process is process
    assert supervisor._ready is False
    assert supervisor._ws_port is None
    assert supervisor.status_snapshot() == {
        "soloist_running": True,
        "ready": False,
        "ws_port": None,
    }
    assert all(
        (data / name).read_text(encoding="ascii") == "live"
        for name in supervisor.CONTROL_ARTIFACTS
    )


def test_constructor_is_side_effect_free(tmp_path):
    binary = tmp_path / "not-created-by-constructor"
    data = tmp_path / "data"
    cache = tmp_path / "cache"

    supervisor = SpotifySoloistSupervisor(
        binary_path=str(binary),
        data_dir=str(data),
        cache_dir=str(cache),
    )

    assert supervisor.data_dir == str(data)
    assert supervisor.cache_dir == str(cache)
    assert not binary.exists()
    assert not data.exists()
    assert not cache.exists()
    assert supervisor.status_snapshot() == {
        "soloist_running": False,
        "ready": False,
        "ws_port": None,
    }


@pytest.mark.parametrize(
    ("pid", "running", "expected"),
    [(4321, True, 4321), (4321, False, None), (True, True, None), (0, True, None)],
)
def test_process_id_returns_only_positive_live_integer(
    tmp_path,
    pid,
    running,
    expected,
):
    supervisor = _supervisor(tmp_path)
    process = FakeProcess([], running=running)
    process.pid = pid
    supervisor._process = process

    assert supervisor.process_id == expected
    assert set(supervisor.status_snapshot()) == {
        "soloist_running",
        "ready",
        "ws_port",
    }


def test_process_id_inspection_exception_fails_safely(tmp_path):
    supervisor = _supervisor(tmp_path)

    class BrokenProcess:
        @property
        def pid(self):
            raise RuntimeError("private pid detail")

        def poll(self):
            raise RuntimeError("private poll detail")

    supervisor._process = BrokenProcess()

    assert supervisor.process_id is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("binary_path", "relative/soloist"),
        ("data_dir", "relative/data"),
        ("cache_dir", "relative/cache"),
    ],
)
def test_relative_paths_are_rejected(tmp_path, field, value):
    values = {
        "binary_path": str(tmp_path / "soloist"),
        "data_dir": str(tmp_path / "data"),
        "cache_dir": str(tmp_path / "cache"),
    }
    values[field] = value
    with pytest.raises(SpotifySoloistError):
        SpotifySoloistSupervisor(**values)


def test_data_and_cache_must_be_distinct(tmp_path):
    shared = tmp_path / "shared"
    with pytest.raises(SpotifySoloistError):
        SpotifySoloistSupervisor(
            binary_path=str(tmp_path / "soloist"),
            data_dir=str(shared),
            cache_dir=str(shared),
        )


def test_private_directories_are_created_mode_0700(tmp_path):
    supervisor = _supervisor(tmp_path)

    supervisor._prepare_directory(supervisor.data_dir)
    supervisor._prepare_directory(supervisor.cache_dir)

    assert stat.S_IMODE(Path(supervisor.data_dir).stat().st_mode) == 0o700
    assert stat.S_IMODE(Path(supervisor.cache_dir).stat().st_mode) == 0o700


def test_existing_private_directories_are_resecured(tmp_path):
    supervisor = _supervisor(tmp_path)
    Path(supervisor.data_dir).mkdir(mode=0o755)
    Path(supervisor.cache_dir).mkdir(mode=0o777)
    os.chmod(supervisor.data_dir, 0o755)
    os.chmod(supervisor.cache_dir, 0o777)

    supervisor._prepare_directory(supervisor.data_dir)
    supervisor._prepare_directory(supervisor.cache_dir)

    assert stat.S_IMODE(Path(supervisor.data_dir).stat().st_mode) == 0o700
    assert stat.S_IMODE(Path(supervisor.cache_dir).stat().st_mode) == 0o700


@pytest.mark.parametrize("directory_name", ["data", "cache"])
def test_symlink_private_directory_is_rejected(tmp_path, directory_name):
    supervisor = _supervisor(tmp_path)
    real = tmp_path / f"real-{directory_name}"
    real.mkdir()
    Path(getattr(supervisor, f"{directory_name}_dir")).symlink_to(
        real,
        target_is_directory=True,
    )

    with pytest.raises(SpotifySoloistError):
        supervisor._prepare_directory(
            getattr(supervisor, f"{directory_name}_dir")
        )


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_invalid_binary_object_is_rejected(tmp_path, kind):
    binary = tmp_path / "soloist"
    if kind == "directory":
        binary.mkdir()
    else:
        target = tmp_path / "target"
        _make_binary(target)
        binary.symlink_to(target)
    supervisor = SpotifySoloistSupervisor(
        binary_path=str(binary),
        data_dir=str(tmp_path / "data"),
        cache_dir=str(tmp_path / "cache"),
    )

    with pytest.raises(SpotifySoloistError):
        supervisor._validate_binary()


def test_non_executable_binary_is_rejected(tmp_path):
    binary = tmp_path / "soloist"
    binary.write_bytes(b"not executable")
    binary.chmod(0o600)
    supervisor = SpotifySoloistSupervisor(
        binary_path=str(binary),
        data_dir=str(tmp_path / "data"),
        cache_dir=str(tmp_path / "cache"),
    )

    with pytest.raises(SpotifySoloistError):
        supervisor._validate_binary()


def test_stale_control_files_are_removed_and_persistent_data_survives(tmp_path):
    supervisor = _supervisor(tmp_path)
    supervisor._prepare_directory(supervisor.data_dir)
    data = Path(supervisor.data_dir)
    for name in supervisor.CONTROL_ARTIFACTS:
        (data / name).write_text("stale", encoding="utf-8")
    persistent_file = data / ".device_id"
    persistent_dir = data / "settings"
    persistent_file.write_text("keep", encoding="utf-8")
    persistent_dir.mkdir()

    supervisor._clear_control_artifacts()

    assert all(not (data / name).exists() for name in supervisor.CONTROL_ARTIFACTS)
    assert persistent_file.read_text(encoding="utf-8") == "keep"
    assert persistent_dir.is_dir()


@pytest.mark.parametrize("kind", ["symlink", "directory"])
def test_unexpected_control_artifact_is_rejected(tmp_path, kind):
    supervisor = _supervisor(tmp_path)
    supervisor._prepare_directory(supervisor.data_dir)
    artifact = Path(supervisor.data_dir) / "ws.port"
    if kind == "symlink":
        target = Path(supervisor.data_dir) / "target"
        target.write_text("1234", encoding="ascii")
        artifact.symlink_to(target)
    else:
        artifact.mkdir()

    with pytest.raises(SpotifySoloistError):
        supervisor._clear_control_artifacts()


def test_exact_command_environment_and_popen_contract(tmp_path, monkeypatch):
    supervisor = _supervisor(tmp_path)
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command_at_launch"] = list(command)
        captured["command_object"] = command
        captured["kwargs"] = kwargs
        Path(supervisor.data_dir, "ws.port").write_text("43123\n", encoding="ascii")
        return FakeProcess(command)

    monkeypatch.setattr(soloist_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(supervisor, "_tcp_ready", lambda *_args: True)
    caller_environment = {"ONLY": "caller", "PIPEWIRE_REMOTE": "private"}

    assert supervisor.start(
        api_key=SYNTHETIC_KEY,
        device_name="Living Room",
        pipewire_node_name="alsa_output.usb-test",
        environment=caller_environment,
    ) is True

    assert captured["command_at_launch"] == [
        str(tmp_path / "soloist"),
        "-n",
        "Living Room",
        "-D",
        str(tmp_path / "data"),
        "-C",
        str(tmp_path / "cache"),
        "-d",
        "alsa_output.usb-test",
        "-w",
        "127.0.0.1:0",
        "-k",
        SYNTHETIC_KEY,
    ]
    assert captured["kwargs"] == {
        "env": caller_environment,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "start_new_session": True,
        "shell": False,
    }
    assert captured["kwargs"]["env"] is not caller_environment
    assert captured["command_object"][-1] == "<redacted>"
    assert supervisor._process.args[-1] == "<redacted>"
    forbidden = {"--pair", "--single-track", "--initial-volume", "--cache-size"}
    assert forbidden.isdisjoint(captured["command_at_launch"])


def test_secret_is_not_retained_or_exposed(tmp_path, monkeypatch):
    supervisor = _supervisor(tmp_path)
    _started, launches, process = _install_successful_spawn(
        monkeypatch,
        supervisor,
    )

    assert SYNTHETIC_KEY in launches[0][0]
    assert SYNTHETIC_KEY not in repr(supervisor.__dict__)
    assert SYNTHETIC_KEY not in repr(supervisor.status_snapshot())
    assert SYNTHETIC_KEY not in repr(process.args)


def test_secret_is_absent_from_public_start_error(tmp_path, monkeypatch):
    supervisor = _supervisor(tmp_path)

    def fail_spawn(*_args):
        raise RuntimeError(f"launch failed with {SYNTHETIC_KEY}")

    monkeypatch.setattr(supervisor, "_spawn", fail_spawn)

    with pytest.raises(SpotifySoloistError) as raised:
        supervisor.start(
            api_key=SYNTHETIC_KEY,
            device_name="Device",
            pipewire_node_name="node",
            environment={},
        )

    assert SYNTHETIC_KEY not in str(raised.value)
    assert SYNTHETIC_KEY not in repr(supervisor.__dict__)


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"\xff",
        b"abcd",
        b"-1",
        b"0",
        b"65536",
        b"1234 ",
    ],
)
def test_invalid_ws_port_content_is_rejected(tmp_path, content):
    supervisor = _supervisor(tmp_path)
    supervisor._prepare_directory(supervisor.data_dir)
    Path(supervisor.data_dir, "ws.port").write_bytes(content)

    with pytest.raises(SpotifySoloistError):
        supervisor._read_ws_port()


def test_valid_ws_port_is_parsed(tmp_path):
    supervisor = _supervisor(tmp_path)
    supervisor._prepare_directory(supervisor.data_dir)
    Path(supervisor.data_dir, "ws.port").write_bytes(b"43123\r\n")

    assert supervisor._read_ws_port() == 43123


def test_oversized_ws_port_is_rejected(tmp_path):
    supervisor = _supervisor(tmp_path)
    supervisor._prepare_directory(supervisor.data_dir)
    Path(supervisor.data_dir, "ws.port").write_bytes(
        b"1" * (supervisor.MAX_WS_PORT_BYTES + 1)
    )

    with pytest.raises(SpotifySoloistError):
        supervisor._read_ws_port()


@pytest.mark.parametrize("kind", ["symlink", "directory"])
def test_non_regular_ws_port_is_rejected(tmp_path, kind):
    supervisor = _supervisor(tmp_path)
    supervisor._prepare_directory(supervisor.data_dir)
    port_path = Path(supervisor.data_dir, "ws.port")
    if kind == "symlink":
        target = Path(supervisor.data_dir, "port-target")
        target.write_text("43123", encoding="ascii")
        port_path.symlink_to(target)
    else:
        port_path.mkdir()

    with pytest.raises(SpotifySoloistError):
        supervisor._read_ws_port()


def test_start_waits_for_fresh_ws_port(tmp_path, monkeypatch):
    supervisor = _supervisor(tmp_path)
    supervisor._prepare_directory(supervisor.data_dir)
    stale = Path(supervisor.data_dir, "ws.port")
    stale.write_text("1111", encoding="ascii")
    process = FakeProcess([])
    spawn_observations = []

    def spawn(command, _environment):
        spawn_observations.append(stale.exists())
        process.args = list(command)
        return process

    sleep_calls = []

    def sleep(_seconds):
        sleep_calls.append(True)
        stale.write_text("43123\n", encoding="ascii")

    monkeypatch.setattr(supervisor, "_spawn", spawn)
    monkeypatch.setattr(supervisor, "_tcp_ready", lambda *_args: True)
    monkeypatch.setattr(soloist_module.time, "sleep", sleep)

    assert supervisor.start(
        api_key=SYNTHETIC_KEY,
        device_name="Device",
        pipewire_node_name="node",
        environment={},
    ) is True
    assert spawn_observations == [False]
    assert sleep_calls
    assert supervisor.ws_port == 43123


def test_successful_loopback_readiness_uses_validated_port(tmp_path, monkeypatch):
    supervisor = _supervisor(tmp_path)
    connections = []

    class Connection:
        def close(self):
            connections.append("closed")

    def create_connection(address, timeout):
        connections.append((address, timeout))
        return Connection()

    monkeypatch.setattr(soloist_module.socket, "create_connection", create_connection)

    def spawn(command, _environment):
        Path(supervisor.data_dir, "ws.port").write_text(
            "43124",
            encoding="ascii",
        )
        return FakeProcess(command)

    monkeypatch.setattr(supervisor, "_spawn", spawn)

    assert supervisor.start(
        api_key=SYNTHETIC_KEY,
        device_name="Device",
        pipewire_node_name="node",
        environment={},
    ) is True
    assert connections[0][0] == ("127.0.0.1", 43124)
    assert "closed" in connections


def test_process_death_before_ws_port_fails_and_cleans(tmp_path, monkeypatch):
    supervisor = _supervisor(tmp_path)
    process = FakeProcess([], running=False)
    monkeypatch.setattr(supervisor, "_spawn", lambda command, _env: process)

    with pytest.raises(SpotifySoloistError):
        supervisor.start(
            api_key=SYNTHETIC_KEY,
            device_name="Device",
            pipewire_node_name="node",
            environment={},
        )

    assert supervisor.status_snapshot()["ready"] is False


def test_process_death_after_port_before_ready_fails(tmp_path, monkeypatch):
    supervisor = _supervisor(tmp_path)
    process = FakeProcess([])

    def spawn(command, _environment):
        process.args = list(command)
        Path(supervisor.data_dir, "ws.port").write_text("43123", encoding="ascii")
        return process

    def connect_then_die(*_args):
        process.running = False
        return True

    monkeypatch.setattr(supervisor, "_spawn", spawn)
    monkeypatch.setattr(supervisor, "_tcp_ready", connect_then_die)

    with pytest.raises(SpotifySoloistError):
        supervisor.start(
            api_key=SYNTHETIC_KEY,
            device_name="Device",
            pipewire_node_name="node",
            environment={},
        )


def test_connection_refusal_retries_then_timeout_cleans_child(tmp_path, monkeypatch):
    supervisor = _supervisor(tmp_path, ready_timeout_seconds=0.01)
    process = FakeProcess([])
    attempts = []

    def spawn(command, _environment):
        process.args = list(command)
        Path(supervisor.data_dir, "ws.port").write_text("43123", encoding="ascii")
        return process

    monkeypatch.setattr(supervisor, "_spawn", spawn)
    monkeypatch.setattr(
        supervisor,
        "_tcp_ready",
        lambda *_args: attempts.append(True) or False,
    )

    with pytest.raises(SpotifySoloistError):
        supervisor.start(
            api_key=SYNTHETIC_KEY,
            device_name="Device",
            pipewire_node_name="node",
            environment={},
        )

    assert len(attempts) > 1
    assert ("terminate",) in process.events
    assert not Path(supervisor.data_dir, "ws.port").exists()
    assert supervisor.status_snapshot() == {
        "soloist_running": False,
        "ready": False,
        "ws_port": None,
    }


def test_first_start_true_second_healthy_start_false(tmp_path, monkeypatch):
    supervisor = _supervisor(tmp_path)
    started, launches, _process = _install_successful_spawn(monkeypatch, supervisor)

    assert started is True
    assert supervisor.start(
        api_key="different-synthetic-key",
        device_name="Other",
        pipewire_node_name="other-node",
        environment={"OTHER": "env"},
    ) is False
    assert len(launches) == 1
    assert supervisor.status_snapshot() == {
        "soloist_running": True,
        "ready": True,
        "ws_port": 43123,
    }


def test_graceful_stop_is_bounded_and_cleans_controls(tmp_path, monkeypatch):
    supervisor = _supervisor(tmp_path)
    _started, _launches, process = _install_successful_spawn(monkeypatch, supervisor)
    data = Path(supervisor.data_dir)
    (data / "ws.addr").write_text("127.0.0.1", encoding="ascii")
    (data / "soloist.pid").write_text("123", encoding="ascii")

    supervisor.stop()

    assert process.events == [
        ("terminate",),
        ("wait", supervisor._stop_timeout_seconds),
    ]
    assert all(not (data / name).exists() for name in supervisor.CONTROL_ARTIFACTS)
    assert supervisor.status_snapshot()["soloist_running"] is False


def test_stop_uses_kill_only_after_timeout(tmp_path):
    supervisor = _supervisor(tmp_path)
    process = FakeProcess([], first_wait_times_out=True)
    supervisor._process = process

    supervisor.stop()

    assert process.events == [
        ("terminate",),
        ("wait", supervisor._stop_timeout_seconds),
        ("kill",),
        ("wait", supervisor._stop_timeout_seconds),
    ]


def test_second_wait_timeout_retains_live_child_and_control_artifacts(tmp_path):
    supervisor = _supervisor(tmp_path)
    data = _create_control_artifacts(supervisor)

    class DoubleTimeoutProcess:
        args = ["soloist", "-k", "<redacted>"]

        def __init__(self):
            self.events = []

        def poll(self):
            return None

        def terminate(self):
            self.events.append(("terminate",))

        def kill(self):
            self.events.append(("kill",))

        def wait(self, timeout=None):
            self.events.append(("wait", timeout))
            raise subprocess.TimeoutExpired("soloist", timeout)

    process = DoubleTimeoutProcess()
    supervisor._process = process
    supervisor._ready = True
    supervisor._ws_port = 43123

    with pytest.raises(SpotifySoloistError) as raised:
        supervisor.stop()

    assert str(raised.value) == "Soloist process could not be terminated"
    assert process.events == [
        ("terminate",),
        ("wait", supervisor._stop_timeout_seconds),
        ("kill",),
        ("wait", supervisor._stop_timeout_seconds),
    ]
    _assert_live_child_retained(supervisor, process, data)


def test_kill_oserror_retains_live_child_and_control_artifacts(tmp_path):
    supervisor = _supervisor(tmp_path)
    data = _create_control_artifacts(supervisor)

    class KillFailureProcess:
        args = ["soloist", "-k", "<redacted>"]

        def __init__(self):
            self.events = []

        def poll(self):
            return None

        def terminate(self):
            self.events.append(("terminate",))

        def wait(self, timeout=None):
            self.events.append(("wait", timeout))
            raise subprocess.TimeoutExpired("soloist", timeout)

        def kill(self):
            self.events.append(("kill",))
            raise OSError("private kill failure")

    process = KillFailureProcess()
    supervisor._process = process
    supervisor._ready = True
    supervisor._ws_port = 43123

    with pytest.raises(SpotifySoloistError) as raised:
        supervisor.stop()

    assert str(raised.value) == "Soloist process could not be terminated"
    assert "private kill failure" not in str(raised.value)
    assert process.events == [
        ("terminate",),
        ("wait", supervisor._stop_timeout_seconds),
        ("kill",),
    ]
    _assert_live_child_retained(supervisor, process, data)


def test_process_lookup_error_and_idempotent_stop_are_tolerated(tmp_path):
    supervisor = _supervisor(tmp_path)
    process = FakeProcess([], terminate_lookup_error=True)
    supervisor._process = process

    supervisor.stop()
    supervisor.stop()

    assert process.events == [("terminate",)]
    assert supervisor.status_snapshot()["soloist_running"] is False


def test_terminate_oserror_retains_live_child_with_generic_error(tmp_path):
    supervisor = _supervisor(tmp_path)
    data = _create_control_artifacts(supervisor)

    class BrokenProcess:
        args = ["soloist", "-k", "<redacted>"]

        def poll(self):
            return None

        def terminate(self):
            raise OSError("private operating-system detail")

    process = BrokenProcess()
    supervisor._process = process
    supervisor._ready = True
    supervisor._ws_port = 43123

    with pytest.raises(SpotifySoloistError) as raised:
        supervisor.stop()

    assert str(raised.value) == "Soloist process could not be terminated"
    assert "private operating-system detail" not in str(raised.value)
    _assert_live_child_retained(supervisor, process, data)


def test_later_stop_retries_same_retained_process_then_cleans(tmp_path):
    supervisor = _supervisor(tmp_path)
    data = _create_control_artifacts(supervisor)

    class RetryProcess:
        args = ["soloist", "-k", "<redacted>"]

        def __init__(self):
            self.running = True
            self.fail_terminate = True
            self.events = []

        def poll(self):
            return None if self.running else 0

        def terminate(self):
            self.events.append(("terminate",))
            if self.fail_terminate:
                raise OSError("first attempt fails")

        def wait(self, timeout=None):
            self.events.append(("wait", timeout))
            self.running = False
            return 0

    process = RetryProcess()
    supervisor._process = process

    with pytest.raises(SpotifySoloistError):
        supervisor.stop()
    _assert_live_child_retained(supervisor, process, data)

    process.fail_terminate = False
    supervisor.stop()

    assert supervisor._process is None
    assert supervisor.status_snapshot() == {
        "soloist_running": False,
        "ready": False,
        "ws_port": None,
    }
    assert all(
        not (data / name).exists()
        for name in supervisor.CONTROL_ARTIFACTS
    )
    assert process.events == [
        ("terminate",),
        ("terminate",),
        ("wait", supervisor._stop_timeout_seconds),
    ]


def test_start_does_not_stack_on_retained_live_child(tmp_path, monkeypatch):
    supervisor = _supervisor(tmp_path)
    data = _create_control_artifacts(supervisor)

    class UnstoppableProcess:
        args = ["soloist", "-k", "<redacted>"]

        def poll(self):
            return None

        def terminate(self):
            raise OSError("cannot terminate")

    process = UnstoppableProcess()
    supervisor._process = process
    spawn_calls = []
    monkeypatch.setattr(
        supervisor,
        "_spawn",
        lambda *_args: spawn_calls.append(True),
    )

    with pytest.raises(SpotifySoloistError) as raised:
        supervisor.start(
            api_key=SYNTHETIC_KEY,
            device_name="Device",
            pipewire_node_name="node",
            environment={},
        )

    assert str(raised.value) == "Soloist process could not be terminated"
    assert spawn_calls == []
    _assert_live_child_retained(supervisor, process, data)


def test_readiness_and_termination_failure_retains_new_child(
    tmp_path,
    monkeypatch,
):
    supervisor = _supervisor(tmp_path)
    spawn_calls = []

    class UnstoppableProcess:
        def __init__(self, args):
            self.args = list(args)

        def poll(self):
            return None

        def terminate(self):
            raise OSError("private cleanup failure")

    process_holder = []

    def spawn(command, _environment):
        spawn_calls.append(True)
        process = UnstoppableProcess(command)
        process_holder.append(process)
        data = Path(supervisor.data_dir)
        for name in supervisor.CONTROL_ARTIFACTS:
            (data / name).write_text("live", encoding="ascii")
        return process

    monkeypatch.setattr(supervisor, "_spawn", spawn)
    monkeypatch.setattr(
        supervisor,
        "_wait_until_ready",
        lambda: (_ for _ in ()).throw(RuntimeError("readiness failure")),
    )

    with pytest.raises(SpotifySoloistError) as raised:
        supervisor.start(
            api_key=SYNTHETIC_KEY,
            device_name="Device",
            pipewire_node_name="node",
            environment={},
        )

    assert str(raised.value) == "Soloist did not become ready"
    assert SYNTHETIC_KEY not in str(raised.value)
    assert spawn_calls == [True]
    process = process_holder[0]
    assert SYNTHETIC_KEY not in repr(process.args)
    _assert_live_child_retained(
        supervisor,
        process,
        Path(supervisor.data_dir),
    )


def test_crash_is_reflected_and_restart_cleans_then_launches(tmp_path, monkeypatch):
    supervisor = _supervisor(tmp_path)
    processes = []

    def spawn(command, _environment):
        Path(supervisor.data_dir, "ws.port").write_text(
            str(43123 + len(processes)),
            encoding="ascii",
        )
        process = FakeProcess(command)
        processes.append(process)
        return process

    monkeypatch.setattr(supervisor, "_spawn", spawn)
    monkeypatch.setattr(supervisor, "_tcp_ready", lambda *_args: True)

    assert supervisor.start(
        api_key=SYNTHETIC_KEY,
        device_name="Device",
        pipewire_node_name="node",
        environment={},
    ) is True
    processes[0].running = False
    assert supervisor.status_snapshot() == {
        "soloist_running": False,
        "ready": False,
        "ws_port": None,
    }
    assert supervisor.start(
        api_key=SYNTHETIC_KEY,
        device_name="Device",
        pipewire_node_name="node",
        environment={},
    ) is True
    assert len(processes) == 2
    assert supervisor.ws_port == 43124


def test_readiness_failure_has_no_private_graph_control(tmp_path, monkeypatch):
    supervisor = _supervisor(tmp_path, ready_timeout_seconds=0.005)
    process = FakeProcess([])
    monkeypatch.setattr(supervisor, "_spawn", lambda command, _env: process)

    with pytest.raises(SpotifySoloistError):
        supervisor.start(
            api_key=SYNTHETIC_KEY,
            device_name="Device",
            pipewire_node_name="node",
            environment={},
        )

    assert process.events[0][0] == "terminate"
    assert all(event[0] in {"terminate", "wait"} for event in process.events)


def test_component_has_no_forbidden_architecture_references():
    source = Path(soloist_module.__file__).read_text(encoding="utf-8").lower()
    forbidden = (
        "spotifycoordinator",
        "spotifysecretstore",
        "spotify_runtime_supervisor",
        "main_headless",
        "audioplayer",
        "alsa_mmap",
        "ufw",
        "firewall",
        "tailscale",
        "socketserver",
        "systemctl",
        "pkill",
        "killall",
        "os.system",
        "download",
    )
    assert not any(token in source for token in forbidden)
    assert "import socket" in source


def test_deactivate_uses_exact_secret_free_control_command(
    tmp_path,
    monkeypatch,
):
    supervisor = _supervisor(tmp_path)
    _started, _launches, process = _install_successful_spawn(
        monkeypatch,
        supervisor,
        port=43123,
    )
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = list(command)
        captured["kwargs"] = dict(kwargs)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(
        soloist_module.subprocess,
        "run",
        fake_run,
    )

    assert supervisor.deactivate() is True

    assert captured["command"] == [
        str(tmp_path / "soloist"),
        "ctl",
        "-w",
        "127.0.0.1:43123",
        "deactivate",
    ]
    assert captured["kwargs"] == {
        "env": {},
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "timeout": supervisor._stop_timeout_seconds,
        "close_fds": True,
        "start_new_session": True,
        "shell": False,
        "check": False,
    }
    assert SYNTHETIC_KEY not in repr(captured)
    assert process.running is True
    assert supervisor.status_snapshot() == {
        "soloist_running": True,
        "ready": True,
        "ws_port": 43123,
    }


def test_deactivate_failure_is_generic_and_keeps_live_child(
    tmp_path,
    monkeypatch,
):
    supervisor = _supervisor(tmp_path)
    _started, _launches, process = _install_successful_spawn(
        monkeypatch,
        supervisor,
    )

    monkeypatch.setattr(
        soloist_module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [],
            1,
        ),
    )

    with pytest.raises(SpotifySoloistError) as raised:
        supervisor.deactivate()

    assert SYNTHETIC_KEY not in str(raised.value)
    assert process.running is True
    assert supervisor.status_snapshot()["soloist_running"] is True
