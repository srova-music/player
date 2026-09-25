import ast
import inspect
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from types import SimpleNamespace

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import main_headless as backend  # noqa: E402
from services import spotify_runtime_components as runtime_module  # noqa: E402
from services.spotify_endpoint_lifecycle import SpotifyEndpointLifecycle  # noqa: E402
from services.spotify_endpoint_network_access import (  # noqa: E402
    SpotifyEndpointNetworkAccess,
)
from services.spotify_firewall_manager import SpotifyFirewallManager  # noqa: E402
from services.spotify_alsa_pcm_verifier import SpotifyAlsaPcmVerifier  # noqa: E402
from services.spotify_lan_network_resolver import SpotifyLanNetworkResolver  # noqa: E402
from services.spotify_paths import SpotifyPaths  # noqa: E402
from services.spotify_pipewire_dac_resolver import (  # noqa: E402
    SpotifyPipeWireDacResolver,
)
from services.spotify_pipewire_prearm import SpotifyPipeWirePrearm  # noqa: E402
from services.spotify_runtime_supervisor import (  # noqa: E402
    SpotifyRuntimeSupervisor,
)
from services.spotify_soloist_event_observer import (  # noqa: E402
    SpotifySoloistEventObserver,
)
from services.spotify_soloist_supervisor import SpotifySoloistSupervisor  # noqa: E402
from services.spotify_soloist_listener_resolver import (  # noqa: E402
    SpotifySoloistLanListenerResolver,
)


def _forbidden(*_args, **_kwargs):
    raise AssertionError("forbidden side effect")


def _paths():
    return SpotifyPaths(
        spotify_state_dir="/state/spotify",
        spotify_cache_dir="/cache/spotify",
        spotify_runtime_dir="/run/srova/spotify",
        soloist_install_dir="/state/spotify/soloist/install",
        soloist_data_dir="/state/spotify/soloist/data",
        soloist_cache_dir="/cache/spotify/soloist",
    )


def _managed(paths=None, soloist_supervisor=None):
    return SimpleNamespace(
        paths=paths or _paths(),
        soloist_supervisor=(
            soloist_supervisor
            if soloist_supervisor is not None
            else object()
        ),
    )


def _runtime(**changes):
    values = {
        "runtime_supervisor": object(),
        "dac_resolver": object(),
        "pipewire_prearm": object(),
        "observer": object(),
        "pcm_verifier": object(),
        "firewall_manager": object(),
        "lan_network_resolver": object(),
        "listener_resolver": object(),
        "endpoint_network_access": object(),
    }
    values.update(changes)
    return runtime_module.SpotifyRuntimeComponents(**values)


def _app():
    return SimpleNamespace(
        spotify_coordinator=SimpleNamespace(state="unchanged"),
        spotify_secret_store=object(),
        spotify_managed=_managed(),
        spotify_runtime=_runtime(),
        spotify_orchestrator=None,
        spotify_orchestrator_binding=None,
    )


def test_module_has_no_import_time_component_construction():
    tree = ast.parse(
        Path(runtime_module.__file__).read_text(encoding="utf-8"),
    )
    top_level_calls = [
        node
        for statement in tree.body
        for node in ast.walk(statement)
        if isinstance(node, ast.Call)
        and not isinstance(statement, (ast.ClassDef, ast.FunctionDef))
    ]

    assert top_level_calls == []


def test_runtime_factory_uses_exact_paths_and_never_rebuilds_soloist():
    paths = _paths()
    soloist = object()
    managed = _managed(paths, soloist)
    calls = []

    def runtime_factory(**kwargs):
        calls.append(("runtime", kwargs))
        return "runtime"

    def resolver_factory(**kwargs):
        calls.append(("resolver", kwargs))
        return "resolver"

    def prearm_factory(**kwargs):
        calls.append(("prearm", kwargs))
        return "prearm"

    def observer_factory(**kwargs):
        calls.append(("observer", kwargs))
        return "observer"

    def verifier_factory(**kwargs):
        calls.append(("verifier", kwargs))
        return "verifier"

    def firewall_factory(**kwargs):
        calls.append(("firewall", kwargs))
        return "firewall"

    def lan_factory(**kwargs):
        calls.append(("lan", kwargs))
        return "lan"

    def listener_factory(**kwargs):
        calls.append(("listener", kwargs))
        return "listener"

    def network_access_factory(**kwargs):
        calls.append(("network_access", kwargs))
        return "network_access"

    composed = runtime_module.build_spotify_runtime_components(
        paths=paths,
        managed=managed,
        runtime_supervisor_factory=runtime_factory,
        dac_resolver_factory=resolver_factory,
        pipewire_prearm_factory=prearm_factory,
        observer_factory=observer_factory,
        pcm_verifier_factory=verifier_factory,
        firewall_manager_factory=firewall_factory,
        lan_network_resolver_factory=lan_factory,
        listener_resolver_factory=listener_factory,
        endpoint_network_access_factory=network_access_factory,
    )

    assert calls == [
        ("runtime", {"runtime_dir": paths.spotify_runtime_dir}),
        ("resolver", {}),
        ("prearm", {}),
        (
            "observer",
            {"binary_path": "/state/spotify/soloist/install/soloist"},
        ),
        ("verifier", {}),
        ("firewall", {}),
        ("lan", {}),
        ("listener", {}),
        (
            "network_access",
            {
                "firewall_manager": "firewall",
                "lan_network_resolver": "lan",
                "listener_resolver": "listener",
                "soloist_supervisor": soloist,
            },
        ),
    ]
    assert [field.name for field in fields(composed)] == [
        "runtime_supervisor",
        "dac_resolver",
        "pipewire_prearm",
        "observer",
        "pcm_verifier",
        "firewall_manager",
        "lan_network_resolver",
        "listener_resolver",
        "endpoint_network_access",
    ]
    assert managed.soloist_supervisor is soloist


def test_production_runtime_factory_is_dormant(monkeypatch):
    paths = _paths()
    managed = _managed(paths)
    monkeypatch.setattr(SpotifyRuntimeSupervisor, "start_private_graph", _forbidden)
    monkeypatch.setattr(SpotifyPipeWireDacResolver, "resolve", _forbidden)
    monkeypatch.setattr(SpotifyPipeWirePrearm, "prearm", _forbidden)
    monkeypatch.setattr(SpotifySoloistEventObserver, "start", _forbidden)
    monkeypatch.setattr(SpotifyAlsaPcmVerifier, "is_free", _forbidden)
    monkeypatch.setattr(SpotifyAlsaPcmVerifier, "wait_until_free", _forbidden)
    monkeypatch.setattr(SpotifyFirewallManager, "inspect", _forbidden)
    monkeypatch.setattr(SpotifyLanNetworkResolver, "resolve", _forbidden)
    monkeypatch.setattr(SpotifySoloistLanListenerResolver, "resolve", _forbidden)
    monkeypatch.setattr(SpotifyEndpointNetworkAccess, "preflight", _forbidden)
    monkeypatch.setattr(SpotifySoloistSupervisor, "__init__", _forbidden)
    monkeypatch.setattr(os, "makedirs", _forbidden)
    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)

    composed = runtime_module.build_spotify_runtime_components(
        paths=paths,
        managed=managed,
    )

    assert isinstance(composed.runtime_supervisor, SpotifyRuntimeSupervisor)
    assert composed.runtime_supervisor.runtime_dir == paths.spotify_runtime_dir
    assert isinstance(composed.dac_resolver, SpotifyPipeWireDacResolver)
    assert isinstance(composed.pipewire_prearm, SpotifyPipeWirePrearm)
    assert isinstance(composed.observer, SpotifySoloistEventObserver)
    assert composed.observer._binary_path == (
        "/state/spotify/soloist/install/soloist"
    )
    assert isinstance(composed.pcm_verifier, SpotifyAlsaPcmVerifier)
    assert isinstance(composed.firewall_manager, SpotifyFirewallManager)
    assert isinstance(composed.lan_network_resolver, SpotifyLanNetworkResolver)
    assert isinstance(
        composed.listener_resolver,
        SpotifySoloistLanListenerResolver,
    )
    assert isinstance(
        composed.endpoint_network_access,
        SpotifyEndpointNetworkAccess,
    )
    assert composed.endpoint_network_access._firewall_manager is composed.firewall_manager
    assert composed.endpoint_network_access._lan_network_resolver is composed.lan_network_resolver
    assert composed.endpoint_network_access._listener_resolver is composed.listener_resolver
    assert composed.endpoint_network_access._soloist_supervisor is managed.soloist_supervisor


def test_runtime_factory_requires_shared_path_authority():
    with pytest.raises(runtime_module.SpotifyRuntimeCompositionError):
        runtime_module.build_spotify_runtime_components(
            paths=_paths(),
            managed=_managed(_paths()),
        )


def test_runtime_composition_is_frozen():
    composed = _runtime()

    with pytest.raises(FrozenInstanceError):
        composed.observer = object()


def test_runtime_factory_has_no_secret_network_or_activation_calls():
    source = inspect.getsource(
        runtime_module.build_spotify_runtime_components,
    )

    for forbidden_name in (
        "secret_store",
        "urlopen",
        "requests",
        "install_or_update",
        "start_private_graph",
        ".start(",
        ".resolve(",
        ".is_free(",
        ".wait_until_free(",
    ):
        assert forbidden_name not in source


@pytest.mark.parametrize(
    ("card_number", "device_number"),
    [(0, 0), (3, 2)],
)
def test_output_binding_contains_only_physical_identity(
    card_number,
    device_number,
):
    binding = runtime_module.SpotifyOutputBinding(
        card_number=card_number,
        device_number=device_number,
    )

    assert binding.card_number == card_number
    assert binding.device_number == device_number
    assert tuple(field.name for field in fields(binding)) == (
        "card_number",
        "device_number",
    )


def test_output_binding_detects_real_physical_change():
    assert runtime_module.SpotifyOutputBinding(
        0,
        0,
    ) != runtime_module.SpotifyOutputBinding(1, 0)


@pytest.mark.parametrize(
    ("card_number", "device_number"),
    [(True, 0), (0, False)],
)
def test_output_binding_rejects_bool_numbers(card_number, device_number):
    with pytest.raises(runtime_module.SpotifyRuntimeCompositionError):
        runtime_module.SpotifyOutputBinding(
            card_number=card_number,
            device_number=device_number,
        )


@pytest.mark.parametrize(
    ("card_number", "device_number"),
    [(-1, 0), (0, -1)],
)
def test_output_binding_rejects_negative_numbers(card_number, device_number):
    with pytest.raises(runtime_module.SpotifyRuntimeCompositionError):
        runtime_module.SpotifyOutputBinding(
            card_number=card_number,
            device_number=device_number,
        )


def test_output_binding_is_frozen():
    binding = runtime_module.SpotifyOutputBinding(0, 0)

    with pytest.raises(FrozenInstanceError):
        binding.card_number = 1


@pytest.mark.parametrize("device_name", ["", " ", "\tDAC", "DAC\n"])
def test_orchestrator_builder_rejects_uncontrolled_presentation_name(
    device_name,
):
    with pytest.raises(runtime_module.SpotifyRuntimeCompositionError):
        runtime_module.build_spotify_orchestrator(
            binding=runtime_module.SpotifyOutputBinding(0, 0),
            device_name=device_name,
            coordinator=object(),
            secret_store=object(),
            managed=_managed(),
            runtime=_runtime(),
            orchestrator_factory=_forbidden,
        )


def test_orchestrator_factory_reuses_every_exact_dependency():
    binding = runtime_module.SpotifyOutputBinding(3, 2)
    coordinator = object()
    secret_store = object()
    soloist = object()
    managed = _managed(soloist_supervisor=soloist)
    runtime = _runtime()
    captured = []
    sentinel = object()

    def factory(**kwargs):
        captured.append(kwargs)
        return sentinel

    result = runtime_module.build_spotify_orchestrator(
        binding=binding,
        device_name="Living Room",
        coordinator=coordinator,
        secret_store=secret_store,
        managed=managed,
        runtime=runtime,
        orchestrator_factory=factory,
    )

    assert result is sentinel
    assert captured == [{
        "coordinator": coordinator,
        "secret_store": secret_store,
        "runtime_supervisor": runtime.runtime_supervisor,
        "dac_resolver": runtime.dac_resolver,
        "pipewire_prearm": runtime.pipewire_prearm,
        "soloist_supervisor": soloist,
        "observer": runtime.observer,
        "pcm_verifier": runtime.pcm_verifier,
        "card_number": 3,
        "device_number": 2,
        "device_name": "Living Room",
    }]


def test_orchestrator_factory_invokes_no_lifecycle_method():
    class DormantOrchestrator:
        enable = _forbidden
        disable = _forbidden
        reconcile = _forbidden
        prepare_native_claim = _forbidden

    result = runtime_module.build_spotify_orchestrator(
        binding=runtime_module.SpotifyOutputBinding(0, 0),
        device_name="DAC",
        coordinator=object(),
        secret_store=object(),
        managed=_managed(),
        runtime=_runtime(),
        orchestrator_factory=lambda **_kwargs: DormantOrchestrator(),
    )

    assert isinstance(result, DormantOrchestrator)


def test_production_orchestrator_construction_is_dormant_and_secret_blind():
    class UnreadableSecret:
        def __getattribute__(self, _name):
            raise AssertionError("secret store was read during construction")

    binding = runtime_module.SpotifyOutputBinding(1, 2)
    coordinator = object()
    secret_store = UnreadableSecret()
    soloist = object()
    runtime = _runtime()

    orchestrator = runtime_module.build_spotify_orchestrator(
        binding=binding,
        device_name="DAC",
        coordinator=coordinator,
        secret_store=secret_store,
        managed=_managed(soloist_supervisor=soloist),
        runtime=runtime,
    )

    assert orchestrator._coordinator is coordinator
    assert orchestrator._secret_store is secret_store
    assert orchestrator._soloist_supervisor is soloist
    assert orchestrator._runtime_supervisor is runtime.runtime_supervisor
    assert orchestrator._dac_resolver is runtime.dac_resolver
    assert orchestrator._pipewire_prearm is runtime.pipewire_prearm
    assert orchestrator._observer is runtime.observer
    assert orchestrator._pcm_verifier is runtime.pcm_verifier
    assert orchestrator._phase == "disabled"


def test_endpoint_lifecycle_builder_wraps_exact_inner_and_network_authority():
    binding = runtime_module.SpotifyOutputBinding(1, 2)
    runtime = _runtime()
    inner = object()
    captured = []
    lifecycle = object()

    result = runtime_module.build_spotify_endpoint_lifecycle(
        binding=binding,
        device_name="DAC",
        coordinator=object(),
        secret_store=object(),
        managed=_managed(),
        runtime=runtime,
        orchestrator_factory=lambda **_kwargs: inner,
        lifecycle_factory=lambda **kwargs: captured.append(kwargs) or lifecycle,
    )

    assert result is lifecycle
    assert captured == [{
        "orchestrator": inner,
        "network_access": runtime.endpoint_network_access,
    }]


def test_production_endpoint_lifecycle_construction_is_dormant():
    runtime = _runtime()
    lifecycle = runtime_module.build_spotify_endpoint_lifecycle(
        binding=runtime_module.SpotifyOutputBinding(0, 0),
        device_name="DAC",
        coordinator=object(),
        secret_store=object(),
        managed=_managed(),
        runtime=runtime,
    )

    assert isinstance(lifecycle, SpotifyEndpointLifecycle)
    assert lifecycle._network_access is runtime.endpoint_network_access


def test_headless_app_owns_dormant_runtime_without_orchestrator(monkeypatch):
    import services.spotify_orchestrator as orchestrator_module

    monkeypatch.setattr(orchestrator_module.SpotifyOrchestrator, "__init__", _forbidden)
    monkeypatch.setattr(SpotifyRuntimeSupervisor, "start_private_graph", _forbidden)
    monkeypatch.setattr(SpotifySoloistEventObserver, "start", _forbidden)
    monkeypatch.setattr(os, "makedirs", _forbidden)
    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)

    app = backend.HeadlessApp()

    assert isinstance(
        app.spotify_runtime,
        runtime_module.SpotifyRuntimeComponents,
    )
    assert app.spotify_orchestrator is None
    assert app.spotify_orchestrator_binding is None


@pytest.mark.parametrize(
    ("device", "card_number", "device_number"),
    [("hw:0,0", 0, 0), ("plughw:3,2", 3, 2)],
)
def test_current_output_binding_parses_selected_device(
    monkeypatch,
    device,
    card_number,
    device_number,
):
    monkeypatch.setattr(backend, "ALSA_DEVICE", device)
    monkeypatch.setattr(backend, "ALSA_DAC_NAME", "Selected DAC")

    binding = backend._spotify_current_output_binding()

    assert binding == runtime_module.SpotifyOutputBinding(
        card_number,
        device_number,
    )


def test_current_output_binding_ignores_presentation_text(monkeypatch):
    monkeypatch.setattr(backend, "ALSA_DEVICE", "plughw:3,2")
    monkeypatch.setattr(backend, "ALSA_DAC_NAME", "Physical DAC")

    binding = backend._spotify_current_output_binding()

    assert binding == runtime_module.SpotifyOutputBinding(3, 2)


@pytest.mark.parametrize("device", ["", "default", "hw:1", "hw:x,1"])
def test_current_output_binding_rejects_malformed_device(monkeypatch, device):
    monkeypatch.setattr(backend, "ALSA_DEVICE", device)
    monkeypatch.setattr(backend, "ALSA_DAC_NAME", "DAC")

    with pytest.raises(runtime_module.SpotifyRuntimeCompositionError):
        backend._spotify_current_output_binding()


def test_current_output_binding_reads_under_audio_lock(monkeypatch):
    class TracingLock:
        entered = False
        completed = False

        def __enter__(self):
            self.entered = True

        def __exit__(self, *_args):
            self.entered = False
            self.completed = True

    lock = TracingLock()

    def parse_while_locked(device):
        assert lock.entered is True
        assert device == "hw:4,5"
        return "4", "5"

    monkeypatch.setattr(backend, "_AUDIO_OUTPUT_LOCK", lock)
    monkeypatch.setattr(backend, "_alsa_device_numbers", parse_while_locked)
    monkeypatch.setattr(backend, "ALSA_DEVICE", "hw:4,5")
    monkeypatch.setattr(backend, "ALSA_DAC_NAME", "Locked DAC")

    binding = backend._spotify_current_output_binding()

    assert lock.completed is True
    assert binding == runtime_module.SpotifyOutputBinding(4, 5)


def test_lazy_helper_builds_once_stores_binding_and_reuses(monkeypatch):
    app = _app()
    binding = runtime_module.SpotifyOutputBinding(0, 0)
    orchestrator = object()
    calls = []
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(backend, "ALSA_DAC_NAME", "Default")
    monkeypatch.setattr(backend, "ALSA_DEVICE", "hw:0,0")
    monkeypatch.setattr(backend, "_AUDIO_OUTPUT_SELECTED", True)
    monkeypatch.setattr(
        backend,
        "_spotify_current_output_binding",
        lambda: binding,
    )

    def build(**kwargs):
        calls.append(kwargs)
        return orchestrator

    monkeypatch.setattr(backend, "build_spotify_endpoint_lifecycle", build)

    first = backend._spotify_orchestrator_for_current_output()
    second = backend._spotify_orchestrator_for_current_output()

    assert first is orchestrator
    assert second is orchestrator
    assert len(calls) == 1
    assert calls[0] == {
        "binding": binding,
        "device_name": "Default",
        "coordinator": app.spotify_coordinator,
        "secret_store": app.spotify_secret_store,
        "managed": app.spotify_managed,
        "runtime": app.spotify_runtime,
    }
    assert app.spotify_orchestrator is orchestrator
    assert app.spotify_orchestrator_binding is binding


def test_lazy_helper_changed_binding_fails_without_retarget(monkeypatch):
    app = _app()
    old_binding = runtime_module.SpotifyOutputBinding(0, 0)
    new_binding = runtime_module.SpotifyOutputBinding(3, 2)

    class ExistingOrchestrator:
        disable = _forbidden
        enable = _forbidden
        reconcile = _forbidden
        prepare_native_claim = _forbidden

    existing = ExistingOrchestrator()
    app.spotify_orchestrator = existing
    app.spotify_orchestrator_binding = old_binding
    coordinator_state = app.spotify_coordinator.state
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(
        backend,
        "_spotify_current_output_binding",
        lambda: new_binding,
    )
    monkeypatch.setattr(backend, "build_spotify_endpoint_lifecycle", _forbidden)

    with pytest.raises(runtime_module.SpotifyRuntimeCompositionError):
        backend._spotify_orchestrator_for_current_output()

    assert app.spotify_orchestrator is existing
    assert app.spotify_orchestrator_binding is old_binding
    assert app.spotify_coordinator.state == coordinator_state


def test_lazy_helper_unavailable_app_fails_closed(monkeypatch):
    monkeypatch.setattr(backend, "APP_INSTANCE", None)
    monkeypatch.setattr(backend, "build_spotify_endpoint_lifecycle", _forbidden)

    with pytest.raises(runtime_module.SpotifyRuntimeCompositionError):
        backend._spotify_orchestrator_for_current_output()


def test_lazy_helper_rejects_inconsistent_saved_state(monkeypatch):
    app = _app()
    app.spotify_orchestrator_binding = runtime_module.SpotifyOutputBinding(
        0,
        0,
    )
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(
        backend,
        "_spotify_current_output_binding",
        lambda: app.spotify_orchestrator_binding,
    )
    monkeypatch.setattr(backend, "build_spotify_endpoint_lifecycle", _forbidden)

    with pytest.raises(runtime_module.SpotifyRuntimeCompositionError):
        backend._spotify_orchestrator_for_current_output()


def test_lazy_helper_is_wired_only_to_post_control():
    assert "_spotify_orchestrator_for_current_output" not in inspect.getsource(
        backend.ControlHandler.do_GET,
    )
    assert inspect.getsource(backend.ControlHandler.do_POST).count(
        "_spotify_orchestrator_for_current_output"
    ) == 1


def test_static_locked_boundaries_allow_only_managed_artifact_update_route():
    completed = subprocess.run(
        ["git", "diff", "-U0", "--", "src/main_headless.py"],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    diff = completed.stdout
    added_lines = [
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    added = "\n".join(added_lines)

    for forbidden_name in (
        "/api/spotify/runtime/status",
        "def _install_native_audio_guard",
        "def _require_audio_output_for_playback",
        "def configure_audio",
        "def _configure_audio_when_ready",
        '"/tidal/dac/exclusive"',
    ):
        assert forbidden_name not in diff

    main_source = Path(backend.__file__).read_text(encoding="utf-8")
    post_source = inspect.getsource(backend.ControlHandler.do_POST)
    assert post_source.count(
        'spotify_artifact_update_path == "/api/spotify/artifact/update"'
    ) == 1
    assert post_source.count("installer.install_or_update()") == 1
    assert "SpotifySoloistInstaller(" not in added
    assert "build_spotify_managed_components(" not in added
    assert main_source.count('getattr(orchestrator, "prepare_native_claim")') == 1
    assert added.count('getattr(orchestrator, "prepare_native_claim")') in (0, 1)
    assert added.count("_spotify_orchestrator_for_current_output(") == 2
    assert inspect.getsource(
        backend._reconcile_existing_spotify_endpoint
    ).count("_spotify_orchestrator_for_current_output(") == 1
    assert inspect.getsource(
        backend.ControlHandler.do_POST
    ).count("_spotify_orchestrator_for_current_output(") == 1
    assert "build_spotify_orchestrator(" not in added

    rust_diff = subprocess.run(
        ["git", "diff", "--", "src/_rust/audio.py"],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    assert rust_diff.stdout == ""
