import ast
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_SOURCE = REPO_ROOT / "src" / "main_headless.py"

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "src"),
)

import backend.tidal as tidal_mod
from backend.tidal import TidalBackend


def _load_main_functions(names, namespace):
    source = MAIN_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(MAIN_SOURCE))

    wanted = set(names)
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in wanted
    ]

    found = {node.name for node in nodes}
    assert found == wanted, (
        f"Missing functions: {sorted(wanted - found)}"
    )

    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)

    namespace = dict(namespace)
    namespace.setdefault("__builtins__", __builtins__)

    exec(
        compile(module, str(MAIN_SOURCE), "exec"),
        namespace,
    )
    return namespace


def _quiet_logger():
    return SimpleNamespace(
        debug=lambda *_args, **_kwargs: None,
        info=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
    )


def test_requests_timeout_is_classified_as_network():
    backend = object.__new__(TidalBackend)

    error = tidal_mod.requests.exceptions.ConnectTimeout(
        "offline"
    )

    assert backend._classify_session_exception(error) == "network"


def test_http_pool_installs_bounded_default_timeout_once(
    monkeypatch,
):
    calls = []
    mounts = []

    class _HttpSession:
        def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs.get("timeout")))
            return kwargs.get("timeout")

        def mount(self, prefix, adapter):
            mounts.append((prefix, adapter))

    http_session = _HttpSession()
    session = SimpleNamespace(
        request=object(),
        request_session=http_session,
    )

    backend = object.__new__(TidalBackend)
    backend.session = session

    monkeypatch.setattr(
        tidal_mod,
        "get_global_session",
        lambda: None,
    )
    monkeypatch.delenv(
        "SROVA_TIDAL_CONNECT_TIMEOUT",
        raising=False,
    )
    monkeypatch.delenv(
        "SROVA_TIDAL_READ_TIMEOUT",
        raising=False,
    )
    monkeypatch.setenv("HIRESTI_HTTP_POOL_SIZE", "16")

    backend._tune_http_pool(session_obj=session)
    backend._tune_http_pool(session_obj=session)

    assert http_session._srova_default_timeout == (4.0, 10.0)
    assert http_session.request("GET", "https://example.invalid") == (
        4.0,
        10.0,
    )
    assert http_session.request(
        "GET",
        "https://example.invalid",
        timeout=23,
    ) == 23

    assert [call[2] for call in calls] == [
        (4.0, 10.0),
        23,
    ]
    assert [prefix for prefix, _adapter in mounts] == [
        "https://",
        "http://",
        "https://",
        "http://",
    ]


def test_session_recovery_performs_only_one_retry():
    backend = object.__new__(TidalBackend)

    attempts = []
    recovery_reasons = []

    def _always_offline():
        attempts.append("call")
        raise tidal_mod.requests.exceptions.ConnectTimeout(
            "offline"
        )

    def _recover(reason="api"):
        recovery_reasons.append(reason)
        return True

    backend.recover_session = _recover

    with pytest.raises(
        tidal_mod.requests.exceptions.ConnectTimeout
    ):
        backend._call_with_session_recovery(
            _always_offline,
            context="stream",
        )

    assert attempts == ["call", "call"]
    assert recovery_reasons == ["stream"]


def test_stream_network_failure_stops_quality_fallback():
    backend = object.__new__(TidalBackend)
    backend.quality = "HI_RES_LOSSLESS"

    applied_qualities = []
    track_requests = []
    stream_requests = []
    legacy_requests = []
    reset_reasons = []

    class _FullTrack:
        name = "Offline Track"

        def get_url(self):
            legacy_requests.append("legacy")
            raise AssertionError(
                "legacy endpoint must not run after network failure"
            )

    full_track = _FullTrack()

    def _track(track_id):
        track_requests.append(str(track_id))
        return full_track

    def _stream(_track):
        stream_requests.append("stream")
        raise tidal_mod.requests.exceptions.ConnectTimeout(
            "offline"
        )

    backend.session = SimpleNamespace(track=_track)
    backend._get_stream_quality_fallback_chain = lambda: [
        "HI_RES_LOSSLESS",
        "LOSSLESS",
        "HIGH",
    ]
    backend._apply_session_quality = applied_qualities.append
    backend._get_url_from_stream = _stream
    backend._reset_tidal_http_connections = (
        lambda reason="network": reset_reasons.append(reason)
    )

    track = SimpleNamespace(
        id="track-1",
        name="Offline Track",
        album=None,
    )

    result = backend._get_stream_url_locked(track)

    assert result is None
    assert track_requests == ["track-1"]
    assert stream_requests == ["stream"]
    assert legacy_requests == []
    assert reset_reasons == [
        "stream-resolution:ConnectTimeout",
    ]

    # One attempted quality, followed by restoration of the preference.
    assert applied_qualities == [
        "HI_RES_LOSSLESS",
        "HI_RES_LOSSLESS",
    ]


def _tidal_resolution_namespace():
    return _load_main_functions(
        (
            "_begin_tidal_stream_resolution",
            "_invalidate_tidal_stream_resolution",
            "_tidal_stream_resolution_matches",
        ),
        {
            "threading": threading,
            "logger": _quiet_logger(),
            "_TIDAL_STREAM_RESOLUTION_LOCK": threading.Lock(),
            "_TIDAL_STREAM_RESOLUTION_GENERATION": 0,
            "_TIDAL_STREAM_RESOLUTION_PENDING": None,
            "_QUEUE_LOCK": threading.Lock(),
            "PLAY_QUEUE": ["track-1"],
            "QUEUE_INDEX": 0,
        },
    )


def test_new_tidal_resolution_supersedes_older_token():
    namespace = _tidal_resolution_namespace()

    first = namespace["_begin_tidal_stream_resolution"](
        0,
        "track-1",
    )
    second = namespace["_begin_tidal_stream_resolution"](
        0,
        "track-1",
    )

    assert second == first + 1
    assert namespace["_tidal_stream_resolution_matches"](
        first,
        0,
        "track-1",
    ) is False
    assert namespace["_tidal_stream_resolution_matches"](
        second,
        0,
        "track-1",
    ) is True


def test_tidal_resolution_requires_queue_identity_and_consumes_once():
    namespace = _tidal_resolution_namespace()

    token = namespace["_begin_tidal_stream_resolution"](
        0,
        "track-1",
    )

    namespace["PLAY_QUEUE"][0] = "track-2"

    assert namespace["_tidal_stream_resolution_matches"](
        token,
        0,
        "track-1",
    ) is False
    assert namespace["_TIDAL_STREAM_RESOLUTION_PENDING"] is None

    namespace["PLAY_QUEUE"][0] = "track-1"
    replacement = namespace["_begin_tidal_stream_resolution"](
        0,
        "track-1",
    )

    assert namespace["_tidal_stream_resolution_matches"](
        replacement,
        0,
        "track-1",
        consume=True,
    ) is True
    assert namespace["_TIDAL_STREAM_RESOLUTION_PENDING"] is None
    assert namespace["_tidal_stream_resolution_matches"](
        replacement,
        0,
        "track-1",
    ) is False


def test_radio_standby_cancels_start_before_stop_and_idle_reset():
    events = []

    class _Player:
        def is_playing(self):
            return False

        def stop(self):
            events.append("stop")

    namespace = _load_main_functions(
        (
            "_cancel_pending_radio_start",
            "_radio_standby_payload",
        ),
        {
            "threading": threading,
            "logger": _quiet_logger(),
            "_RADIO_START_LOCK": threading.Lock(),
            "_RADIO_START_TOKEN": 41,
            "_RADIO_STARTING": True,
            "APP_INSTANCE": SimpleNamespace(player=_Player()),
            "RADIO_MODE": True,
            "CURRENT_RADIO": {
                "name": "Test Radio",
                "url": "https://example.invalid/radio",
            },
            "PAUSED_PLAYBACK_POSITION": 17.5,
            "PAUSED_PLAYBACK_TRACK_ID": "radio:station:test",
            "PAUSED_PIPELINE_RELEASED": True,
            "_status_playback_context": lambda _player: {
                "source": "radio",
                "playback_state": "paused",
            },
            "cancel_scrobble": (
                lambda: events.append("cancel-scrobble")
            ),
            "_reset_idle_playback_context": (
                lambda: events.append("reset-idle")
            ),
            "_schedule_idle_release": (
                lambda seconds: events.append(
                    f"release:{seconds}"
                )
            ),
        },
    )

    actual_cancel = namespace["_cancel_pending_radio_start"]

    def _tracked_cancel():
        events.append("cancel-start")
        actual_cancel()

    namespace["_cancel_pending_radio_start"] = _tracked_cancel

    result = namespace["_radio_standby_payload"]()

    assert result == {
        "ok": True,
        "cleared": True,
        "result": "idle",
    }
    assert namespace["_RADIO_START_TOKEN"] == 42
    assert namespace["_RADIO_STARTING"] is False
    assert namespace["PAUSED_PLAYBACK_POSITION"] == 0.0
    assert namespace["PAUSED_PLAYBACK_TRACK_ID"] is None
    assert namespace["PAUSED_PIPELINE_RELEASED"] is False
    assert events == [
        "cancel-start",
        "stop",
        "cancel-scrobble",
        "reset-idle",
        "release:5",
    ]


def test_cancelled_radio_token_cannot_prepare_audio():
    audio_preparation = []

    namespace = _load_main_functions(
        (
            "_cancel_pending_radio_start",
            "play_radio_station",
        ),
        {
            "threading": threading,
            "logger": _quiet_logger(),
            "_RADIO_START_LOCK": threading.Lock(),
            "_RADIO_START_TOKEN": 7,
            "_RADIO_STARTING": True,
            "APP_INSTANCE": SimpleNamespace(
                player=SimpleNamespace()
            ),
            "_radio_station_key": (
                lambda station: str(station.get("id") or "")
            ),
            "_require_audio_output_for_playback": (
                lambda reason: audio_preparation.append(reason)
            ),
        },
    )

    namespace["_cancel_pending_radio_start"]()

    result = namespace["play_radio_station"](
        {
            "id": "test",
            "name": "Test Radio",
            "url": "https://example.invalid/radio",
        },
        token=7,
        reason="queued Radio start",
    )

    assert result is False
    assert namespace["_RADIO_START_TOKEN"] == 8
    assert namespace["_RADIO_STARTING"] is False
    assert audio_preparation == []


def _online_transition_namespace(playback_context):
    scheduled = []

    namespace = _load_main_functions(
        (
            "_schedule_active_tidal_offline_stop",
            "_online_state_payload",
        ),
        {
            "time": time,
            "threading": threading,
            "logger": _quiet_logger(),
            "_ONLINE_STATE_LOCK": threading.Lock(),
            "_ONLINE_STATE": {
                "online": True,
                "checked_at": 0.0,
                "method": "tcp_connect",
                "target": "",
                "confidence": "unknown",
                "error": "",
            },
            "_ONLINE_STATE_TTL": 10.0,
            "_probe_external_online": lambda: {
                "online": False,
                "target": "all",
                "confidence": "all_failed",
                "error": "offline",
            },
            "APP_INSTANCE": SimpleNamespace(
                player=SimpleNamespace()
            ),
            "_status_playback_context": (
                lambda _player: dict(playback_context)
            ),
            "_finalize_end_of_queue_playback": (
                lambda _reason: False
            ),
            "GLib": SimpleNamespace(
                idle_add=lambda callback, *args: (
                    scheduled.append((callback, args)) or 1
                )
            ),
        },
    )

    return namespace, scheduled


def test_confirmed_offline_transition_schedules_active_tidal_stop_once():
    namespace, scheduled = _online_transition_namespace({
        "source": "tidal",
        "playback_state": "playing",
        "current_track_valid": True,
    })

    first = namespace["_online_state_payload"](force=True)
    second = namespace["_online_state_payload"](force=True)

    assert first["online"] is False
    assert second["online"] is False
    assert len(scheduled) == 1
    _callback, args = scheduled[0]
    assert args == (
        "TIDAL playback stopped: network unavailable",
    )


def test_confirmed_offline_transition_does_not_stop_local_playback():
    namespace, scheduled = _online_transition_namespace({
        "source": "local",
        "playback_state": "playing",
        "current_track_valid": True,
    })

    result = namespace["_online_state_payload"](force=True)

    assert result["online"] is False
    assert scheduled == []


def test_confirmed_offline_transition_does_not_stop_paused_tidal():
    namespace, scheduled = _online_transition_namespace({
        "source": "tidal",
        "playback_state": "paused",
        "current_track_valid": True,
    })

    result = namespace["_online_state_payload"](force=True)

    assert result["online"] is False
    assert scheduled == []
