import json
import subprocess
import sys
from pathlib import Path

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from services import spotify_pipewire_prearm as prearm_module  # noqa: E402
from services.spotify_pipewire_prearm import (  # noqa: E402
    SpotifyPipeWirePrearm,
    SpotifyPipeWirePrearmError,
)


PRIVATE_DETAIL = "synthetic-private-command-detail"


def _make_binary(path):
    path.write_bytes(b"synthetic executable")
    path.chmod(0o700)
    return str(path)


def _prearm(tmp_path, **changes):
    values = {
        "pw_dump_binary": _make_binary(tmp_path / "pw-dump"),
        "pw_metadata_binary": _make_binary(tmp_path / "pw-metadata"),
        "wpctl_binary": _make_binary(tmp_path / "wpctl"),
        "command_timeout_seconds": 0.25,
    }
    values.update(changes)
    return SpotifyPipeWirePrearm(**values)


def _sink(
    *,
    object_id=42,
    card=3,
    device=2,
    node_name="alsa_output.synthetic",
    stream="playback",
    cross_check=3,
    include_cross_check=True,
):
    properties = {
        "media.class": "Audio/Sink",
        "alsa.card": card,
        "alsa.device": device,
        "api.alsa.pcm.stream": stream,
        "node.name": node_name,
    }
    if include_cross_check:
        properties["api.alsa.pcm.card"] = cross_check
    return {
        "id": object_id,
        "type": "PipeWire:Interface:Node",
        "info": {"props": properties},
    }


def _metadata(value="44100"):
    return {
        "id": 30,
        "type": "PipeWire:Interface:Metadata",
        "props": {"metadata.name": "settings"},
        "metadata": [
            {
                "subject": 0,
                "key": "clock.force-rate",
                "type": "Spa:Int",
                "value": value,
            }
        ],
    }


def _graph(*objects):
    return [
        {
            "id": 0,
            "type": "PipeWire:Interface:Core",
            "info": {"props": {"core.name": "private"}},
        },
        *objects,
    ]


def _install_successful_commands(
    monkeypatch,
    prearm,
    *,
    first_graph=None,
    verified_graph=None,
    volume="Volume: 1.000\n",
):
    calls = []
    dump_count = 0
    first = first_graph or _graph(_sink())
    verified = verified_graph or _graph(_sink(), _metadata())

    def run(command, **kwargs):
        nonlocal dump_count
        calls.append((list(command), kwargs))
        if command == [prearm._pw_dump_binary]:
            dump_count += 1
            graph = first if dump_count == 1 else verified
            stdout = json.dumps(graph)
        elif command[1:2] == ["get-volume"]:
            stdout = volume
        else:
            stdout = ""
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(prearm_module.subprocess, "run", run)
    return calls


def _call(prearm, *, card=3, device=2, node_name="alsa_output.synthetic", environment=None):
    return prearm.prearm(
        card_number=card,
        device_number=device,
        pipewire_node_name=node_name,
        environment=environment or {"PIPEWIRE_RUNTIME_DIR": "/run/private"},
    )


def test_constructor_is_dormant_and_uses_absolute_defaults(monkeypatch):
    monkeypatch.setattr(prearm_module.os, "lstat", lambda _path: pytest.fail("I/O"))
    prearm = SpotifyPipeWirePrearm()

    assert prearm._pw_dump_binary == "/usr/bin/pw-dump"
    assert prearm._pw_metadata_binary == "/usr/bin/pw-metadata"
    assert prearm._wpctl_binary == "/usr/bin/wpctl"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pw_dump_binary", "pw-dump"),
        ("pw_metadata_binary", "pw-metadata"),
        ("wpctl_binary", "wpctl"),
        ("command_timeout_seconds", 0),
        ("command_timeout_seconds", -1),
        ("command_timeout_seconds", True),
        ("command_timeout_seconds", float("nan")),
    ],
)
def test_invalid_constructor_inputs_are_rejected(tmp_path, field, value):
    values = {
        "pw_dump_binary": str(tmp_path / "pw-dump"),
        "pw_metadata_binary": str(tmp_path / "pw-metadata"),
        "wpctl_binary": str(tmp_path / "wpctl"),
        "command_timeout_seconds": 1.0,
    }
    values[field] = value

    with pytest.raises(SpotifyPipeWirePrearmError):
        SpotifyPipeWirePrearm(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("card_number", -1),
        ("card_number", True),
        ("device_number", "2"),
        ("pipewire_node_name", ""),
        ("pipewire_node_name", " node"),
        ("pipewire_node_name", "node\n"),
        ("environment", None),
        ("environment", {"BAD": object()}),
    ],
)
def test_invalid_prearm_inputs_are_rejected_before_subprocess(
    tmp_path,
    monkeypatch,
    field,
    value,
):
    prearm = _prearm(tmp_path)
    values = {
        "card_number": 3,
        "device_number": 2,
        "pipewire_node_name": "alsa_output.synthetic",
        "environment": {"PIPEWIRE_RUNTIME_DIR": "/run/private"},
    }
    values[field] = value
    monkeypatch.setattr(
        prearm_module.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("invalid input reached subprocess"),
    )

    with pytest.raises(SpotifyPipeWirePrearmError):
        prearm.prearm(**values)


@pytest.mark.parametrize(
    "attribute",
    ["_pw_dump_binary", "_pw_metadata_binary", "_wpctl_binary"],
)
@pytest.mark.parametrize("kind", ["missing", "directory", "symlink", "nonexec"])
def test_every_binary_must_be_regular_executable(
    tmp_path,
    monkeypatch,
    attribute,
    kind,
):
    prearm = _prearm(tmp_path)
    invalid = tmp_path / "wpctl-invalid"
    if kind == "directory":
        invalid.mkdir()
    elif kind == "symlink":
        invalid.symlink_to(tmp_path / "wpctl")
    elif kind == "nonexec":
        invalid.write_bytes(b"not executable")
        invalid.chmod(0o600)
    setattr(prearm, attribute, str(invalid))
    monkeypatch.setattr(
        prearm_module.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("invalid binary was executed"),
    )

    with pytest.raises(SpotifyPipeWirePrearmError):
        _call(prearm)


def test_exact_commands_environment_and_verified_barriers(tmp_path, monkeypatch):
    prearm = _prearm(tmp_path)
    caller_environment = {
        "PIPEWIRE_RUNTIME_DIR": "/run/private",
        "XDG_RUNTIME_DIR": "/run/private",
    }
    calls = _install_successful_commands(monkeypatch, prearm)

    assert _call(prearm, environment=caller_environment) is None
    assert [command for command, _kwargs in calls] == [
        [prearm._pw_dump_binary],
        [
            prearm._pw_metadata_binary,
            "-n",
            "settings",
            "0",
            "clock.force-rate",
            "44100",
        ],
        [prearm._pw_dump_binary],
        [prearm._wpctl_binary, "set-volume", "42", "1.0"],
        [prearm._wpctl_binary, "set-mute", "42", "0"],
        [prearm._wpctl_binary, "get-volume", "42"],
    ]
    first_environment = calls[0][1]["env"]
    assert first_environment == caller_environment
    assert first_environment is not caller_environment
    assert all(kwargs["env"] is first_environment for _command, kwargs in calls)
    for _command, kwargs in calls:
        assert kwargs == {
            "check": False,
            "env": first_environment,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "close_fds": True,
            "shell": False,
            "timeout": 0.25,
        }


def test_transient_sink_id_is_refreshed_after_rate_write(tmp_path, monkeypatch):
    prearm = _prearm(tmp_path)
    calls = _install_successful_commands(
        monkeypatch,
        prearm,
        first_graph=_graph(_sink(object_id=41)),
        verified_graph=_graph(_sink(object_id=77), _metadata()),
    )

    _call(prearm)

    assert calls[-3][0][-2:] == ["77", "1.0"]
    assert calls[-2][0][-2:] == ["77", "0"]
    assert calls[-1][0][-1] == "77"
    assert "77" not in repr(prearm.__dict__)


@pytest.mark.parametrize(
    "verified_graph",
    [
        _graph(_sink(card=4), _metadata()),
        _graph(_sink(device=1), _metadata()),
        _graph(_sink(node_name="wrong.node"), _metadata()),
        _graph(_sink(stream="capture"), _metadata()),
        _graph(_sink(cross_check=9), _metadata()),
        _graph(_sink(object_id="42"), _metadata()),
    ],
)
def test_sink_identity_mismatch_or_invalid_id_is_rejected(
    tmp_path,
    monkeypatch,
    verified_graph,
):
    prearm = _prearm(tmp_path)
    calls = _install_successful_commands(
        monkeypatch,
        prearm,
        first_graph=verified_graph,
        verified_graph=verified_graph,
    )

    with pytest.raises(SpotifyPipeWirePrearmError):
        _call(prearm)

    assert len(calls) == 1


def test_ambiguous_exact_sinks_are_rejected(tmp_path, monkeypatch):
    prearm = _prearm(tmp_path)
    calls = _install_successful_commands(
        monkeypatch,
        prearm,
        first_graph=_graph(_sink(object_id=41), _sink(object_id=42)),
    )

    with pytest.raises(SpotifyPipeWirePrearmError):
        _call(prearm)

    assert len(calls) == 1


@pytest.mark.parametrize("malformed", ["not-json", {}, [None], [{"id": 1}]])
def test_malformed_graph_is_rejected(tmp_path, monkeypatch, malformed):
    prearm = _prearm(tmp_path)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        stdout = malformed if isinstance(malformed, str) else json.dumps(malformed)
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(prearm_module.subprocess, "run", run)

    with pytest.raises(SpotifyPipeWirePrearmError):
        _call(prearm)

    assert len(calls) == 1


@pytest.mark.parametrize(
    "verified_graph",
    [
        _graph(_sink()),
        _graph(_sink(), _metadata("48000")),
        _graph(_sink(), _metadata("044100")),
        _graph(_sink(), _metadata(44100), _metadata(44100)),
        _graph(
            _sink(),
            {
                "id": 30,
                "type": "PipeWire:Interface:Metadata",
                "props": {"metadata.name": "settings"},
                "metadata": "invalid",
            },
        ),
    ],
)
def test_rate_must_be_positively_verified(
    tmp_path,
    monkeypatch,
    verified_graph,
):
    prearm = _prearm(tmp_path)
    calls = _install_successful_commands(
        monkeypatch,
        prearm,
        verified_graph=verified_graph,
    )

    with pytest.raises(SpotifyPipeWirePrearmError):
        _call(prearm)

    assert not any("set-volume" in command for command, _kwargs in calls)


@pytest.mark.parametrize(
    "volume",
    [
        "",
        "Volume: unknown\n",
        "Volume: 0.999\n",
        "Volume: 1.0001\n",
        "Volume: 1.000 [MUTED]\n",
        "1.0\n",
    ],
)
def test_volume_must_be_well_formed_and_unity(
    tmp_path,
    monkeypatch,
    volume,
):
    prearm = _prearm(tmp_path)
    _install_successful_commands(monkeypatch, prearm, volume=volume)

    with pytest.raises(SpotifyPipeWirePrearmError):
        _call(prearm)


@pytest.mark.parametrize("mode", ["nonzero", "timeout", "oserror"])
def test_command_failures_are_sanitized(tmp_path, monkeypatch, mode):
    prearm = _prearm(tmp_path)

    def run(command, **_kwargs):
        if mode == "timeout":
            raise subprocess.TimeoutExpired(command, 0.25, stderr=PRIVATE_DETAIL)
        if mode == "oserror":
            raise OSError(PRIVATE_DETAIL)
        return subprocess.CompletedProcess(command, 7, PRIVATE_DETAIL, PRIVATE_DETAIL)

    monkeypatch.setattr(prearm_module.subprocess, "run", run)

    with pytest.raises(SpotifyPipeWirePrearmError) as raised:
        _call(prearm)

    assert PRIVATE_DETAIL not in str(raised.value)
