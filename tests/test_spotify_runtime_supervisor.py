import os
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from services.spotify_runtime_supervisor import (  # noqa: E402
    SpotifyRuntimeError,
    SpotifyRuntimeSupervisor,
)


class FakeProcess:
    def __init__(
        self,
        name,
        events,
        *,
        running=True,
        timeout_on_first_wait=False,
    ):
        self.name = name
        self.events = events
        self.running = bool(running)
        self.timeout_on_first_wait = bool(
            timeout_on_first_wait
        )
        self.wait_calls = 0

    def poll(self):
        return None if self.running else 1

    def terminate(self):
        self.events.append(
            ("terminate", self.name)
        )

    def kill(self):
        self.events.append(
            ("kill", self.name)
        )
        self.running = False

    def wait(self, timeout=None):
        self.wait_calls += 1
        self.events.append(
            ("wait", self.name, timeout)
        )

        if (
            self.timeout_on_first_wait
            and self.wait_calls == 1
        ):
            raise subprocess.TimeoutExpired(
                self.name,
                timeout,
            )

        self.running = False
        return 0


def _supervisor(tmp_path):
    return SpotifyRuntimeSupervisor(
        runtime_dir=str(
            tmp_path / "runtime"
        ),
        pipewire_binary="/usr/bin/pipewire",
        wireplumber_binary="/usr/bin/wireplumber",
    )


def _install_fake_spawn(
    monkeypatch,
    supervisor,
    *,
    wireplumber_running=True,
    stub_wireplumber_ready=True,
):
    events = []
    processes = []

    def spawn(command, env):
        name = Path(command[0]).name
        events.append(
            (
                "spawn",
                tuple(command),
                env["XDG_RUNTIME_DIR"],
                env["PIPEWIRE_RUNTIME_DIR"],
            )
        )

        process = FakeProcess(
            name,
            events,
            running=(
                wireplumber_running
                if name == "wireplumber"
                else True
            ),
        )
        processes.append(process)
        return process

    monkeypatch.setattr(
        supervisor,
        "_spawn",
        spawn,
    )
    monkeypatch.setattr(
        supervisor,
        "_wait_for_pipewire_ready",
        lambda: events.append(
            ("pipewire_ready",)
        ),
    )
    if stub_wireplumber_ready:
        monkeypatch.setattr(
            supervisor,
            "_wait_for_wireplumber_ready",
            lambda: events.append(
                ("wireplumber_ready",)
            ),
        )

    return events, processes


def test_constructor_is_side_effect_free(tmp_path):
    runtime = tmp_path / "runtime"

    supervisor = SpotifyRuntimeSupervisor(
        runtime_dir=str(runtime)
    )

    assert supervisor.runtime_dir == str(runtime)
    assert not runtime.exists()
    assert supervisor.status_snapshot() == {
        "pipewire_running": False,
        "wireplumber_running": False,
    }


def test_relative_runtime_directory_is_rejected():
    with pytest.raises(SpotifyRuntimeError):
        SpotifyRuntimeSupervisor(
            runtime_dir="relative/path"
        )


def test_explicit_runtime_directory_wins(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        "SROVA_SPOTIFY_RUNTIME_DIR",
        "/should/not/be/used",
    )
    monkeypatch.setenv(
        "RUNTIME_DIRECTORY",
        "/also/not/used",
    )

    expected = tmp_path / "explicit"

    supervisor = SpotifyRuntimeSupervisor(
        runtime_dir=str(expected)
    )

    assert supervisor.runtime_dir == str(expected)


def test_runtime_directory_override_environment(
    monkeypatch,
):
    monkeypatch.setenv(
        "SROVA_SPOTIFY_RUNTIME_DIR",
        "/tmp/srova-explicit-spotify-runtime",
    )
    monkeypatch.setenv(
        "RUNTIME_DIRECTORY",
        "/run/srova",
    )

    supervisor = SpotifyRuntimeSupervisor()

    assert supervisor.runtime_dir == (
        "/tmp/srova-explicit-spotify-runtime"
    )


def test_systemd_runtime_directory_is_used(
    monkeypatch,
):
    monkeypatch.delenv(
        "SROVA_SPOTIFY_RUNTIME_DIR",
        raising=False,
    )
    monkeypatch.setenv(
        "RUNTIME_DIRECTORY",
        "/run/srova",
    )

    supervisor = SpotifyRuntimeSupervisor()

    assert supervisor.runtime_dir == (
        "/run/srova/spotify"
    )


def test_first_systemd_runtime_directory_is_used(
    monkeypatch,
):
    monkeypatch.delenv(
        "SROVA_SPOTIFY_RUNTIME_DIR",
        raising=False,
    )
    monkeypatch.setenv(
        "RUNTIME_DIRECTORY",
        "/run/srova:/run/other",
    )

    supervisor = SpotifyRuntimeSupervisor()

    assert supervisor.runtime_dir == (
        "/run/srova/spotify"
    )


def test_fallback_runtime_directory(
    monkeypatch,
):
    monkeypatch.delenv(
        "SROVA_SPOTIFY_RUNTIME_DIR",
        raising=False,
    )
    monkeypatch.delenv(
        "RUNTIME_DIRECTORY",
        raising=False,
    )

    supervisor = SpotifyRuntimeSupervisor()

    assert supervisor.runtime_dir == (
        "/run/srova/spotify"
    )


def test_prepare_runtime_directory_uses_0700(
    tmp_path,
):
    supervisor = _supervisor(tmp_path)

    supervisor._prepare_runtime_dir()

    path = Path(supervisor.runtime_dir)

    assert path.is_dir()
    assert stat.S_IMODE(
        path.stat().st_mode
    ) == 0o700


def test_existing_runtime_directory_is_resecured(
    tmp_path,
):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o755)
    os.chmod(runtime, 0o755)

    supervisor = SpotifyRuntimeSupervisor(
        runtime_dir=str(runtime)
    )

    supervisor._prepare_runtime_dir()

    assert stat.S_IMODE(
        runtime.stat().st_mode
    ) == 0o700


def test_runtime_directory_symlink_is_rejected(
    tmp_path,
):
    real = tmp_path / "real"
    real.mkdir()

    link = tmp_path / "runtime"
    link.symlink_to(
        real,
        target_is_directory=True,
    )

    supervisor = SpotifyRuntimeSupervisor(
        runtime_dir=str(link)
    )

    with pytest.raises(SpotifyRuntimeError):
        supervisor._prepare_runtime_dir()


def test_runtime_directory_regular_file_is_rejected(
    tmp_path,
):
    runtime = tmp_path / "runtime"
    runtime.write_text(
        "not a directory",
        encoding="utf-8",
    )

    supervisor = SpotifyRuntimeSupervisor(
        runtime_dir=str(runtime)
    )

    with pytest.raises(SpotifyRuntimeError):
        supervisor._prepare_runtime_dir()


def test_private_environment_is_isolated(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        "PIPEWIRE_REMOTE",
        "desktop-pipewire",
    )
    monkeypatch.setenv(
        "PULSE_SERVER",
        "desktop-pulse",
    )
    monkeypatch.setenv(
        "DBUS_SESSION_BUS_ADDRESS",
        "unix:path=/borrowed/session/bus",
    )
    monkeypatch.setenv("SROVA_SYNTHETIC_SECRET", "must-not-leak")
    monkeypatch.setenv("SPOTIFY_API_TOKEN", "must-not-leak")
    monkeypatch.setenv("UNRELATED_APPLICATION_VALUE", "must-not-leak")
    monkeypatch.setenv("HOME", "/home/synthetic")
    monkeypatch.setenv("LANG", "C.UTF-8")

    supervisor = _supervisor(tmp_path)

    env = supervisor.private_environment()

    assert env["XDG_RUNTIME_DIR"] == (
        supervisor.runtime_dir
    )
    assert env["PIPEWIRE_RUNTIME_DIR"] == (
        supervisor.runtime_dir
    )
    assert "PIPEWIRE_REMOTE" not in env
    assert "PULSE_SERVER" not in env
    assert "DBUS_SESSION_BUS_ADDRESS" not in env
    assert "SROVA_SYNTHETIC_SECRET" not in env
    assert "SPOTIFY_API_TOKEN" not in env
    assert "UNRELATED_APPLICATION_VALUE" not in env
    assert env["HOME"] == "/home/synthetic"
    assert env["LANG"] == "C.UTF-8"
    assert set(env).issubset(
        set(supervisor.CHILD_ENVIRONMENT_KEYS)
        | {"XDG_RUNTIME_DIR", "PIPEWIRE_RUNTIME_DIR"}
    )


def test_commands_are_exact_and_systemwide(
    tmp_path,
):
    supervisor = _supervisor(tmp_path)

    assert tuple(
        supervisor.pipewire_command()
    ) == (
        "/usr/bin/pipewire",
    )

    assert tuple(
        supervisor.wireplumber_command()
    ) == (
        "/usr/bin/wireplumber",
        "--profile",
        "main-systemwide",
    )


def test_start_order_is_pipewire_then_ready_then_wireplumber(
    tmp_path,
    monkeypatch,
):
    supervisor = _supervisor(tmp_path)

    events, _processes = _install_fake_spawn(
        monkeypatch,
        supervisor,
    )

    started = supervisor.start_private_graph()

    assert started is True

    assert events[0][0:2] == (
        "spawn",
        ("/usr/bin/pipewire",),
    )
    assert events[1] == (
        "pipewire_ready",
    )
    assert events[2][0:2] == (
        "spawn",
        (
            "/usr/bin/wireplumber",
            "--profile",
            "main-systemwide",
        ),
    )
    assert events[3] == (
        "wireplumber_ready",
    )

    assert supervisor.status_snapshot() == {
        "pipewire_running": True,
        "wireplumber_running": True,
    }


def test_start_is_idempotent_when_graph_is_healthy(
    tmp_path,
    monkeypatch,
):
    supervisor = _supervisor(tmp_path)

    events, _processes = _install_fake_spawn(
        monkeypatch,
        supervisor,
    )

    assert supervisor.start_private_graph() is True
    first_event_count = len(events)

    assert supervisor.start_private_graph() is False
    assert len(events) == first_event_count


def test_wireplumber_start_failure_cleans_pipewire(
    tmp_path,
    monkeypatch,
):
    supervisor = _supervisor(tmp_path)

    events, _processes = _install_fake_spawn(
        monkeypatch,
        supervisor,
        wireplumber_running=False,
        stub_wireplumber_ready=False,
    )

    with pytest.raises(SpotifyRuntimeError):
        supervisor.start_private_graph()

    assert (
        "terminate",
        "pipewire",
    ) in events

    assert supervisor.status_snapshot() == {
        "pipewire_running": False,
        "wireplumber_running": False,
    }


def test_pipewire_readiness_failure_cleans_pipewire(
    tmp_path,
    monkeypatch,
):
    supervisor = _supervisor(tmp_path)
    events = []

    process = FakeProcess(
        "pipewire",
        events,
    )

    monkeypatch.setattr(
        supervisor,
        "_spawn",
        lambda command, env: process,
    )

    def fail_ready():
        raise SpotifyRuntimeError(
            "synthetic readiness failure"
        )

    monkeypatch.setattr(
        supervisor,
        "_wait_for_pipewire_ready",
        fail_ready,
    )

    with pytest.raises(
        SpotifyRuntimeError,
        match="synthetic readiness failure",
    ):
        supervisor.start_private_graph()

    assert (
        "terminate",
        "pipewire",
    ) in events

    assert supervisor.status_snapshot() == {
        "pipewire_running": False,
        "wireplumber_running": False,
    }


def test_stop_order_is_wireplumber_then_pipewire(
    tmp_path,
    monkeypatch,
):
    supervisor = _supervisor(tmp_path)

    events, _processes = _install_fake_spawn(
        monkeypatch,
        supervisor,
    )

    supervisor.start_private_graph()
    events.clear()

    supervisor.stop_private_graph()

    terminate_events = [
        event
        for event in events
        if event[0] == "terminate"
    ]

    assert terminate_events == [
        ("terminate", "wireplumber"),
        ("terminate", "pipewire"),
    ]

    assert supervisor.status_snapshot() == {
        "pipewire_running": False,
        "wireplumber_running": False,
    }


def test_stop_uses_kill_only_after_timeout(
    tmp_path,
):
    supervisor = _supervisor(tmp_path)
    events = []

    process = FakeProcess(
        "pipewire",
        events,
        timeout_on_first_wait=True,
    )

    supervisor._terminate_process(process)

    assert events == [
        ("terminate", "pipewire"),
        (
            "wait",
            "pipewire",
            supervisor.PROCESS_STOP_TIMEOUT_SECONDS,
        ),
        ("kill", "pipewire"),
        (
            "wait",
            "pipewire",
            supervisor.PROCESS_STOP_TIMEOUT_SECONDS,
        ),
    ]


def test_dead_process_does_not_receive_signal(
    tmp_path,
):
    supervisor = _supervisor(tmp_path)
    events = []

    process = FakeProcess(
        "pipewire",
        events,
        running=False,
    )

    supervisor._terminate_process(process)

    assert events == []


def test_pipewire_socket_path_is_private(
    tmp_path,
):
    supervisor = _supervisor(tmp_path)

    assert supervisor.pipewire_socket == os.path.join(
        supervisor.runtime_dir,
        "pipewire-0",
    )


def test_stale_runtime_endpoint_artifacts_are_removed(
    tmp_path,
):
    supervisor = _supervisor(tmp_path)
    supervisor._prepare_runtime_dir()

    runtime_dir = Path(
        supervisor.runtime_dir
    )

    for name in supervisor.RUNTIME_ENDPOINT_NAMES:
        (runtime_dir / name).write_text(
            "stale",
            encoding="utf-8",
        )

    supervisor._clear_stale_runtime_endpoints()

    assert all(
        not (runtime_dir / name).exists()
        for name in supervisor.RUNTIME_ENDPOINT_NAMES
    )


def test_invalid_runtime_endpoint_artifact_is_rejected(
    tmp_path,
):
    supervisor = _supervisor(tmp_path)
    supervisor._prepare_runtime_dir()

    invalid = (
        Path(supervisor.runtime_dir)
        / "pipewire-0"
    )
    invalid.mkdir()

    with pytest.raises(
        SpotifyRuntimeError,
        match="endpoint artifact is invalid",
    ):
        supervisor._clear_stale_runtime_endpoints()

    assert invalid.is_dir()


def test_stale_pipewire_socket_cannot_satisfy_new_startup(
    tmp_path,
    monkeypatch,
):
    supervisor = _supervisor(tmp_path)
    supervisor._prepare_runtime_dir()

    stale = socket.socket(
        socket.AF_UNIX,
        socket.SOCK_STREAM,
    )
    try:
        stale.bind(
            supervisor.pipewire_socket
        )
    finally:
        stale.close()

    assert Path(
        supervisor.pipewire_socket
    ).exists()

    events = []
    process = FakeProcess(
        "pipewire",
        events,
    )

    monkeypatch.setattr(
        supervisor,
        "_spawn",
        lambda command, env: process,
    )

    supervisor.PIPEWIRE_READY_TIMEOUT_SECONDS = 0.02
    supervisor.READY_POLL_SECONDS = 0.001

    with pytest.raises(
        SpotifyRuntimeError,
        match="PipeWire did not become ready",
    ):
        supervisor.start_private_graph()

    assert not Path(
        supervisor.pipewire_socket
    ).exists()
    assert (
        "terminate",
        "pipewire",
    ) in events


def test_wireplumber_stability_wait_accepts_surviving_process(
    tmp_path,
):
    supervisor = _supervisor(tmp_path)
    events = []

    supervisor._wireplumber_process = FakeProcess(
        "wireplumber",
        events,
        running=True,
    )

    supervisor.WIREPLUMBER_STABILITY_SECONDS = 0.01
    supervisor.READY_POLL_SECONDS = 0.001

    supervisor._wait_for_wireplumber_ready()

    assert supervisor._process_alive(
        supervisor._wireplumber_process
    )


def test_wireplumber_stability_wait_rejects_delayed_exit(
    tmp_path,
):
    supervisor = _supervisor(tmp_path)

    class DelayedExitProcess:
        def __init__(self):
            self.poll_calls = 0

        def poll(self):
            self.poll_calls += 1
            if self.poll_calls < 3:
                return None
            return 1

    process = DelayedExitProcess()
    supervisor._wireplumber_process = process
    supervisor.WIREPLUMBER_STABILITY_SECONDS = 0.05
    supervisor.READY_POLL_SECONDS = 0.001

    with pytest.raises(
        SpotifyRuntimeError,
        match="WirePlumber exited during startup",
    ):
        supervisor._wait_for_wireplumber_ready()

    assert process.poll_calls >= 3
