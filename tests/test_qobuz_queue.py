import ast
import threading
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "src" / "main_headless.py"


class _Logger:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


class _GLib:
    @staticmethod
    def idle_add(callback, *args):
        return callback(*args)


def _source():
    return MAIN.read_text(encoding="utf-8")


def _function_node(name):
    text = _source()
    tree = ast.parse(text, filename=str(MAIN))
    hits = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    assert len(hits) == 1
    return text, hits[0]


def _function_source(name):
    text, node = _function_node(name)
    lines = text.splitlines()
    return "\n".join(lines[node.lineno - 1:node.end_lineno])


def _load_functions(names, namespace=None):
    text = _source()
    tree = ast.parse(text, filename=str(MAIN))
    wanted = set(names)
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in wanted
    ]
    assert {node.name for node in nodes} == wanted

    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)

    ns = dict(namespace or {})
    exec(compile(module, str(MAIN), "exec"), ns)
    return ns


def test_q5_provider_identity_and_mixed_queue_sequence():
    ns = _load_functions(["_queue_item_source"])
    classify = ns["_queue_item_source"]

    queue = [
        ("101", {}),
        (
            "qobuz:202",
            {"source": "qobuz", "provider_track_id": "202"},
        ),
        ("303", {"source": "tidal"}),
        (
            "qobuz:404",
            {"source": "qobuz", "provider_track_id": "404"},
        ),
    ]

    assert [classify(track_id, meta) for track_id, meta in queue] == [
        "tidal",
        "qobuz",
        "tidal",
        "qobuz",
    ]

    # Historical unprefixed identity is authoritative TIDAL regardless
    # of conflicting provider metadata.
    assert classify("101", {"source": "qobuz"}) == "tidal"
    assert classify("101", {"source": "local"}) == "tidal"
    assert classify("101", {"source": "radio"}) == "tidal"

    # Canonical prefixes also win over conflicting metadata.
    assert classify("qobuz:202", {"source": "local"}) == "qobuz"
    assert classify("qobuz:202", {"source": "radio"}) == "qobuz"
    assert classify("local:abc", {"source": "qobuz"}) == "local"
    assert classify(
        "radio:station:abc",
        {"source": "qobuz"},
    ) == "radio"

    assert classify("unknown:abc", {}) == "unknown"



def test_q5_status_uses_authoritative_queue_provider_identity():
    class Player:
        @staticmethod
        def is_playing():
            return False

    state = {
        "track_id": "qobuz:202",
        "meta": {
            "id": "qobuz:202",
            "source": "qobuz",
            "title": "Queued Qobuz",
        },
    }

    ns = _load_functions(
        ["_queue_item_source", "_status_playback_context"],
        {
            "_queue_current_snapshot": (
                lambda: (state["track_id"], state["meta"])
            ),
            "RADIO_MODE": False,
            "CURRENT_RADIO": None,
            "_qobuz_playback_is_active": lambda: False,
            "_qobuz_active_queue_id": lambda: "",
            "_is_local_playback_context": lambda: False,
            "LOCAL_PLAYBACK_CONTEXT": {},
            "CURRENT_CONTEXT": {
                "track_id": "qobuz:202",
                "title": "Queued Qobuz",
            },
            "PLAYBACK_START_TIME": 0,
            "time": __import__("time"),
        },
    )

    status = ns["_status_playback_context"](Player())
    assert status["source"] == "qobuz"
    assert status["current_track_id"] == "qobuz:202"

    # Historical unprefixed ID remains TIDAL even when stale metadata claims
    # that it is Local.
    state["track_id"] = "101"
    state["meta"] = {
        "id": "101",
        "source": "local",
        "title": "Historical TIDAL",
    }
    ns["CURRENT_CONTEXT"] = {
        "track_id": "101",
        "title": "Historical TIDAL",
    }

    status = ns["_status_playback_context"](Player())
    assert status["source"] == "tidal"
    assert status["current_track_id"] == "101"


def test_q5_queue_helpers_honor_canonical_provider_identity():
    # qobuz:<id> remains Qobuz even if malformed metadata claims Local.
    local_ns = _load_functions(
        ["_queue_item_source", "_is_local_track_payload"]
    )
    assert local_ns["_is_local_track_payload"](
        {
            "id": "qobuz:202",
            "source": "local",
        }
    ) is False
    assert local_ns["_is_local_track_payload"](
        {
            "id": "local:abc",
            "source": "qobuz",
        }
    ) is True

    queue_lock = threading.Lock()

    radio_ns = _load_functions(
        ["_queue_item_source", "_queue_current_item_is_radio"],
        {
            "_QUEUE_LOCK": queue_lock,
            "PLAY_QUEUE": ["qobuz:202"],
            "QUEUE_INDEX": 0,
            "PLAY_QUEUE_META_CACHE": {
                "qobuz:202": {"source": "radio"}
            },
            "logger": _Logger(),
        },
    )

    assert radio_ns["_queue_current_item_is_radio"]() is False

    prune_ns = _load_functions(
        ["_queue_item_source", "_queue_prune_after_first_radio_locked"],
        {
            "PLAY_QUEUE": [
                "qobuz:202",
                "radio:station:test",
                "303",
            ],
            "ORIGINAL_QUEUE": [
                "qobuz:202",
                "radio:station:test",
                "303",
            ],
            "PLAY_QUEUE_META_CACHE": {
                "qobuz:202": {"source": "radio"},
                "radio:station:test": {"source": "qobuz"},
                "303": {},
            },
            "logger": _Logger(),
        },
    )

    removed = prune_ns["_queue_prune_after_first_radio_locked"](
        "q5-test"
    )

    # The malformed Qobuz metadata must not make index 0 terminal Radio.
    # The canonical radio:station: ID at index 1 is the terminal item.
    assert removed == 1
    assert prune_ns["PLAY_QUEUE"] == [
        "qobuz:202",
        "radio:station:test",
    ]
    assert prune_ns["ORIGINAL_QUEUE"] == [
        "qobuz:202",
        "radio:station:test",
    ]

def test_q5_qobuz_native_identity_requires_canonical_prefix():
    ns = _load_functions(["_qobuz_queue_native_track_id"])
    native = ns["_qobuz_queue_native_track_id"]

    assert native("qobuz:202", {}) == "202"
    assert native(
        "qobuz:202",
        {"provider_track_id": "202"},
    ) == "202"

    assert native("202", {}) is None
    assert native("qobuz:", {}) is None
    assert native("qobuz:abc", {}) is None
    assert native("qobuz:0", {}) is None
    assert native(
        "qobuz:202",
        {"provider_track_id": "999"},
    ) is None


def test_q5_qobuz_stale_completion_rejects_index_or_identity_change():
    queue_lock = threading.Lock()
    ns = _load_functions(
        ["_qobuz_queue_context_matches"],
        {
            "_QUEUE_LOCK": queue_lock,
            "PLAY_QUEUE": ["101", "qobuz:202", "303"],
            "QUEUE_INDEX": 1,
        },
    )

    matches = ns["_qobuz_queue_context_matches"]

    context = {
        "queue_index": 1,
        "queue_id": "qobuz:202",
    }
    assert matches(context) is True

    ns["QUEUE_INDEX"] = 2
    assert matches(context) is False

    ns["QUEUE_INDEX"] = 1
    ns["PLAY_QUEUE"][1] = "qobuz:999"
    assert matches(context) is False


def test_q5_next_walks_tidal_qobuz_tidal_qobuz_shared_indices():
    played = []

    base = {
        "QUEUE_INDEX": 0,
        "REPEAT_MODE": "off",
        "PLAY_QUEUE_PENDING_AFTER_CONTEXT": False,
        "PLAY_QUEUE": ["101", "qobuz:202", "303", "qobuz:404"],
        "PLAY_QUEUE_META_CACHE": {
            "101": {},
            "qobuz:202": {"source": "qobuz"},
            "303": {},
            "qobuz:404": {"source": "qobuz"},
        },
        "RADIO_MODE": False,
        "GLib": _GLib,
        "logger": _Logger(),
        "_is_local_album_playback_context": lambda: False,
        "_local_playback_has_queue_position": lambda: False,
        "_tidal_infinite_play_enabled": lambda: False,
        "_finalize_end_of_queue_playback": lambda reason: False,
        "_autofill_queue": lambda: None,
        "threading": threading,
        "play_queue_index": lambda index: played.append(index),
    }

    # Mutate the exact globals dictionary used by the dynamically-loaded
    # function. Updating a separate outer dict would not affect
    # play_next_track.__globals__.
    ns = _load_functions(
        ["_queue_item_source", "play_next_track"],
        base,
    )

    assert ns["play_next_track"].__globals__ is ns

    ns["QUEUE_INDEX"] = 0
    ns["play_next_track"]()
    assert played[-1] == 1

    ns["QUEUE_INDEX"] = 1
    ns["play_next_track"]()
    assert played[-1] == 2

    ns["QUEUE_INDEX"] = 2
    ns["play_next_track"]()
    assert played[-1] == 3



def test_q5_queued_qobuz_eos_advances_but_direct_proof_does_not():
    class Player:
        def __init__(self):
            self.original_calls = 0
            self.stop_calls = 0
            self._on_eos_callback = self._original

        def _original(self, *args, **kwargs):
            self.original_calls += 1

        def stop(self):
            self.stop_calls += 1

    def run(queue_id):
        player = Player()
        advanced = []
        invalidated = []

        ns = _load_functions(
            ["install_eos_hook"],
            {
                "APP_INSTANCE": SimpleNamespace(player=player),
                "_radio_eos_should_ignore": lambda: False,
                "_qobuz_playback_is_active": lambda: True,
                "_qobuz_active_queue_id": lambda: queue_id,
                "_invalidate_qobuz_playback": (
                    lambda reason: invalidated.append(reason)
                ),
                "play_next_track": lambda: advanced.append(True),
                "logger": _Logger(),
            },
        )

        ns["install_eos_hook"]()
        player._on_eos_callback()

        return player, advanced, invalidated

    queued_player, queued_advanced, queued_invalidated = run(
        "qobuz:202"
    )
    assert queued_player.original_calls == 1
    assert queued_player.stop_calls == 1
    assert queued_advanced == [True]
    assert queued_invalidated == ["qobuz-queue-eos"]

    direct_player, direct_advanced, direct_invalidated = run("")
    assert direct_player.original_calls == 1
    assert direct_player.stop_calls == 1
    assert direct_advanced == []
    assert direct_invalidated == []


def test_q5_qobuz_seed_is_rejected_when_effective_provider_is_tidal():
    recommendation_calls = []

    ns = {
        "PLAY_QUEUE": ["qobuz:202"],
        "ORIGINAL_QUEUE": ["qobuz:202"],
        "PLAY_QUEUE_META_CACHE": {
            "qobuz:202": {
                "source": "qobuz",
                "provider_track_id": "202",
            }
        },
        "_QUEUE_LOCK": threading.Lock(),
        "logger": _Logger(),
        "_normalise_tidal_infinite_play_mode": lambda mode: mode,
        "_tidal_infinite_play_mode": lambda: "balanced",
        "_recommended_tracks_for_seed": (
            lambda *args, **kwargs: recommendation_calls.append(True)
        ),
    }

    ns.update(
        _load_functions(
            [
                "_queue_item_source",
                "_normalise_infinite_play_provider",
                "_append_infinite_play_recommendations",
            ],
            ns,
        )
    )

    result = ns["_append_infinite_play_recommendations"](
        seed_id="qobuz:202",
        limit=10,
        autoplay=False,
        mode="balanced",
        provider="tidal",
    )

    assert result["ok"] is False
    assert (
        result["error"]
        == "seed provider does not match Infinite Play provider"
    )
    assert recommendation_calls == []



def test_q5_play_queue_index_has_explicit_provider_dispatch():
    block = _function_source("play_queue_index")

    assert "queue_source = _queue_item_source(track_id, queue_meta)" in block
    assert 'if queue_source == "radio":' in block
    assert 'if queue_source == "local":' in block
    assert 'if queue_source == "qobuz":' in block
    assert "_qobuz_queue_native_track_id(" in block
    assert "_qobuz_test_play_payload(" in block
    assert '"queue_index": int(index)' in block
    assert '"queue_id": str(track_id)' in block
    assert 'if queue_source != "tidal":' in block

    assert (
        block.index('if queue_source == "qobuz":')
        < block.index('_invalidate_qobuz_playback("tidal-playback")')
    )


def test_q5_qobuz_context_survives_audio_output_reentry():
    block = _function_source("_complete_qobuz_test_play")

    assert "_queue_context=None" in block
    assert "_queue_context=_queue_context" in block
    assert block.count("_qobuz_queue_context_matches(") >= 2
    assert '"track_id": queue_id or str(track_id)' in block
    assert "_QOBUZ_ACTIVE_QUEUE_ID = queue_id or None" in block


def test_q5_qobuz_manual_next_previous_and_jump_cancel_old_transport():
    assert (
        '_cancel_qobuz_for_queue_transition("user-next")'
        in _function_source("_tidal_next_payload")
    )
    assert (
        '_cancel_qobuz_for_queue_transition("user-previous")'
        in _function_source("_tidal_prev_payload")
    )
    assert (
        '_cancel_qobuz_for_queue_transition("queue-jump")'
        in _source()
    )


def test_q5_qobuz_resume_is_provider_aware():
    class Player:
        def __init__(self):
            self.play_calls = 0

        def play(self):
            self.play_calls += 1

    # ---------------------------------------------------------------
    # Direct Q4 proof:
    # native ID deliberately equals an unrelated historical TIDAL
    # queue ID. Resume must NOT bind to that queue.
    # ---------------------------------------------------------------
    direct_player = Player()
    direct_reloads = []
    direct_arms = []
    direct_scrobbles = []

    direct_ns = _load_functions(
        ["_tidal_resume_payload"],
        {
            "PAUSED_PIPELINE_RELEASED": True,
            "APP_INSTANCE": SimpleNamespace(player=direct_player),
            "_status_playback_context": lambda player: {
                "current_track_valid": True,
                "source": "qobuz",
                "current_track_id": "202",
                "context": {
                    "track_id": "202",
                    "duration": 120,
                },
            },
            "_resume_position_for_track": lambda track_id: 31.0,
            "_require_audio_output_for_playback": lambda reason: None,
            "_cancel_idle_release": lambda: None,
            "_qobuz_active_queue_id": lambda: "",
            "_set_playback_clock_position": lambda pos: None,
            "_arm_active_queue_auto_advance": (
                lambda: direct_arms.append(True)
            ),
            "start_current_scrobble": (
                lambda *args, **kwargs:
                    direct_scrobbles.append(True)
            ),
            "build_current_scrobble_track": lambda source=None: {
                "source": source
            },
            "_QUEUE_LOCK": threading.Lock(),
            "PLAY_QUEUE": ["202"],
            "QUEUE_INDEX": 0,
            "GLib": _GLib,
            "play_queue_index": (
                lambda *args, **kwargs:
                    direct_reloads.append((args, kwargs))
            ),
            "logger": _Logger(),
            "AudioOutputUnavailable": RuntimeError,
        },
    )

    direct_result = direct_ns["_tidal_resume_payload"]()

    assert direct_result["result"] == "playing"
    assert direct_result["source"] == "qobuz"
    assert direct_player.play_calls == 1
    assert direct_reloads == []
    assert direct_arms == []
    assert direct_scrobbles == []

    # ---------------------------------------------------------------
    # Q5 queued Qobuz after DAC release:
    # canonical qobuz:<id> identity must restart the same queue item.
    # ---------------------------------------------------------------
    queued_player = Player()
    queued_reloads = []

    queued_ns = _load_functions(
        ["_tidal_resume_payload"],
        {
            "PAUSED_PIPELINE_RELEASED": True,
            "APP_INSTANCE": SimpleNamespace(player=queued_player),
            "_status_playback_context": lambda player: {
                "current_track_valid": True,
                "source": "qobuz",
                "current_track_id": "qobuz:202",
                "context": {
                    "track_id": "qobuz:202",
                    "duration": 120,
                },
            },
            "_resume_position_for_track": lambda track_id: 31.0,
            "_require_audio_output_for_playback": lambda reason: None,
            "_cancel_idle_release": lambda: None,
            "_qobuz_active_queue_id": lambda: "qobuz:202",
            "_disarm_queue_auto_advance": lambda reason: None,
            "_set_playback_clock_position": lambda pos: None,
            "_arm_active_queue_auto_advance": lambda: None,
            "start_current_scrobble": lambda *args, **kwargs: None,
            "build_current_scrobble_track": lambda source=None: {
                "source": source
            },
            "_QUEUE_LOCK": threading.Lock(),
            "PLAY_QUEUE": ["qobuz:202"],
            "QUEUE_INDEX": 0,
            "GLib": _GLib,
            "play_queue_index": (
                lambda index, _resume_position=0.0:
                    queued_reloads.append(
                        (index, _resume_position)
                    )
            ),
            "logger": _Logger(),
            "AudioOutputUnavailable": RuntimeError,
        },
    )

    queued_result = queued_ns["_tidal_resume_payload"]()

    assert queued_result["result"] == "playing"
    assert queued_result["source"] == "qobuz"
    assert queued_result["restarted"] is True
    assert queued_result["position"] == 0
    assert queued_reloads == [(0, 0.0)]
    assert queued_player.play_calls == 0


def test_q9b_infinite_play_preserves_provider_boundaries():
    next_block = _function_source("play_next_track")
    append_block = _function_source(
        "_append_infinite_play_recommendations"
    )
    coordinated = _function_source(
        "_coordinated_infinite_play_refill"
    )

    assert (
        'current_source not in ("tidal", "qobuz")'
        in next_block
    )
    assert (
        "effective_provider = _effective_infinite_play_provider()"
        in next_block
    )
    assert "if current_source != effective_provider:" in next_block

    assert (
        "seed_source = _queue_item_source("
        in append_block
    )
    assert "if seed_source != provider:" in append_block
    assert "_valid_qobuz_infinite_play_seed(" in append_block

    assert (
        "effective_provider = ("
        in coordinated
    )
    assert (
        "if active_source != effective_provider:"
        in coordinated
    )
    assert "_valid_qobuz_infinite_play_seed(" in coordinated



def test_q5_shuffle_seek_and_overrun_are_provider_aware():
    assert (
        "_queue_item_source(track_id, meta)"
        in _function_source("_queue_group_key_locked")
    )
    assert (
        '("local", "tidal", "qobuz")'
        in _function_source("_arm_queue_auto_advance")
    )
    assert (
        '("local", "tidal", "qobuz")'
        in _function_source("_maybe_schedule_queue_overrun_advance")
    )
    seek = _function_source("_tidal_seek_payload")
    assert 'source in ("local", "tidal", "qobuz")' in seek
    assert 'source in ("local", "tidal")' in seek
    assert 'source == "qobuz"' in seek
    assert "bool(_qobuz_active_queue_id())" in seek


def test_q5_final_queue_stop_invalidates_qobuz_virtual_media():
    block = _function_source("_finalize_end_of_queue_playback")

    assert "_invalidate_tidal_stream_resolution(reason)" in block
    assert "_invalidate_qobuz_playback(reason)" in block
    assert "_reset_idle_playback_context()" in block


def test_q5_legacy_queue_routes_are_preserved():
    source = _source()

    for route in (
        '"/tidal/queue"',
        '"/tidal/queue/replace"',
        '"/tidal/queue/append"',
        '"/tidal/queue/insert_next"',
        '"/tidal/queue/reorder"',
        '"/tidal/next"',
        '"/tidal/prev"',
        '"/tidal/repeat"',
        '"/tidal/shuffle"',
    ):
        assert route in source

    assert "QobuzQueue" not in source
