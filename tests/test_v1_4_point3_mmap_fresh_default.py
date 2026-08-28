import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import main_headless as backend


MAIN_SOURCE = (ROOT / "src/main_headless.py").read_text(encoding="utf-8")
UI_SOURCE = (ROOT / "src/ui_web/ui.js").read_text(encoding="utf-8")
PACKAGE_SOURCE = (ROOT / "package.sh").read_text(encoding="utf-8")
ARM64_PACKAGE_SOURCE = (
    ROOT / "packaging/arm64/build_deb.sh"
).read_text(encoding="utf-8")


@pytest.fixture
def isolated_audio_output(tmp_path, monkeypatch):
    preference = tmp_path / "home" / ".config" / "hiresti" / "audio_output.json"
    monkeypatch.setattr(backend, "_AUDIO_OUTPUT_FILE", str(preference))
    monkeypatch.setattr(backend, "ALSA_DRIVER", "alsa_mmap")
    monkeypatch.setattr(backend, "ALSA_DEVICE", "hw:0,0")
    monkeypatch.setattr(backend, "ALSA_DAC_NAME", "")
    monkeypatch.setattr(backend, "APP_INSTANCE", None)
    monkeypatch.delenv("SROVA_FORCE_CLI_AUDIO", raising=False)
    return preference


def _write_preference(path, **values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values), encoding="utf-8")


def _run_main_to_loop(monkeypatch, arguments):
    player = SimpleNamespace()
    app = SimpleNamespace(
        player=player,
        backend=SimpleNamespace(try_load_session=lambda: None),
    )

    monkeypatch.setattr(backend, "setup_logging", lambda: None)
    monkeypatch.setattr(
        backend,
        "_migrate_legacy_network_root_state",
        lambda: {"status": "not-needed", "changed": False, "pending_roots": []},
    )
    monkeypatch.setattr(backend, "_load_srova_env_port", lambda: None)
    monkeypatch.setattr(
        backend,
        "_resolve_dac_name",
        lambda device=None: str(device or backend.ALSA_DEVICE),
    )
    monkeypatch.setattr(backend, "HeadlessApp", lambda: app)
    monkeypatch.setattr(backend.app_init_runtime, "init_runtime", lambda _app: None)
    monkeypatch.setattr(backend, "load_queue", lambda: None)
    monkeypatch.setattr(backend, "_reset_startup_playback_state", lambda: None)
    monkeypatch.setattr(backend, "_load_app_settings", lambda: None)
    monkeypatch.setattr(backend, "_load_scrobble_creds", lambda: None)
    monkeypatch.setattr(backend, "_load_meta_cache", lambda: None)
    monkeypatch.setattr(backend, "install_eos_hook", lambda: None)
    monkeypatch.setattr(backend, "start_http", lambda: None)
    monkeypatch.setattr(
        backend,
        "GLib",
        SimpleNamespace(
            timeout_add=lambda *_args, **_kwargs: 0,
            MainLoop=lambda: SimpleNamespace(run=lambda: None),
        ),
    )
    monkeypatch.setattr(sys, "argv", ["main_headless.py", *arguments])

    backend.main()
    return app


def test_no_preference_uses_mmap_without_creating_preference(
    isolated_audio_output, monkeypatch
):
    assert 'ALSA_DRIVER = "alsa_mmap"' in MAIN_SOURCE
    assert 'ALSA_DRIVER = "ALSA"' not in MAIN_SOURCE
    assert not isolated_audio_output.exists()

    _run_main_to_loop(monkeypatch, [])

    assert backend.ALSA_DRIVER == "alsa_mmap"
    assert backend.ALSA_DEVICE == "hw:0,0"
    assert not isolated_audio_output.exists()


def test_valid_saved_alsa_overrides_new_default(
    isolated_audio_output, monkeypatch
):
    _write_preference(
        isolated_audio_output,
        alsa_driver="ALSA",
        alsa_device="hw:2,0",
        dac_name="Saved ALSA DAC",
    )

    _run_main_to_loop(monkeypatch, ["--alsa-driver", "alsa_mmap"])

    assert backend.ALSA_DRIVER == "ALSA"
    assert backend.ALSA_DEVICE == "hw:2,0"
    assert backend.ALSA_DAC_NAME == "Saved ALSA DAC"


def test_valid_saved_mmap_remains_mmap(isolated_audio_output, monkeypatch):
    _write_preference(
        isolated_audio_output,
        alsa_driver="alsa_mmap",
        alsa_device="hw:3,1",
        dac_name="Saved mmap DAC",
    )

    _run_main_to_loop(monkeypatch, ["--alsa-driver", "ALSA"])

    assert backend.ALSA_DRIVER == "alsa_mmap"
    assert backend.ALSA_DEVICE == "hw:3,1"
    assert backend.ALSA_DAC_NAME == "Saved mmap DAC"


def test_older_preference_without_driver_inherits_mmap_and_retains_device(
    isolated_audio_output,
):
    _write_preference(
        isolated_audio_output,
        alsa_device="plughw:4,0",
        dac_name="Legacy DAC",
    )

    assert backend._load_audio_output_config() is True
    assert backend.ALSA_DRIVER == "alsa_mmap"
    assert backend.ALSA_DEVICE == "plughw:4,0"
    assert backend.ALSA_DAC_NAME == "Legacy DAC"


def test_unforced_cli_alsa_still_applies_without_saved_preference(
    isolated_audio_output, monkeypatch
):
    _run_main_to_loop(
        monkeypatch,
        ["--alsa-driver", "ALSA", "--alsa-device", "plughw:5,0"],
    )

    assert backend.ALSA_DRIVER == "ALSA"
    assert backend.ALSA_DEVICE == "plughw:5,0"
    assert not isolated_audio_output.exists()


def test_forced_cli_audio_still_overrides_saved_preference(
    isolated_audio_output, monkeypatch
):
    _write_preference(
        isolated_audio_output,
        alsa_driver="alsa_mmap",
        alsa_device="hw:6,0",
        dac_name="Saved mmap DAC",
    )
    monkeypatch.setenv("SROVA_FORCE_CLI_AUDIO", "1")

    _run_main_to_loop(
        monkeypatch,
        ["--alsa-driver", "ALSA", "--alsa-device", "plughw:7,0"],
    )

    assert backend.ALSA_DRIVER == "ALSA"
    assert backend.ALSA_DEVICE == "plughw:7,0"
    assert json.loads(isolated_audio_output.read_text(encoding="utf-8")) == {
        "alsa_driver": "alsa_mmap",
        "alsa_device": "hw:6,0",
        "dac_name": "Saved mmap DAC",
    }


def test_save_validation_accepts_both_existing_driver_identifiers():
    assert backend._VALID_ALSA_DRIVERS == ("ALSA", "alsa_mmap")
    assert backend._validate_audio_driver("ALSA") == "ALSA"
    assert backend._validate_audio_driver("alsa_mmap") == "alsa_mmap"


def test_browser_selector_restores_backend_value_without_ui_change():
    assert '["ALSA", "alsa_mmap"].forEach(function(d)' in UI_SOURCE
    assert 'd === "alsa_mmap" ? "ALSA mmap (Recommended)" : d' in UI_SOURCE
    assert "driver: output.alsa_driver" in UI_SOURCE
    assert "driverSelect.value = currentDriver;" in UI_SOURCE
    assert "var SEEK_SESSION_GUARD_MS = 1500;" in UI_SOURCE


def test_official_packaging_does_not_hard_code_audio_driver():
    generic_exec = (
        "ExecStart=/usr/bin/python3 /opt/srova/main_headless.py --host 0.0.0.0"
    )

    generic_exec_lines = [
        line.strip()
        for line in PACKAGE_SOURCE.splitlines()
        if line.startswith("ExecStart=") and "/opt/srova/main_headless.py" in line
    ]

    assert generic_exec_lines == [generic_exec]
    assert all("--alsa-driver" not in line for line in generic_exec_lines)
    assert all("--alsa-device" not in line for line in generic_exec_lines)

    assert 'PACKAGE_SCRIPT="$REPO_ROOT/package.sh"' in ARM64_PACKAGE_SOURCE
    assert 'VERSION_FILE="$REPO_ROOT/version.txt"' in ARM64_PACKAGE_SOURCE
    assert 'exec bash "$PACKAGE_SCRIPT" deb "$VERSION"' in ARM64_PACKAGE_SOURCE
    assert "--alsa-driver" not in ARM64_PACKAGE_SOURCE
    assert "--alsa-device" not in ARM64_PACKAGE_SOURCE


def test_physical_device_default_and_identifiers_are_unchanged():
    assert 'ALSA_DEVICE = "hw:0,0"' in MAIN_SOURCE
    assert '_VALID_ALSA_DRIVERS = ("ALSA", "alsa_mmap")' in MAIN_SOURCE
    assert backend.ALSA_DEVICE == "hw:0,0"
