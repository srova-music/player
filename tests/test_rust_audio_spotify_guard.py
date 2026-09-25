import sys
import threading
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from _rust import audio as rust_audio  # noqa: E402


class FakeRust:
    def __init__(self, output_rc=0):
        self.available = True
        self.output_rc = output_rc
        self.play_calls = 0
        self.output_calls = []
        self.uri_calls = []

    def play(self):
        self.play_calls += 1
        return 0

    def set_output(
        self,
        driver,
        device_id,
        buffer_us=0,
        latency_us=0,
        exclusive=False,
    ):
        self.output_calls.append(
            (driver, device_id, buffer_us, latency_us, exclusive)
        )
        return self.output_rc

    def set_preferred_output_format(self, _format):
        return 0

    def get_last_error(self):
        return "busy"

    def set_uri(self, uri):
        self.uri_calls.append(uri)
        return 0

    def pump_events(self):
        return 0

    def get_spectrum_frames_since(self, *_args, **_kwargs):
        return []


def _make_adapter(output_rc=0):
    adapter = object.__new__(rust_audio.RustAudioPlayerAdapter)
    adapter._rust = FakeRust(output_rc=output_rc)
    adapter._native_audio_guard_lock = threading.RLock()
    adapter._native_audio_guard = None
    adapter._pipewire_rate_blocked = False
    adapter._cached_is_playing = False
    adapter._rust_last_play_ts = 0.0
    adapter.output_state = "idle"
    adapter.output_error = None
    adapter.requested_driver = "ALSA"
    adapter.requested_device_id = "hw:1,0"
    adapter.current_driver = "ALSA"
    adapter.current_device_id = "hw:1,0"
    adapter.alsa_buffer_time = 20000
    adapter.alsa_latency_time = 2000
    adapter.exclusive_lock_mode = True
    adapter.preferred_output_format = ""
    adapter._alsa_reservation = None
    adapter._output_switch_lock = threading.RLock()
    adapter._output_switch_inflight = False
    adapter._output_switch_pending = None
    adapter._last_output_switch_sig = None
    adapter._last_output_switch_ts = 0.0
    adapter._output_switch_restore = None
    adapter._alsa_container_adapter_active = False
    adapter._alsa_container_adapter_format = ""
    adapter._alsa_container_adapter_diag_sig = ""
    adapter._reset_rust_visual_sync_state = lambda: None
    adapter._effective_output_selection = lambda: (
        adapter.current_driver,
        adapter.current_device_id,
    )
    adapter._refresh_rust_cache = lambda force=False: None
    adapter._retune_idle_timers = lambda: None
    adapter._release_alsa_reservation = lambda: None
    adapter._apply_driver_spectrum_policy = lambda _driver: None
    adapter._start_alsa_reservation_async = lambda *_args: None
    return adapter


@pytest.mark.parametrize("guard", [None, lambda *_args, **_kwargs: True])
def test_play_without_guard_or_with_allowed_guard_preserves_behavior(guard):
    adapter = _make_adapter()
    if guard is not None:
        adapter.set_native_audio_guard(guard)

    adapter.play()

    assert adapter._rust.play_calls == 1
    assert adapter._cached_is_playing is True
    assert adapter.output_state == "active"


@pytest.mark.parametrize(
    "guard",
    [
        lambda *_args, **_kwargs: False,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("secret")),
    ],
)
def test_play_guard_denial_or_exception_fails_closed(guard):
    adapter = _make_adapter()
    adapter.set_native_audio_guard(guard)

    adapter.play()

    assert adapter._rust.play_calls == 0
    assert adapter._cached_is_playing is False
    assert adapter.output_state == "idle"
    assert adapter.output_error is None


def test_limiter_retry_cannot_replay_when_guard_denies(monkeypatch):
    adapter = _make_adapter()
    adapter.set_native_audio_guard(lambda *_args, **_kwargs: False)
    adapter.limiter_enabled = True
    adapter._limiter_negotiation_retry_pending = False
    adapter._last_loaded_uri = "file:///music/test.flac"
    adapter._live_radio_mode = False
    adapter.set_limiter_enabled = lambda _enabled: True
    adapter.set_uri = lambda _uri: None
    callbacks = []
    monkeypatch.setattr(
        rust_audio.GLib,
        "idle_add",
        lambda callback, *_args: callbacks.append(callback) or 1,
    )

    adapter._apply_rust_error_policy("codec", "not-negotiated")
    assert len(callbacks) == 1
    assert callbacks[0]() is False
    assert adapter._rust.play_calls == 0
    assert adapter._cached_is_playing is False


def test_persistent_spectrum_recovery_cannot_replay_when_guard_denies():
    adapter = _make_adapter()
    adapter.set_native_audio_guard(lambda *_args, **_kwargs: False)
    adapter._rust_spectrum_enabled = True
    adapter._rust_pump_source = 1
    adapter._rust_last_pump_ts = 0.0
    adapter._rust_pump_idle_interval_playing_s = 0.08
    adapter._rust_pump_idle_interval_paused_s = 0.25
    adapter._viz_trace_enabled = False
    adapter._last_rust_spectrum_seq = 0
    adapter._rust_spectrum_frames_seen = 0
    adapter._rust_last_spectrum_seen_ts = 0.0
    adapter._rust_last_spectrum_recover_ts = 0.0
    adapter._spectrum_stall_count = 4
    adapter._viz_spectrum_queue = deque()
    adapter._last_loaded_uri = "file:///music/test.flac"
    adapter._cached_pos_s = 4.0
    adapter._cached_dur_s = 20.0
    adapter._live_radio_mode = False
    adapter._pw_last_probe_ts = 0.0

    assert adapter._pump_rust_events_tick() is True
    assert adapter._rust.play_calls == 0
    assert adapter._rust.uri_calls == []
    assert adapter._cached_is_playing is False


def test_allowed_hardware_output_claim_reaches_rust():
    adapter = _make_adapter()
    adapter.set_native_audio_guard(lambda *_args, **_kwargs: True)

    assert adapter.set_output("ALSA", "hw:2,0") is True
    assert len(adapter._rust.output_calls) == 1
    assert adapter.current_device_id == "hw:2,0"


def test_blocked_hardware_claim_is_inert_and_bookkeeping_clears():
    adapter = _make_adapter(output_rc=-4)
    reservation_calls = []
    adapter._start_alsa_reservation_async = (
        lambda *args: reservation_calls.append(args)
    )
    before = {
        "requested_driver": adapter.requested_driver,
        "requested_device_id": adapter.requested_device_id,
        "current_driver": adapter.current_driver,
        "current_device_id": adapter.current_device_id,
        "output_state": adapter.output_state,
        "output_error": adapter.output_error,
    }
    adapter.set_native_audio_guard(lambda *_args, **_kwargs: False)

    assert adapter.set_output("ALSA", "hw:2,0") is False
    assert adapter._rust.output_calls == []
    assert reservation_calls == []
    assert adapter._output_switch_inflight is False
    assert adapter._output_switch_pending is None
    assert adapter._output_switch_restore is None
    assert {
        "requested_driver": adapter.requested_driver,
        "requested_device_id": adapter.requested_device_id,
        "current_driver": adapter.current_driver,
        "current_device_id": adapter.current_device_id,
        "output_state": adapter.output_state,
        "output_error": adapter.output_error,
    } == before


def test_permission_change_between_checks_cannot_reach_rust():
    adapter = _make_adapter()
    decisions = iter((True, False))
    adapter.set_native_audio_guard(
        lambda *_args, **_kwargs: next(decisions)
    )

    assert adapter.set_output("ALSA", "hw:2,0") is False
    assert adapter._rust.output_calls == []
    assert adapter._output_switch_inflight is False
    assert adapter._output_switch_pending is None
    assert adapter._output_switch_restore is None


def test_blocked_reservation_retry_restores_previous_output_state():
    adapter = _make_adapter(output_rc=-4)
    permission = {"allowed": True}
    reservation_calls = []
    adapter.set_native_audio_guard(
        lambda *_args, **_kwargs: permission["allowed"]
    )
    adapter._start_alsa_reservation_async = (
        lambda *args: reservation_calls.append(args)
    )

    assert adapter.set_output("ALSA", "hw:2,0") is True
    assert reservation_calls == [("ALSA", "hw:2,0", 2)]
    assert adapter.output_state == "switching"
    assert adapter._output_switch_restore is not None

    permission["allowed"] = False
    assert adapter.set_output("ALSA", "hw:2,0") is False

    assert len(adapter._rust.output_calls) == 1
    assert adapter.requested_driver == "ALSA"
    assert adapter.requested_device_id == "hw:1,0"
    assert adapter.current_driver == "ALSA"
    assert adapter.current_device_id == "hw:1,0"
    assert adapter.output_state == "idle"
    assert adapter.output_error is None
    assert adapter._output_switch_inflight is False
    assert adapter._output_switch_pending is None
    assert adapter._output_switch_restore is None


def test_permission_change_blocks_deferred_reservation_retry(monkeypatch):
    adapter = _make_adapter()
    permission = {"allowed": True}
    adapter.set_native_audio_guard(
        lambda *_args, **_kwargs: permission["allowed"]
    )

    class Reservation:
        def __init__(self, card_num):
            self.card_num = card_num
            self.acquired = False

        def acquire(self):
            self.acquired = True
            return True

    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self.target = target

        def start(self):
            self.target()

    callbacks = []
    monkeypatch.setitem(
        sys.modules,
        "services.alsa_reserve",
        SimpleNamespace(AlsaDeviceReservation=Reservation),
    )
    monkeypatch.setattr(rust_audio.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(
        rust_audio.GLib,
        "idle_add",
        lambda callback, *_args: callbacks.append(callback) or 1,
    )

    rust_audio.RustAudioPlayerAdapter._start_alsa_reservation_async(
        adapter,
        "ALSA",
        "hw:2,0",
        2,
    )
    assert len(callbacks) == 1
    permission["allowed"] = False

    assert callbacks[0]() is False
    assert adapter._rust.output_calls == []
    assert adapter._output_switch_inflight is False


def test_nonexclusive_alsa_default_release_is_allowed_while_blocked():
    adapter = _make_adapter()
    adapter.exclusive_lock_mode = False
    adapter.set_native_audio_guard(lambda *_args, **_kwargs: False)

    assert adapter.set_output("ALSA", "default") is True
    assert len(adapter._rust.output_calls) == 1
    assert adapter._rust.output_calls[0][0:2] == ("ALSA", "default")


def test_guard_receives_only_bounded_output_claim_details():
    adapter = _make_adapter()
    calls = []

    def guard(operation, **details):
        calls.append((operation, details))
        return False

    adapter.set_native_audio_guard(guard)
    adapter.set_output("ALSA", "/private/device/path")

    assert calls == [
        (
            "output_claim",
            {
                "source": "set-output",
                "driver": "alsa_auto",
                "exclusive": True,
            },
        )
    ]
    assert "/private/device/path" not in repr(calls)
