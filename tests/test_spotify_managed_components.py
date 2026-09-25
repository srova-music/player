import importlib
import inspect
import os
import subprocess
import sys
import urllib.request
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import main_headless as backend  # noqa: E402
from services import spotify_managed_components as managed_module  # noqa: E402
from services.spotify_paths import SpotifyPaths  # noqa: E402
from services.spotify_soloist_artifact import (  # noqa: E402
    SpotifySoloistArtifactAuthority,
)
from services.spotify_soloist_installer import SpotifySoloistInstaller  # noqa: E402
from services.spotify_soloist_supervisor import (  # noqa: E402
    SpotifySoloistSupervisor,
)


PUBLIC_STATUS_KEYS = {
    "installed",
    "valid",
    "version",
    "build_timestamp",
    "build_date",
    "platform",
    "architecture",
    "expires_at",
    "expired",
    "seconds_remaining",
    "error_code",
}


def _paths():
    return SpotifyPaths(
        spotify_state_dir="/state/spotify",
        spotify_cache_dir="/cache/spotify",
        spotify_runtime_dir="/run/srova/spotify",
        soloist_install_dir="/state/spotify/soloist/install",
        soloist_data_dir="/state/spotify/soloist/data",
        soloist_cache_dir="/cache/spotify/soloist",
    )


def _snapshot(**changes):
    snapshot = {
        "installed": True,
        "valid": True,
        "version": "1.3.8.54",
        "build_timestamp": 1789797673,
        "build_date": "20260919",
        "build_identifier": "SENSITIVE_BUILD_IDENTIFIER",
        "platform": "linux",
        "architecture": "x86_64",
        "sha256": "a" * 64,
        "expires_at": "2026-12-18T15:21:13Z",
        "expired": False,
        "seconds_remaining": 7776000,
        "error_code": "valid",
        "filesystem_path": "/private/managed/soloist",
        "api_key": "SROVA_TEST_ONLY_SECRET_MUST_NOT_ECHO",
    }
    snapshot.update(changes)
    return snapshot


def _get(monkeypatch, path, app):
    handler = object.__new__(backend.ControlHandler)
    handler.path = path
    response = {}

    def send_json(payload, no_store=False):
        response.update(status=200, payload=payload, no_store=no_store)

    def send_error(status, message=None, explain=None):
        response.update(status=status, message=message, explain=explain)

    handler._send_json = send_json
    handler.send_error = send_error
    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    handler.do_GET()
    return response


class _Authority:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = 0

    def status_snapshot(self):
        self.calls += 1
        return self.snapshot


def _forbidden(*_args, **_kwargs):
    raise AssertionError("forbidden side effect")


def test_composition_module_import_is_side_effect_free(monkeypatch):
    monkeypatch.setattr(os, "makedirs", _forbidden)
    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", _forbidden)

    reloaded = importlib.reload(managed_module)

    assert reloaded.__all__ == [
        "SpotifyManagedComponents",
        "build_spotify_managed_components",
    ]


def test_factory_resolves_shared_paths_once_and_injects_exact_object():
    paths = _paths()
    calls = []

    def resolver():
        calls.append("resolve")
        return paths

    def artifact_factory(*, paths):
        calls.append(("artifact", paths))
        return "artifact"

    def installer_factory(*, paths):
        calls.append(("installer", paths))
        return "installer"

    def supervisor_factory(**kwargs):
        calls.append(("supervisor", kwargs))
        return "supervisor"

    composed = managed_module.build_spotify_managed_components(
        path_resolver=resolver,
        artifact_authority_factory=artifact_factory,
        installer_factory=installer_factory,
        soloist_supervisor_factory=supervisor_factory,
    )

    assert calls[0] == "resolve"
    assert calls.count("resolve") == 1
    assert composed.paths is paths
    assert calls[1] == ("artifact", paths)
    assert calls[2] == ("installer", paths)
    assert calls[3] == (
        "supervisor",
        {
            "binary_path": "/state/spotify/soloist/install/soloist",
            "data_dir": paths.soloist_data_dir,
            "cache_dir": paths.soloist_cache_dir,
        },
    )


def test_explicit_paths_bypass_resolver_and_composition_is_immutable():
    paths = _paths()
    composed = managed_module.build_spotify_managed_components(
        paths=paths,
        path_resolver=_forbidden,
    )

    assert composed.paths is paths
    assert isinstance(composed.artifact_authority, SpotifySoloistArtifactAuthority)
    assert isinstance(composed.installer, SpotifySoloistInstaller)
    assert isinstance(composed.soloist_supervisor, SpotifySoloistSupervisor)
    assert composed.artifact_authority._binary_path == (
        "/state/spotify/soloist/install/soloist"
    )
    assert composed.installer._paths is paths
    assert composed.soloist_supervisor._binary_path == (
        "/state/spotify/soloist/install/soloist"
    )
    assert composed.soloist_supervisor.data_dir == paths.soloist_data_dir
    assert composed.soloist_supervisor.cache_dir == paths.soloist_cache_dir
    with pytest.raises(FrozenInstanceError):
        composed.paths = _paths()


def test_factory_construction_does_not_activate_components(monkeypatch):
    monkeypatch.setattr(
        SpotifySoloistArtifactAuthority,
        "inspect_installed",
        _forbidden,
    )
    monkeypatch.setattr(
        SpotifySoloistArtifactAuthority,
        "status_snapshot",
        _forbidden,
    )
    monkeypatch.setattr(
        SpotifySoloistInstaller,
        "install_or_update",
        _forbidden,
    )
    monkeypatch.setattr(SpotifySoloistSupervisor, "start", _forbidden)
    monkeypatch.setattr(os, "makedirs", _forbidden)
    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", _forbidden)

    composed = managed_module.build_spotify_managed_components(paths=_paths())

    assert isinstance(composed.artifact_authority, SpotifySoloistArtifactAuthority)
    assert isinstance(composed.installer, SpotifySoloistInstaller)
    assert isinstance(composed.soloist_supervisor, SpotifySoloistSupervisor)


def test_composition_has_no_secret_or_runtime_graph_dependencies():
    source = Path(managed_module.__file__).read_text(encoding="utf-8")

    for forbidden_name in (
        "SpotifySecretStore",
        "SpotifyRuntimeSupervisor",
        "SpotifyPipeWireDacResolver",
        "SpotifySoloistEventObserver",
        "SpotifyAlsaPcmVerifier",
        "SpotifyOrchestrator",
        "install_or_update(",
        "inspect_installed(",
        "status_snapshot(",
        ".start(",
        ".enable(",
        "prepare_native_claim(",
    ):
        assert forbidden_name not in source


def test_headless_app_owns_one_dormant_managed_root(monkeypatch):
    import services.spotify_orchestrator as orchestrator_module

    monkeypatch.setattr(
        SpotifySoloistArtifactAuthority,
        "status_snapshot",
        _forbidden,
    )
    monkeypatch.setattr(
        SpotifySoloistInstaller,
        "install_or_update",
        _forbidden,
    )
    monkeypatch.setattr(SpotifySoloistSupervisor, "start", _forbidden)
    monkeypatch.setattr(
        orchestrator_module.SpotifyOrchestrator,
        "__init__",
        _forbidden,
    )
    monkeypatch.setattr(urllib.request, "urlopen", _forbidden)

    app = backend.HeadlessApp()

    assert isinstance(
        app.spotify_managed,
        managed_module.SpotifyManagedComponents,
    )
    assert list(vars(app)).count("spotify_managed") == 1


def test_main_does_not_construct_orchestrator_or_second_installer():
    source = Path(backend.__file__).read_text(encoding="utf-8")

    assert "SpotifyOrchestrator(" not in source
    assert "SpotifySoloistInstaller(" not in source
    assert source.count("installer.install_or_update()") == 1
    assert "prepare_native_claim(" not in source


def test_artifact_status_returns_exact_sanitized_valid_contract(monkeypatch):
    authority = _Authority(_snapshot())
    app = SimpleNamespace(
        spotify_managed=SimpleNamespace(artifact_authority=authority),
    )

    response = _get(monkeypatch, "/api/spotify/artifact/status", app)

    assert response["status"] == 200
    assert response["no_store"] is True
    assert set(response["payload"]) == PUBLIC_STATUS_KEYS
    assert response["payload"] == {
        "installed": True,
        "valid": True,
        "version": "1.3.8.54",
        "build_timestamp": 1789797673,
        "build_date": "20260919",
        "platform": "linux",
        "architecture": "x86_64",
        "expires_at": "2026-12-18T15:21:13Z",
        "expired": False,
        "seconds_remaining": 7776000,
        "error_code": "valid",
    }
    serialized = repr(response["payload"])
    assert "sha256" not in response["payload"]
    assert "build_identifier" not in response["payload"]
    assert "/private/managed/soloist" not in serialized
    assert "SROVA_TEST_ONLY_SECRET_MUST_NOT_ECHO" not in serialized
    assert authority.calls == 1


@pytest.mark.parametrize(
    "snapshot",
    [
        _snapshot(
            installed=False,
            valid=False,
            version=None,
            build_timestamp=None,
            build_date=None,
            build_identifier=None,
            platform=None,
            architecture=None,
            sha256=None,
            expires_at=None,
            expired=None,
            seconds_remaining=None,
            error_code="not_installed",
        ),
        _snapshot(
            valid=False,
            expired=True,
            seconds_remaining=0,
            error_code="expired",
        ),
        _snapshot(
            valid=False,
            version=None,
            build_timestamp=None,
            build_date=None,
            build_identifier=None,
            platform=None,
            architecture=None,
            sha256=None,
            expires_at=None,
            expired=None,
            seconds_remaining=None,
            error_code="invalid_file",
        ),
    ],
    ids=["not-installed", "expired", "invalid"],
)
def test_controlled_nonvalid_artifact_statuses_return_200(monkeypatch, snapshot):
    app = SimpleNamespace(
        spotify_managed=SimpleNamespace(
            artifact_authority=_Authority(snapshot),
        ),
    )

    response = _get(monkeypatch, "/api/spotify/artifact/status", app)

    assert response["status"] == 200
    assert response["no_store"] is True
    assert set(response["payload"]) == PUBLIC_STATUS_KEYS
    assert response["payload"]["error_code"] == snapshot["error_code"]


@pytest.mark.parametrize(
    "snapshot",
    [
        None,
        {},
        _snapshot(installed="yes"),
        _snapshot(build_timestamp=True),
        _snapshot(error_code="private_internal_error"),
    ],
)
def test_invalid_internal_artifact_contract_fails_safe(monkeypatch, snapshot):
    app = SimpleNamespace(
        spotify_managed=SimpleNamespace(
            artifact_authority=_Authority(snapshot),
        ),
    )

    response = _get(monkeypatch, "/api/spotify/artifact/status", app)

    assert response["status"] == 503
    assert "payload" not in response
    assert "private_internal_error" not in repr(response)


def test_artifact_authority_exception_fails_safe(monkeypatch):
    class BrokenAuthority:
        def status_snapshot(self):
            raise RuntimeError("SROVA_TEST_ONLY_PRIVATE_FAILURE")

    app = SimpleNamespace(
        spotify_managed=SimpleNamespace(
            artifact_authority=BrokenAuthority(),
        ),
    )

    response = _get(monkeypatch, "/api/spotify/artifact/status", app)

    assert response["status"] == 503
    assert "payload" not in response
    assert "SROVA_TEST_ONLY_PRIVATE_FAILURE" not in repr(response)


@pytest.mark.parametrize(
    "app",
    [SimpleNamespace(), SimpleNamespace(spotify_managed=None)],
)
def test_missing_artifact_authority_fails_safe(monkeypatch, app):
    response = _get(monkeypatch, "/api/spotify/artifact/status", app)

    assert response["status"] == 503
    assert "payload" not in response


def test_artifact_status_query_string_is_not_routed(monkeypatch):
    authority = _Authority(_snapshot())
    app = SimpleNamespace(
        spotify_managed=SimpleNamespace(artifact_authority=authority),
    )

    response = _get(
        monkeypatch,
        "/api/spotify/artifact/status?inspect=true",
        app,
    )

    assert response["status"] == 404
    assert "payload" not in response
    assert authority.calls == 0


def test_artifact_status_never_invokes_installer_or_supervisor(monkeypatch):
    authority = _Authority(_snapshot())
    managed = SimpleNamespace(
        artifact_authority=authority,
        installer=SimpleNamespace(install_or_update=_forbidden),
        soloist_supervisor=SimpleNamespace(start=_forbidden),
    )

    response = _get(
        monkeypatch,
        "/api/spotify/artifact/status",
        SimpleNamespace(spotify_managed=managed),
    )

    assert response["status"] == 200
    assert authority.calls == 1


def test_existing_spotify_status_contract_is_unchanged(monkeypatch):
    coordinator = SimpleNamespace(
        status_snapshot=lambda: {
            "state": "disabled",
            "spotify_owner": False,
            "native_blocked": False,
        },
    )
    secret_store = SimpleNamespace(key_configured=lambda: True)
    app = SimpleNamespace(
        spotify_coordinator=coordinator,
        spotify_secret_store=secret_store,
        spotify_managed=SimpleNamespace(artifact_authority=_forbidden),
    )

    response = _get(monkeypatch, "/api/spotify/status", app)

    assert response == {
        "status": 200,
        "payload": {
            "state": "disabled",
            "spotify_owner": False,
            "native_blocked": False,
            "key_configured": True,
            "enabled": False,
        },
        "no_store": True,
    }


def test_exact_artifact_update_http_route_uses_only_managed_installer():
    post_source = inspect.getsource(backend.ControlHandler.do_POST)

    assert post_source.count(
        'spotify_artifact_update_path == "/api/spotify/artifact/update"'
    ) == 1
    assert post_source.count("installer.install_or_update()") == 1
    assert 'getattr(APP_INSTANCE, "spotify_managed", None)' in post_source
    assert "SpotifySoloistInstaller(" not in post_source
    assert "/api/spotify/runtime/status" not in post_source
