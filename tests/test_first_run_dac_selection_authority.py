import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import main_headless as backend


@pytest.fixture
def isolated_output(tmp_path, monkeypatch):
    preference = tmp_path / "audio_output.json"
    monkeypatch.setattr(backend, "_AUDIO_OUTPUT_FILE", str(preference))
    monkeypatch.setattr(backend, "ALSA_DRIVER", "alsa_mmap")
    monkeypatch.setattr(backend, "ALSA_DEVICE", "hw:0,0")
    monkeypatch.setattr(backend, "ALSA_DAC_NAME", "")
    monkeypatch.setattr(backend, "_AUDIO_OUTPUT_SELECTED", False)
    monkeypatch.setattr(backend, "APP_INSTANCE", None)
    return preference


def _write_preference(path, *, device="hw:3,0", name="SMSL USB DAC"):
    path.write_text(
        json.dumps({
            "alsa_driver": "alsa_mmap",
            "alsa_device": device,
            "dac_name": name,
        }),
        encoding="utf-8",
    )


def test_enumerated_default_without_preference_has_no_selection_authority(
    isolated_output,
    monkeypatch,
):
    monkeypatch.setattr(
        backend,
        "_find_discovered_audio_device",
        lambda _device: pytest.fail("unselected fallback must not be resolved"),
    )
    monkeypatch.setattr(
        backend.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("unselected fallback must not be probed"),
    )

    assert backend._load_audio_output_config() is False
    state = backend._audio_output_settings_state()

    assert state["output_selected"] is False
    assert state["alsa_device"] == "hw:0,0"
    assert state["dac_name"] == ""
    assert state["device_available"] is False
    assert state["device_selectable"] is False
    assert backend._selected_audio_output_available_for_playback() == (
        False,
        "no audio output selected",
    )
    assert backend._spotify_selected_dac_available() is False


def test_valid_saved_preference_establishes_selection_authority(isolated_output):
    _write_preference(isolated_output)

    assert backend._load_audio_output_config() is True
    assert backend._audio_output_state()["output_selected"] is True


def test_saved_but_absent_output_remains_selected_and_unavailable(
    isolated_output,
    monkeypatch,
):
    _write_preference(isolated_output)
    assert backend._load_audio_output_config() is True
    monkeypatch.setattr(backend, "_find_discovered_audio_device", lambda _device: None)

    state = backend._audio_output_settings_state()

    assert state["output_selected"] is True
    assert state["alsa_device"] == "hw:3,0"
    assert state["device_available"] is False
    monkeypatch.setattr(
        backend.subprocess,
        "run",
        lambda *_args, **_kwargs: type(
            "Result",
            (),
            {"stdout": "", "stderr": ""},
        )(),
    )
    assert backend._selected_audio_output_available_for_playback() == (
        False,
        "selected ALSA device hw:3,0 not found",
    )


def test_successful_settings_save_persists_and_establishes_authority(
    isolated_output,
    monkeypatch,
):
    discovered = {
        "device": "hw:3,0",
        "name": "SMSL USB DAC",
        "recommended": True,
        "recommendation": "external_usb",
        "recommendation_reason": "External USB audio device",
    }
    monkeypatch.setattr(
        backend,
        "_find_discovered_audio_device",
        lambda device: discovered if device == "hw:3,0" else None,
    )

    state = backend._set_audio_output_preference(
        "alsa_mmap",
        "hw:3,0",
        "Untrusted browser name",
    )

    assert state["output_selected"] is True
    assert json.loads(isolated_output.read_text(encoding="utf-8")) == {
        "alsa_driver": "alsa_mmap",
        "alsa_device": "hw:3,0",
        "dac_name": "SMSL USB DAC",
    }


# P13_SAVED_DAC_NUMERIC_BINDING_RECOVERY


def test_p13_unique_saved_dac_identity_relocates_numeric_binding(
    isolated_output,
    monkeypatch,
):
    _write_preference(
        isolated_output,
        device="hw:3,0",
        name="SMSL USB AUDIO",
    )
    assert backend._load_audio_output_config() is True

    devices = [
        {
            "device": "hw:0,0",
            "name": "bcm2835 Headphones",
            "label": "bcm2835 Headphones — hw:0,0",
            "recommended": False,
        },
        {
            "device": "hw:1,0",
            "name": "SMSL USB AUDIO",
            "label": "SMSL USB AUDIO — hw:1,0",
            "recommended": True,
        },
        {
            "device": "hw:3,0",
            "name": "vc4-hdmi-1",
            "label": "vc4-hdmi-1 — hw:3,0",
            "recommended": False,
        },
    ]

    monkeypatch.setattr(
        backend,
        "_discover_audio_devices",
        lambda include_other=True: list(devices),
    )

    saved = []

    def save(driver, device, name):
        saved.append((driver, device, name))

    monkeypatch.setattr(backend, "_save_audio_output_config", save)

    assert backend._reresolve_saved_audio_output_binding() is True

    assert backend.ALSA_DRIVER == "alsa_mmap"
    assert backend.ALSA_DEVICE == "hw:1,0"
    assert backend.ALSA_DAC_NAME == "SMSL USB AUDIO"
    assert backend._AUDIO_OUTPUT_SELECTED is True
    assert saved == [
        ("alsa_mmap", "hw:1,0", "SMSL USB AUDIO"),
    ]


def test_p13_no_saved_selection_never_auto_selects_enumerated_dac(
    isolated_output,
    monkeypatch,
):
    assert backend._load_audio_output_config() is False

    monkeypatch.setattr(
        backend,
        "_discover_audio_devices",
        lambda include_other=True: [
            {
                "device": "hw:1,0",
                "name": "SMSL USB AUDIO",
                "label": "SMSL USB AUDIO — hw:1,0",
                "recommended": True,
            },
        ],
    )

    monkeypatch.setattr(
        backend,
        "_save_audio_output_config",
        lambda *_args, **_kwargs: pytest.fail(
            "P6 forbids automatic selection without saved authority"
        ),
    )

    assert backend._reresolve_saved_audio_output_binding() is False
    assert backend._AUDIO_OUTPUT_SELECTED is False
    assert backend.ALSA_DEVICE == "hw:0,0"


def test_p13_ambiguous_identity_does_not_relocate(
    isolated_output,
    monkeypatch,
):
    _write_preference(
        isolated_output,
        device="hw:3,0",
        name="SMSL USB AUDIO",
    )
    assert backend._load_audio_output_config() is True

    monkeypatch.setattr(
        backend,
        "_discover_audio_devices",
        lambda include_other=True: [
            {
                "device": "hw:1,0",
                "name": "SMSL USB AUDIO",
                "label": "SMSL USB AUDIO — hw:1,0",
                "recommended": True,
            },
            {
                "device": "hw:2,0",
                "name": "SMSL USB AUDIO",
                "label": "SMSL USB AUDIO — hw:2,0",
                "recommended": True,
            },
            {
                "device": "hw:3,0",
                "name": "vc4-hdmi-1",
                "label": "vc4-hdmi-1 — hw:3,0",
                "recommended": False,
            },
        ],
    )

    monkeypatch.setattr(
        backend,
        "_save_audio_output_config",
        lambda *_args, **_kwargs: pytest.fail(
            "ambiguous identity must fail closed"
        ),
    )

    assert backend._reresolve_saved_audio_output_binding() is False
    assert backend.ALSA_DEVICE == "hw:3,0"
    assert backend.ALSA_DAC_NAME == "SMSL USB AUDIO"


def test_p13_relocation_preserves_pcm_device_number(
    isolated_output,
    monkeypatch,
):
    _write_preference(
        isolated_output,
        device="hw:3,1",
        name="Reference DAC",
    )
    assert backend._load_audio_output_config() is True

    monkeypatch.setattr(
        backend,
        "_discover_audio_devices",
        lambda include_other=True: [
            {
                "device": "hw:1,0",
                "name": "Reference DAC",
                "label": "Reference DAC — hw:1,0",
                "recommended": True,
            },
            {
                "device": "hw:3,1",
                "name": "Wrong Device",
                "label": "Wrong Device — hw:3,1",
                "recommended": False,
            },
        ],
    )

    monkeypatch.setattr(
        backend,
        "_save_audio_output_config",
        lambda *_args, **_kwargs: pytest.fail(
            "different PCM device number must not be rebound"
        ),
    )

    assert backend._reresolve_saved_audio_output_binding() is False
    assert backend.ALSA_DEVICE == "hw:3,1"


def test_p13_settings_state_rejects_wrong_identity_at_saved_numeric_slot(
    isolated_output,
    monkeypatch,
):
    _write_preference(
        isolated_output,
        device="hw:3,0",
        name="SMSL USB AUDIO",
    )
    assert backend._load_audio_output_config() is True

    wrong = {
        "device": "hw:3,0",
        "name": "vc4-hdmi-1",
        "label": "vc4-hdmi-1 — hw:3,0",
        "recommended": False,
        "recommendation": "other",
        "recommendation_reason": "Other or unverified system output",
    }

    monkeypatch.setattr(
        backend,
        "_find_discovered_audio_device",
        lambda _device: wrong,
    )

    state = backend._audio_output_settings_state()

    assert state["output_selected"] is True
    assert state["alsa_device"] == "hw:3,0"
    assert state["dac_name"] == "SMSL USB AUDIO"
    assert state["device_available"] is False
    assert state["device_selectable"] is False


# P13_AUTOMATIC_SAVED_DAC_RERESOLUTION


def test_p13_startup_watch_never_runs_without_saved_selection(
    isolated_output,
    monkeypatch,
):
    assert backend._load_audio_output_config() is False

    monkeypatch.setattr(backend, "_AUDIO_OUTPUT_RERESOLVE_SOURCE", 0)

    monkeypatch.setattr(
        backend,
        "_reresolve_saved_audio_output_binding",
        lambda **_kwargs: pytest.fail(
            "P6 forbids probing for automatic selection"
        ),
    )
    monkeypatch.setattr(
        backend.GLib,
        "timeout_add",
        lambda *_args, **_kwargs: pytest.fail(
            "P6 forbids starting a saved-DAC watch without saved authority"
        ),
    )

    assert backend._register_saved_audio_output_reresolve() == 0


def test_p13_startup_watch_retries_pending_then_stops_after_relocation(
    isolated_output,
    monkeypatch,
):
    _write_preference(
        isolated_output,
        device="hw:3,0",
        name="SMSL USB AUDIO",
    )
    assert backend._load_audio_output_config() is True

    monkeypatch.setattr(backend, "_AUDIO_OUTPUT_RERESOLVE_SOURCE", 0)

    statuses = iter(["pending", "relocated"])
    calls = []

    def reresolve(*, _return_status=False):
        assert _return_status is True
        return next(statuses)

    def timeout_add(delay_ms, callback):
        calls.append((delay_ms, callback))
        return 77

    monkeypatch.setattr(
        backend,
        "_reresolve_saved_audio_output_binding",
        reresolve,
    )
    monkeypatch.setattr(
        backend.GLib,
        "timeout_add",
        timeout_add,
    )

    source = backend._register_saved_audio_output_reresolve()

    assert source == 77
    assert backend._AUDIO_OUTPUT_RERESOLVE_SOURCE == 77
    assert len(calls) == 1
    assert calls[0][0] == backend._AUDIO_OUTPUT_RERESOLVE_FAST_MS

    callback = calls[0][1]
    assert callback() is False
    assert backend._AUDIO_OUTPUT_RERESOLVE_SOURCE == 0
    assert len(calls) == 1


def test_p13_startup_watch_stops_immediately_when_binding_is_resolved(
    isolated_output,
    monkeypatch,
):
    _write_preference(
        isolated_output,
        device="hw:1,0",
        name="SMSL USB AUDIO",
    )
    assert backend._load_audio_output_config() is True

    monkeypatch.setattr(backend, "_AUDIO_OUTPUT_RERESOLVE_SOURCE", 0)
    monkeypatch.setattr(
        backend,
        "_reresolve_saved_audio_output_binding",
        lambda *, _return_status=False: (
            "resolved"
            if _return_status
            else pytest.fail("status mode required")
        ),
    )
    monkeypatch.setattr(
        backend.GLib,
        "timeout_add",
        lambda *_args, **_kwargs: pytest.fail(
            "resolved binding must not start a polling timer"
        ),
    )

    assert backend._register_saved_audio_output_reresolve() == 0
    assert backend._AUDIO_OUTPUT_RERESOLVE_SOURCE == 0


def test_p13_playback_attempt_reresolves_before_strict_output_guard(
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        backend,
        "_reresolve_saved_audio_output_binding",
        lambda: calls.append("reresolve") or False,
    )
    monkeypatch.setattr(
        backend,
        "_require_audio_output_for_playback",
        lambda reason: calls.append(("require", reason)) or True,
    )
    monkeypatch.setattr(
        backend,
        "_playback_audio_output_ready",
        lambda: True,
    )

    assert backend._ensure_audio_output_for_playback("P13 test") is False
    assert calls == [
        "reresolve",
        ("require", "P13 test"),
    ]


def test_p13_spotify_rearm_waits_when_saved_physical_dac_is_unavailable(
    monkeypatch,
):
    from types import SimpleNamespace

    coordinator = SimpleNamespace(
        status_snapshot=lambda: {
            "state": "disabled",
            "spotify_owner": False,
            "native_blocked": False,
        },
    )

    app = SimpleNamespace(
        spotify_orchestrator=None,
        spotify_orchestrator_binding=None,
        spotify_coordinator=coordinator,
        spotify_runtime=SimpleNamespace(pcm_verifier=object()),
    )

    monkeypatch.setattr(backend, "APP_INSTANCE", app)
    monkeypatch.setattr(
        backend,
        "_spotify_enabled_intent",
        lambda: True,
    )
    monkeypatch.setattr(
        backend,
        "_spotify_selected_dac_available",
        lambda: False,
    )
    monkeypatch.setattr(
        backend,
        "_spotify_rearm_pcm_is_free",
        lambda: pytest.fail(
            "stale numeric PCM must not be inspected for Spotify rearm"
        ),
    )
    monkeypatch.setattr(
        backend,
        "_spotify_orchestrator_for_current_output",
        lambda: pytest.fail(
            "Spotify must not compose against an unavailable saved DAC"
        ),
    )

    assert backend._reconcile_existing_spotify_endpoint() is True
