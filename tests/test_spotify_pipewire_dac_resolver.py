import json
import subprocess
import sys
from pathlib import Path

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from services import spotify_pipewire_dac_resolver as resolver_module  # noqa: E402
from services.spotify_pipewire_dac_resolver import (  # noqa: E402
    SpotifyPipeWireDacResolutionError,
    SpotifyPipeWireDacResolver,
)


PRIVATE_VALUE = "synthetic-private-environment-value"
PRIVATE_STDERR = "synthetic-private-stderr-payload"
PRIVATE_GRAPH_VALUE = "synthetic-private-graph-payload"


def _make_binary(path):
    path.write_bytes(b"synthetic executable")
    path.chmod(0o700)
    return path


def _resolver(tmp_path, **kwargs):
    binary = _make_binary(tmp_path / "pw-dump")
    return SpotifyPipeWireDacResolver(
        pw_dump_binary=str(binary),
        ready_timeout_seconds=kwargs.pop("ready_timeout_seconds", 0.1),
        poll_seconds=kwargs.pop("poll_seconds", 0.01),
        command_timeout_seconds=kwargs.pop("command_timeout_seconds", 0.05),
        **kwargs,
    )


def _object(properties):
    return {
        "id": 42,
        "type": "PipeWire:Interface:Node",
        "info": {"props": dict(properties)},
    }


def _sink(
    *,
    card=0,
    device=0,
    stream="playback",
    node_name="alsa_output.synthetic",
    cross_check=0,
    include_cross_check=True,
    media_class="Audio/Sink",
    extra=None,
):
    properties = {
        "media.class": media_class,
        "alsa.card": card,
        "alsa.device": device,
        "api.alsa.pcm.stream": stream,
        "node.name": node_name,
    }
    if include_cross_check:
        properties["api.alsa.pcm.card"] = cross_check
    if extra:
        properties.update(extra)
    return _object(properties)


def _realistic_graph(*nodes):
    return [
        {
            "id": 0,
            "type": "PipeWire:Interface:Core",
            "info": {"props": {"core.name": "pipewire-private"}},
        },
        {
            "id": 1,
            "type": "PipeWire:Interface:Module",
            "info": {"props": {"module.name": "libpipewire-module-protocol-native"}},
        },
        {"id": 2, "type": "PipeWire:Interface:SecurityContext"},
        {"id": 3, "type": "PipeWire:Interface:Profiler"},
        {"id": 30, "type": "PipeWire:Interface:Metadata"},
        {"id": 31, "type": "PipeWire:Interface:Metadata"},
        {"id": 32, "type": "PipeWire:Interface:Metadata"},
        {
            "id": 40,
            "type": "PipeWire:Interface:Device",
            "info": {"props": {"media.class": "Audio/Device"}},
        },
        {
            "id": 41,
            "type": "PipeWire:Interface:Port",
            "info": {"props": {"port.direction": "out"}},
        },
        *nodes,
    ]


def _install_graphs(monkeypatch, graphs, *, returncode=0, stderr=""):
    calls = []
    remaining = list(graphs)

    def run(command, **kwargs):
        calls.append((list(command), kwargs))
        graph = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        stdout = graph if isinstance(graph, str) else json.dumps(graph)
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    monkeypatch.setattr(resolver_module.subprocess, "run", run)
    return calls


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def _install_clock(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(resolver_module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(resolver_module.time, "sleep", clock.sleep)
    return clock


def _resolve(resolver, *, card=0, device=0, environment=None):
    return resolver.resolve(
        card_number=card,
        device_number=device,
        environment=environment or {"PIPEWIRE_REMOTE": "private"},
    )


def test_constructor_is_side_effect_free(tmp_path):
    binary = tmp_path / "not-created-by-constructor"

    resolver = SpotifyPipeWireDacResolver(pw_dump_binary=str(binary))

    assert resolver.pw_dump_binary == str(binary)
    assert not binary.exists()


def test_relative_pw_dump_binary_is_rejected():
    with pytest.raises(SpotifyPipeWireDacResolutionError):
        SpotifyPipeWireDacResolver(pw_dump_binary="relative/pw-dump")


def test_missing_binary_is_rejected_at_resolve_time(tmp_path, monkeypatch):
    resolver = SpotifyPipeWireDacResolver(
        pw_dump_binary=str(tmp_path / "missing")
    )
    calls = []
    monkeypatch.setattr(
        resolver_module.subprocess,
        "run",
        lambda *_args, **_kwargs: calls.append(True),
    )

    with pytest.raises(SpotifyPipeWireDacResolutionError):
        _resolve(resolver)

    assert calls == []


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_invalid_binary_object_is_rejected(tmp_path, kind):
    binary = tmp_path / "pw-dump"
    if kind == "directory":
        binary.mkdir()
    else:
        target = _make_binary(tmp_path / "target")
        binary.symlink_to(target)
    resolver = SpotifyPipeWireDacResolver(pw_dump_binary=str(binary))

    with pytest.raises(SpotifyPipeWireDacResolutionError):
        _resolve(resolver)


def test_non_executable_binary_is_rejected(tmp_path):
    binary = tmp_path / "pw-dump"
    binary.write_bytes(b"not executable")
    binary.chmod(0o600)
    resolver = SpotifyPipeWireDacResolver(pw_dump_binary=str(binary))

    with pytest.raises(SpotifyPipeWireDacResolutionError):
        _resolve(resolver)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ready_timeout_seconds", 0),
        ("ready_timeout_seconds", -1),
        ("ready_timeout_seconds", True),
        ("ready_timeout_seconds", float("nan")),
        ("ready_timeout_seconds", float("inf")),
        ("poll_seconds", 0),
        ("poll_seconds", -0.1),
        ("poll_seconds", False),
        ("command_timeout_seconds", 0),
        ("command_timeout_seconds", -1),
        ("command_timeout_seconds", "invalid"),
    ],
)
def test_invalid_timeout_and_poll_values_are_rejected(tmp_path, field, value):
    values = {
        "pw_dump_binary": str(tmp_path / "pw-dump"),
        "ready_timeout_seconds": 1,
        "poll_seconds": 0.1,
        "command_timeout_seconds": 1,
    }
    values[field] = value

    with pytest.raises(SpotifyPipeWireDacResolutionError):
        SpotifyPipeWireDacResolver(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("card", -1),
        ("device", -1),
        ("card", "0"),
        ("device", "0"),
        ("card", 0.0),
        ("device", 0.0),
        ("card", True),
        ("device", False),
        ("card", "hw:0,0"),
        ("device", "plughw:0,0"),
    ],
)
def test_invalid_numeric_inputs_are_rejected_before_execution(
    tmp_path,
    monkeypatch,
    field,
    value,
):
    resolver = _resolver(tmp_path)
    calls = _install_graphs(monkeypatch, [[_sink()]])
    values = {"card": 0, "device": 0}
    values[field] = value

    with pytest.raises(SpotifyPipeWireDacResolutionError):
        _resolve(resolver, **values)

    assert calls == []


@pytest.mark.parametrize(
    "environment",
    [None, [], {1: "value"}, {"KEY": 1}],
)
def test_invalid_environment_is_rejected(tmp_path, monkeypatch, environment):
    resolver = _resolver(tmp_path)
    calls = _install_graphs(monkeypatch, [[_sink()]])

    with pytest.raises(SpotifyPipeWireDacResolutionError):
        resolver.resolve(
            card_number=0,
            device_number=0,
            environment=environment,
        )

    assert calls == []


def test_card_zero_device_zero_resolves(tmp_path, monkeypatch):
    resolver = _resolver(tmp_path)
    _install_graphs(monkeypatch, [[_sink()]])

    assert _resolve(resolver) == "alsa_output.synthetic"


def test_nonzero_card_and_device_resolve(tmp_path, monkeypatch):
    resolver = _resolver(tmp_path)
    _install_graphs(
        monkeypatch,
        [[_sink(card=7, device=3, cross_check=7)]],
    )

    assert _resolve(resolver, card=7, device=3) == "alsa_output.synthetic"


def test_decimal_string_properties_resolve(tmp_path, monkeypatch):
    resolver = _resolver(tmp_path)
    _install_graphs(
        monkeypatch,
        [[_sink(card="07", device="3", cross_check="7")]],
    )

    assert _resolve(resolver, card=7, device=3) == "alsa_output.synthetic"


@pytest.mark.parametrize(
    "value",
    [True, False, -1, 1.0, "-1", "+1", " 1", "1 ", "1.0", "one", "١"],
)
def test_unsafe_numeric_property_forms_are_not_accepted(value):
    assert SpotifyPipeWireDacResolver._numeric_property(value) is None


def test_unrelated_graph_nodes_are_ignored(tmp_path, monkeypatch):
    resolver = _resolver(tmp_path)
    graph = [
        _sink(card=1, cross_check=1, node_name="wrong-card"),
        _sink(device=1, node_name="wrong-device"),
        _sink(stream="capture", node_name="capture"),
        _sink(media_class="Audio/Source", node_name="source"),
        _sink(node_name="selected"),
    ]
    _install_graphs(monkeypatch, [graph])

    assert _resolve(resolver) == "selected"


def test_realistic_heterogeneous_graph_resolves_selected_sink(
    tmp_path,
    monkeypatch,
):
    resolver = _resolver(tmp_path)
    selected = _sink(
        node_name=(
            "alsa_output.usb-Topping_DX5_II-00."
            "HiFi__Headphones__sink"
        ),
        extra={
            "api.alsa.path": "hw:II,0",
            "object.path": "alsa:acp:II:0:playback",
        },
    )
    _install_graphs(monkeypatch, [_realistic_graph(selected)])

    assert _resolve(resolver) == (
        "alsa_output.usb-Topping_DX5_II-00.HiFi__Headphones__sink"
    )


@pytest.mark.parametrize(
    "object_type",
    [
        "PipeWire:Interface:Metadata",
        "PipeWire:Interface:Profiler",
        "PipeWire:Interface:SecurityContext",
    ],
)
def test_explicit_non_node_without_info_is_ignored(
    tmp_path,
    monkeypatch,
    object_type,
):
    resolver = _resolver(tmp_path)
    graph = [{"id": 30, "type": object_type}, _sink()]
    _install_graphs(monkeypatch, [graph])

    assert _resolve(resolver) == "alsa_output.synthetic"


@pytest.mark.parametrize(
    "info_value",
    [None, [], "malformed", {"props": None}],
)
def test_explicit_non_node_does_not_require_valid_info_props(
    tmp_path,
    monkeypatch,
    info_value,
):
    resolver = _resolver(tmp_path)
    graph = [
        {
            "id": 30,
            "type": "PipeWire:Interface:Metadata",
            "info": info_value,
        },
        _sink(),
    ]
    _install_graphs(monkeypatch, [graph])

    assert _resolve(resolver) == "alsa_output.synthetic"


@pytest.mark.parametrize(
    "node",
    [
        {"type": "PipeWire:Interface:Node"},
        {"type": "PipeWire:Interface:Node", "info": None},
        {"type": "PipeWire:Interface:Node", "info": {}},
        {"type": "PipeWire:Interface:Node", "info": {"props": []}},
    ],
)
def test_explicit_node_requires_valid_info_props(
    tmp_path,
    monkeypatch,
    node,
):
    resolver = _resolver(tmp_path)
    clock = _install_clock(monkeypatch)
    calls = _install_graphs(monkeypatch, [[node, _sink()]])

    with pytest.raises(SpotifyPipeWireDacResolutionError):
        _resolve(resolver)

    assert len(calls) == 1
    assert clock.sleeps == []


def test_untyped_valid_property_object_preserves_compatibility(
    tmp_path,
    monkeypatch,
):
    resolver = _resolver(tmp_path)
    sink = _sink()
    del sink["type"]
    _install_graphs(monkeypatch, [[sink]])

    assert _resolve(resolver) == "alsa_output.synthetic"


@pytest.mark.parametrize(
    "graph_object",
    [{}, {"info": None}, {"info": {}}, {"info": {"props": []}}],
)
def test_untyped_malformed_object_fails_closed(
    tmp_path,
    monkeypatch,
    graph_object,
):
    resolver = _resolver(tmp_path)
    clock = _install_clock(monkeypatch)
    calls = _install_graphs(monkeypatch, [[graph_object, _sink()]])

    with pytest.raises(SpotifyPipeWireDacResolutionError):
        _resolve(resolver)

    assert len(calls) == 1
    assert clock.sleeps == []


@pytest.mark.parametrize("object_type", [None, 123, [], {}])
def test_malformed_explicit_type_fails_closed(
    tmp_path,
    monkeypatch,
    object_type,
):
    resolver = _resolver(tmp_path)
    clock = _install_clock(monkeypatch)
    graph_object = {
        "type": object_type,
        "info": {"props": {"media.class": "Audio/Sink"}},
    }
    calls = _install_graphs(monkeypatch, [[graph_object, _sink()]])

    with pytest.raises(SpotifyPipeWireDacResolutionError):
        _resolve(resolver)

    assert len(calls) == 1
    assert clock.sleeps == []


@pytest.mark.parametrize(
    ("card", "expected"),
    [
        (0, "alsa_output.usb-Topping_DX5_II-00.HiFi__Headphones__sink"),
        (1, "alsa_output.platform-pcspkr.mono-fallback"),
    ],
)
def test_realistic_two_sink_graph_resolves_each_identity(
    tmp_path,
    monkeypatch,
    card,
    expected,
):
    resolver = _resolver(tmp_path)
    dx5 = _sink(
        card=0,
        device=0,
        cross_check=0,
        node_name=(
            "alsa_output.usb-Topping_DX5_II-00."
            "HiFi__Headphones__sink"
        ),
    )
    pcsp = _sink(
        card=1,
        device=0,
        cross_check=1,
        node_name="alsa_output.platform-pcspkr.mono-fallback",
    )
    _install_graphs(monkeypatch, [_realistic_graph(dx5, pcsp)])

    assert _resolve(resolver, card=card) == expected


def test_realistic_graph_with_ambiguous_selected_nodes_fails_immediately(
    tmp_path,
    monkeypatch,
):
    resolver = _resolver(tmp_path)
    clock = _install_clock(monkeypatch)
    graph = _realistic_graph(
        _sink(node_name="first"),
        _sink(node_name="second"),
    )
    calls = _install_graphs(monkeypatch, [graph])

    with pytest.raises(SpotifyPipeWireDacResolutionError):
        _resolve(resolver)

    assert len(calls) == 1
    assert clock.sleeps == []


def test_realistic_graph_with_conflicting_cross_check_fails_immediately(
    tmp_path,
    monkeypatch,
):
    resolver = _resolver(tmp_path)
    clock = _install_clock(monkeypatch)
    graph = _realistic_graph(_sink(cross_check=1))
    calls = _install_graphs(monkeypatch, [graph])

    with pytest.raises(SpotifyPipeWireDacResolutionError):
        _resolve(resolver)

    assert len(calls) == 1
    assert clock.sleeps == []


def test_exact_node_name_is_returned_without_stripping(tmp_path, monkeypatch):
    resolver = _resolver(tmp_path)
    _install_graphs(monkeypatch, [[_sink(node_name="  exact.node.name  ")]])

    assert _resolve(resolver) == "  exact.node.name  "


@pytest.mark.parametrize("cross_check", [0, "0"])
def test_matching_cross_check_is_accepted(tmp_path, monkeypatch, cross_check):
    resolver = _resolver(tmp_path)
    _install_graphs(monkeypatch, [[_sink(cross_check=cross_check)]])

    assert _resolve(resolver) == "alsa_output.synthetic"


@pytest.mark.parametrize("mode", ["absent", "null"])
def test_absent_or_null_cross_check_is_accepted(tmp_path, monkeypatch, mode):
    resolver = _resolver(tmp_path)
    sink = _sink(include_cross_check=mode != "absent")
    if mode == "null":
        sink["info"]["props"]["api.alsa.pcm.card"] = None
    _install_graphs(monkeypatch, [[sink]])

    assert _resolve(resolver) == "alsa_output.synthetic"


@pytest.mark.parametrize("cross_check", [1, "1", True, -1, 0.0, "bad"])
def test_conflicting_or_malformed_cross_check_fails_closed(
    tmp_path,
    monkeypatch,
    cross_check,
):
    resolver = _resolver(tmp_path)
    clock = _install_clock(monkeypatch)
    calls = _install_graphs(monkeypatch, [[_sink(cross_check=cross_check)]])

    with pytest.raises(SpotifyPipeWireDacResolutionError):
        _resolve(resolver)

    assert len(calls) == 1
    assert clock.sleeps == []


@pytest.mark.parametrize(
    "omitted",
    ["api.alsa.pcm.device", "api.alsa.path", "object.path", "node.description"],
)
def test_non_authoritative_properties_are_not_required(
    tmp_path,
    monkeypatch,
    omitted,
):
    resolver = _resolver(tmp_path)
    properties = {
        "api.alsa.pcm.device": "synthetic",
        "api.alsa.path": "hw:SYNTHETIC,0",
        "object.path": "alsa:synthetic",
        "node.description": "Synthetic DAC",
    }
    properties.pop(omitted)
    _install_graphs(monkeypatch, [[_sink(extra=properties)]])

    assert _resolve(resolver) == "alsa_output.synthetic"


@pytest.mark.parametrize("node_name", [None, "", "   ", 123])
def test_invalid_node_name_fails_closed(tmp_path, monkeypatch, node_name):
    resolver = _resolver(tmp_path)
    clock = _install_clock(monkeypatch)
    calls = _install_graphs(monkeypatch, [[_sink(node_name=node_name)]])

    with pytest.raises(SpotifyPipeWireDacResolutionError):
        _resolve(resolver)

    assert len(calls) == 1
    assert clock.sleeps == []


def test_missing_node_name_fails_closed(tmp_path, monkeypatch):
    resolver = _resolver(tmp_path)
    sink = _sink()
    del sink["info"]["props"]["node.name"]
    calls = _install_graphs(monkeypatch, [[sink]])

    with pytest.raises(SpotifyPipeWireDacResolutionError):
        _resolve(resolver)

    assert len(calls) == 1


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_candidates_fail_immediately_regardless_of_order(
    tmp_path,
    monkeypatch,
    reverse,
):
    resolver = _resolver(tmp_path)
    clock = _install_clock(monkeypatch)
    graph = [_sink(node_name="first"), _sink(node_name="second")]
    if reverse:
        graph.reverse()
    calls = _install_graphs(monkeypatch, [graph])

    with pytest.raises(SpotifyPipeWireDacResolutionError):
        _resolve(resolver)

    assert len(calls) == 1
    assert clock.sleeps == []


def test_first_empty_dump_then_selected_sink_succeeds(tmp_path, monkeypatch):
    resolver = _resolver(tmp_path)
    clock = _install_clock(monkeypatch)
    calls = _install_graphs(monkeypatch, [[], [_sink()]])

    assert _resolve(resolver) == "alsa_output.synthetic"
    assert len(calls) == 2
    assert clock.sleeps == [resolver._poll_seconds]


def test_multiple_empty_dumps_then_selected_sink_succeeds(tmp_path, monkeypatch):
    resolver = _resolver(tmp_path)
    clock = _install_clock(monkeypatch)
    calls = _install_graphs(monkeypatch, [[], [], [], [_sink()]])

    assert _resolve(resolver) == "alsa_output.synthetic"
    assert len(calls) == 4
    assert len(clock.sleeps) == 3


def test_zero_candidates_times_out_with_bounded_polling(tmp_path, monkeypatch):
    resolver = _resolver(
        tmp_path,
        ready_timeout_seconds=0.025,
        poll_seconds=0.01,
    )
    clock = _install_clock(monkeypatch)
    calls = _install_graphs(monkeypatch, [[]])

    with pytest.raises(
        SpotifyPipeWireDacResolutionError,
        match="not ready",
    ):
        _resolve(resolver)

    assert len(calls) == 4
    assert clock.sleeps == pytest.approx([0.01, 0.01, 0.005])
    assert sum(clock.sleeps) == pytest.approx(0.025)
    assert max(clock.sleeps) <= resolver._poll_seconds


def test_exact_subprocess_contract_and_environment_copy(tmp_path, monkeypatch):
    resolver = _resolver(tmp_path, command_timeout_seconds=1.25)
    environment = {
        "XDG_RUNTIME_DIR": "/run/private",
        "PIPEWIRE_RUNTIME_DIR": "/run/private",
    }
    original = dict(environment)
    calls = _install_graphs(monkeypatch, [[_sink()]])

    assert _resolve(resolver, environment=environment) == "alsa_output.synthetic"

    command, kwargs = calls[0]
    assert command == [resolver.pw_dump_binary]
    assert kwargs == {
        "check": False,
        "env": environment,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "close_fds": True,
        "shell": False,
        "timeout": 1.25,
    }
    assert kwargs["env"] is not environment
    assert environment == original


def test_nonzero_pw_dump_exit_fails_without_stderr_leak(tmp_path, monkeypatch):
    resolver = _resolver(tmp_path)
    _install_graphs(
        monkeypatch,
        [[]],
        returncode=1,
        stderr=PRIVATE_STDERR,
    )

    with pytest.raises(SpotifyPipeWireDacResolutionError) as raised:
        _resolve(resolver)

    assert PRIVATE_STDERR not in str(raised.value)


def test_pw_dump_timeout_fails_closed(tmp_path, monkeypatch):
    resolver = _resolver(tmp_path, command_timeout_seconds=0.75)
    observed = []

    def timeout(_command, **kwargs):
        observed.append(kwargs["timeout"])
        raise subprocess.TimeoutExpired("pw-dump", kwargs["timeout"])

    monkeypatch.setattr(resolver_module.subprocess, "run", timeout)

    with pytest.raises(SpotifyPipeWireDacResolutionError):
        _resolve(resolver)

    assert observed == [0.75]


def test_process_exception_detail_is_not_exposed(tmp_path, monkeypatch):
    resolver = _resolver(tmp_path)

    def fail(*_args, **_kwargs):
        raise OSError(PRIVATE_VALUE)

    monkeypatch.setattr(resolver_module.subprocess, "run", fail)

    with pytest.raises(SpotifyPipeWireDacResolutionError) as raised:
        _resolve(resolver)

    assert PRIVATE_VALUE not in str(raised.value)


@pytest.mark.parametrize("payload", ["not-json", "{", "null", "{}", '"text"'])
def test_invalid_or_non_list_json_fails_closed(tmp_path, monkeypatch, payload):
    resolver = _resolver(tmp_path)
    _install_graphs(monkeypatch, [payload])

    with pytest.raises(SpotifyPipeWireDacResolutionError):
        _resolve(resolver)


@pytest.mark.parametrize(
    "graph_object",
    [None, "node", {}, {"info": None}, {"info": {}}, {"info": {"props": []}}],
)
def test_malformed_graph_object_fails_immediately(
    tmp_path,
    monkeypatch,
    graph_object,
):
    resolver = _resolver(tmp_path)
    clock = _install_clock(monkeypatch)
    calls = _install_graphs(monkeypatch, [[graph_object]])

    with pytest.raises(SpotifyPipeWireDacResolutionError):
        _resolve(resolver)

    assert len(calls) == 1
    assert clock.sleeps == []


def test_graph_payload_is_not_exposed_in_public_error(tmp_path, monkeypatch):
    resolver = _resolver(tmp_path)
    graph = [_sink(node_name=PRIVATE_GRAPH_VALUE), _sink(node_name="duplicate")]
    _install_graphs(monkeypatch, [graph])

    with pytest.raises(SpotifyPipeWireDacResolutionError) as raised:
        _resolve(resolver)

    assert PRIVATE_GRAPH_VALUE not in str(raised.value)


def test_environment_is_not_exposed_in_public_error(tmp_path, monkeypatch):
    resolver = _resolver(tmp_path)
    _install_graphs(monkeypatch, ["not-json"])

    with pytest.raises(SpotifyPipeWireDacResolutionError) as raised:
        _resolve(resolver, environment={"PRIVATE": PRIVATE_VALUE})

    assert PRIVATE_VALUE not in str(raised.value)


def test_component_has_no_forbidden_architecture_references():
    source = Path(resolver_module.__file__).read_text(encoding="utf-8").lower()
    forbidden = (
        "spotifycoordinator",
        "spotifyruntimesupervisor",
        "spotify_runtime_supervisor",
        "spotifysoloistsupervisor",
        "spotify_soloist_supervisor",
        "spotifysecretstore",
        "main_headless",
        "audioplayer",
        "rust audio",
        "alsa_mmap",
        "native playback",
        "websocket",
        "firewall",
        "ufw",
        "tailscale",
        "http",
        "systemctl",
        "sudo",
        "pkill",
        "killall",
        "os.system",
        "download",
        "import threading",
    )
    assert not any(token in source for token in forbidden)
