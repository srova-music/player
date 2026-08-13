from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import main_headless as backend


UI = (ROOT / "src/ui_web/ui.js").read_text(encoding="utf-8")
HTML = (ROOT / "src/ui_web/index.html").read_text(encoding="utf-8")
BACKEND = (ROOT / "src/main_headless.py").read_text(encoding="utf-8")


def recommendation(**metadata):
    base = {
        "udev": {},
        "driver_path": "",
        "sysfs_path": "",
        "usb_removable": "",
        "card_id": "",
        "pcm_info": "",
        "aplay_identity": "",
        "device_tree_compatible": "",
    }
    base.update(metadata)
    return backend._audio_device_recommendation_from_metadata(base)


def test_external_usb_audio_is_recommended():
    result = recommendation(
        udev={"ID_BUS": "usb", "ID_USB_DRIVER": "snd-usb-audio"},
        sysfs_path="/sys/devices/pci0000:00/usb1/1-2/1-2:1.0/sound/card0",
        driver_path="/sys/bus/usb/drivers/snd-usb-audio",
        usb_removable="removable",
        aplay_identity="Topping DX5 II",
    )

    assert result == {
        "recommended": True,
        "recommendation": "external_usb",
        "recommendation_reason": "External USB audio device",
    }


@pytest.mark.parametrize(
    "metadata",
    [
        {
            "udev": {"ID_BUS": "usb", "SOUND_FORM_FACTOR": "internal"},
            "usb_removable": "removable",
        },
        {
            "udev": {"ID_BUS": "usb", "SOUND_FORM_FACTOR": "webcam"},
            "usb_removable": "removable",
        },
        {
            "udev": {"ID_BUS": "usb"},
            "usb_removable": "fixed",
        },
        {
            "udev": {"ID_BUS": "platform", "SOUND_FORM_FACTOR": "internal"},
            "driver_path": "/sys/bus/platform/drivers/pcspkr",
            "aplay_identity": "pcsp pc speaker",
        },
        {
            "udev": {"ID_BUS": "pci"},
            "driver_path": "/sys/bus/pci/drivers/snd_hda_intel",
            "aplay_identity": "HDMI DisplayPort",
        },
        {
            "udev": {"ID_BUS": "platform", "SOUND_FORM_FACTOR": "internal"},
            "hat_product": "HiFiBerry DAC2 HD",
            "aplay_identity": "vc4-hdmi",
        },
    ],
)
def test_internal_fixed_and_unverified_outputs_are_other(metadata):
    result = recommendation(**metadata)

    assert result["recommended"] is False
    assert result["recommendation"] == "other"


@pytest.mark.parametrize(
    "identity",
    [
        "sndrpihifiberry",
        "IQaudIODAC",
        "sndrpijustboomdigi",
        "allo-boss-dac-pcm512x-audio",
    ],
)
def test_supported_audio_hat_identity_is_recommended(identity):
    result = recommendation(
        udev={"ID_BUS": "platform", "SOUND_FORM_FACTOR": "internal"},
        card_id=identity,
        aplay_identity=identity,
    )

    assert result["recommended"] is True
    assert result["recommendation"] == "supported_audio_hat"


def test_device_discovery_filters_and_sorts_recommended_first(monkeypatch):
    aplay = """
card 1: pcsp [pcsp], device 0: pcspeaker [pc speaker]
card 0: DX5II [Topping DX5 II], device 0: USB Audio [USB Audio]
"""
    monkeypatch.setattr(
        backend.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=aplay, stderr=""),
    )
    monkeypatch.setattr(
        backend,
        "_audio_device_recommendation",
        lambda item: {
            "recommended": item["device"] == "hw:0,0",
            "recommendation": (
                "external_usb" if item["device"] == "hw:0,0" else "other"
            ),
            "recommendation_reason": (
                "External USB audio device"
                if item["device"] == "hw:0,0"
                else "Other or unverified system output"
            ),
        },
    )

    recommended = backend._discover_audio_devices(include_other=False)
    all_outputs = backend._discover_audio_devices(include_other=True)

    assert [item["device"] for item in recommended] == ["hw:0,0"]
    assert [item["device"] for item in all_outputs] == ["hw:0,0", "hw:1,0"]
    assert all_outputs[0]["recommended"] is True
    assert all_outputs[1]["recommended"] is False


def test_showing_other_outputs_requires_current_warning_each_time(monkeypatch):
    monkeypatch.setattr(backend, "_save_app_settings", lambda: None)
    monkeypatch.setitem(backend._APP_SETTINGS, "recommended_audio_outputs_only", True)
    monkeypatch.setitem(backend._APP_SETTINGS, "other_audio_outputs_warning_version", 0)
    monkeypatch.setitem(backend._APP_SETTINGS, "other_audio_outputs_acknowledged_at", 0)

    with pytest.raises(ValueError, match="must be accepted"):
        backend._set_recommended_audio_outputs_only(False)
    with pytest.raises(ValueError, match="current Volume Safety warning"):
        backend._set_recommended_audio_outputs_only(
            False,
            warning_acknowledged=True,
            warning_version=backend._OTHER_AUDIO_OUTPUT_WARNING_VERSION - 1,
        )

    state = backend._set_recommended_audio_outputs_only(
        False,
        warning_acknowledged=True,
        warning_version=backend._OTHER_AUDIO_OUTPUT_WARNING_VERSION,
    )
    assert state["recommended_only"] is False
    assert state["acknowledged_warning_version"] == 1
    assert state["acknowledged_at"] > 0

    backend._set_recommended_audio_outputs_only(True)
    with pytest.raises(ValueError, match="must be accepted"):
        backend._set_recommended_audio_outputs_only(False)


def test_output_save_enforces_visibility_and_uses_discovered_name(monkeypatch):
    devices = {
        "hw:0,0": {
            "device": "hw:0,0",
            "name": "External DAC",
            "recommended": True,
        },
        "hw:1,0": {
            "device": "hw:1,0",
            "name": "Internal Headphone Output",
            "recommended": False,
        },
    }
    saved = []
    monkeypatch.setattr(
        backend,
        "_find_discovered_audio_device",
        lambda device: devices.get(device),
    )
    monkeypatch.setattr(
        backend,
        "_save_audio_output_config",
        lambda driver, device, name: saved.append((driver, device, name)),
    )
    monkeypatch.setattr(
        backend,
        "_audio_output_settings_state",
        lambda: {"ok": True},
    )
    monkeypatch.setattr(backend, "ALSA_DRIVER", "ALSA")
    monkeypatch.setattr(backend, "ALSA_DEVICE", "hw:0,0")
    monkeypatch.setattr(backend, "ALSA_DAC_NAME", "Old DAC")
    monkeypatch.setitem(backend._APP_SETTINGS, "recommended_audio_outputs_only", True)

    with pytest.raises(ValueError, match="not currently available"):
        backend._set_audio_output_preference("ALSA", "hw:9,9")
    with pytest.raises(ValueError, match="Other output"):
        backend._set_audio_output_preference("ALSA", "hw:1,0")

    assert backend._set_audio_output_preference(
        "alsa_mmap", "hw:0,0", "Untrusted browser name"
    ) == {"ok": True}
    assert saved[-1] == ("alsa_mmap", "hw:0,0", "External DAC")

    monkeypatch.setitem(backend._APP_SETTINGS, "recommended_audio_outputs_only", False)
    backend._set_audio_output_preference("ALSA", "hw:1,0")
    assert saved[-1] == ("ALSA", "hw:1,0", "Internal Headphone Output")


def test_ui_has_default_filter_warning_grouping_and_fresh_cache_tokens():
    assert 'filterLabel.textContent = "Only show recommended devices";' in UI
    assert 'fetch("/api/audio/device-filter", {' in UI
    assert "warning_acknowledged: warningAcknowledged === true" in UI
    assert "SROVA_OTHER_AUDIO_OUTPUT_WARNING_VERSION = 1" in UI
    assert (
        "READ CAREFULLY \\u2014 DANGER: RISK OF PERMANENT HEARING LOSS "
        "AND EQUIPMENT DAMAGE"
    ) in UI
    assert "Immediate and permanent hearing loss or tinnitus." in UI
    assert "var remaining = 20;" in UI
    assert "acceptButton.disabled = remaining > 0 || !checkbox.checked;" in UI
    assert 'recommendedGroup.label = "Recommended devices";' in UI
    assert 'otherGroup.label = "Other system outputs";' in UI
    assert '" (Recommended)"' in UI
    assert '"Select a recommended output"' in UI
    assert "deviceSelect.insertBefore(chooseOption, deviceSelect.firstChild);" in UI
    assert (
        "Restart SROVA to activate the new audio-output safety controls."
        in UI
    )
    assert "filterSaveInFlight || !audioOutputSafetyReady" in UI
    assert "/api/audio/device-filter" in BACKEND
    assert (
        "/ui_web/srova.css?v=20260812_v1_2_queue_drag2"
        in HTML
    )
    assert (
        "/ui_web/ui.js?v=20260812_v1_2_queue_drag2"
        in HTML
    )
