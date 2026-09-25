from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "src/main_headless.py").read_text(encoding="utf-8")
UI = (ROOT / "src/ui_web/ui.js").read_text(encoding="utf-8")
INDEX = (ROOT / "src/ui_web/index.html").read_text(encoding="utf-8")


def py_block(name):
    marker = f"def {name}("
    start = MAIN.index(marker)
    next_def = MAIN.find("\ndef ", start + len(marker))
    next_class = MAIN.find("\nclass ", start + len(marker))
    ends = [p for p in (next_def, next_class) if p >= 0]
    return MAIN[start:min(ends) if ends else len(MAIN)]


def js_block(name):
    marker = f"function {name}("
    start = UI.index(marker)

    # Q10B only needs the source region of a top-level function.  Slicing to
    # the next top-level function avoids treating quote/braces inside JS
    # comments, regular expressions or template strings as syntax.
    next_function = UI.find("\nfunction ", start + len(marker))
    if next_function < 0:
        return UI[start:]
    return UI[start:next_function]


def test_q10b_status_contract_is_minimal_boolean():
    assert MAIN.count('"qobuz_replacement_pending": _qobuz_replacement_is_pending()') == 2
    assert 'qobuz_replacement_pending' in MAIN
    assert 'replacement_target_queue_id' not in py_block("_status_playback_context")


def test_q10b_direct_replacement_marks_before_teardown_and_binds_generation():
    block = py_block("_qobuz_test_play_payload")
    mark = block.index("_prepare_qobuz_replacement_pending(")
    invalidate = block.index("_invalidate_qobuz_playback(", mark)
    stop = block.index("APP_INSTANCE.player.stop()", invalidate)
    begin = block.index("_begin_qobuz_stream_resolution(", stop)
    bind = block.index("_bind_qobuz_replacement_generation(", begin)
    assert mark < invalidate < stop < begin < bind
    assert "preserve_replacement=replacement_request is not None" in block


def test_q10b_next_previous_share_generation_bound_lifecycle():
    next_block = py_block("_tidal_next_payload")
    prev_block = py_block("_tidal_prev_payload")
    assert '_cancel_qobuz_for_queue_transition("user-next")' in next_block
    assert '_cancel_qobuz_for_queue_transition("user-previous")' in prev_block

    cancel = py_block("_cancel_qobuz_for_queue_transition")
    next_target = cancel.index(
        'target_queue_id = _qobuz_next_replacement_target_queue_id()'
    )
    previous_target = cancel.index(
        'target_queue_id = _qobuz_previous_replacement_target_queue_id()'
    )
    mark = cancel.index("_prepare_qobuz_replacement_pending(")
    invalidate = cancel.index("_invalidate_qobuz_playback(", mark)

    assert next_target < mark
    assert previous_target < mark
    assert mark < invalidate
    assert "preserve_replacement=replacement_request is not None" in cancel


def test_q10b_eos_marks_before_stop_and_uses_same_pending_contract():
    block = py_block("install_eos_hook")
    mark = block.index("_prepare_qobuz_replacement_pending(")
    stop = block.index("player.stop()", mark)
    invalidate = block.index("_invalidate_qobuz_playback(", stop)
    assert mark < stop < invalidate
    assert "qobuz_eos_replacement_request is not None" in block


def test_q10b_matching_success_arms_hardware_commit_and_failures_clear():
    block = py_block("_complete_qobuz_test_play")
    assert "_arm_qobuz_replacement_hardware_commit(" in block
    assert '"qobuz-replacement-ready"' not in block
    assert '"qobuz-delivery-resolution-failed"' in block
    assert '"qobuz-playback-handoff-failed"' in block
    assert block.count("generation=token") >= 5
    assert block.count("target_queue_id=replacement_target_queue_id") >= 5


def test_q10b_stale_generation_cannot_clear_newer_pending_state():
    block = py_block("_clear_qobuz_replacement_pending")
    assert 'int(state.get("generation") or -1) != int(generation)' in block
    complete = py_block("_complete_qobuz_test_play")
    first_generation_check = complete.index("if not _qobuz_stream_resolution_matches(")
    first_clear = complete.index("_clear_qobuz_replacement_pending(")
    assert first_generation_check < first_clear
    prefix = complete[first_generation_check:first_clear]
    assert "return False" in prefix


def test_q10b_true_idle_invalidations_clear_pending_normally():
    invalidate = py_block("_invalidate_qobuz_playback")
    assert "preserve_replacement=False" in invalidate
    assert "if not preserve_replacement:" in invalidate
    assert "_clear_qobuz_replacement_pending(reason)" in invalidate
    assert '_invalidate_qobuz_playback("qobuz-test-stop")' in py_block("_qobuz_test_stop_payload")
    assert '_invalidate_qobuz_playback(reason)' in py_block("_finalize_end_of_queue_playback")
    assert '_invalidate_qobuz_playback("queue-clear")' in MAIN
    assert '_invalidate_qobuz_playback("qobuz-logout")' in MAIN


def test_q10b_poll_status_blocks_false_hero_and_ready_before_standby():
    block = js_block("pollStatus")
    pending = block.index("if (qobuzReplacementPending) {")
    hero = block.index("updateHomeHeroNowPlaying(s)", pending)
    standby = block.index("applyStandbyPlayerBar()", hero)
    pending_branch = block[pending:hero]

    assert "playing = statusPlaying" in pending_branch
    assert "updatePlayPauseIcon()" in pending_branch
    assert "updatePlayerInfinitePlayControl()" in pending_branch
    assert "return;" in pending_branch

    # Atomic pending state must not advance visual track identity.
    assert "q10bApplyPendingQobuzQueuePresentation" not in pending_branch
    assert "playerArt.src" not in pending_branch
    assert "playerTrack.textContent" not in pending_branch
    assert "playerArtist.textContent" not in pending_branch
    assert "currentPlayingId =" not in pending_branch
    assert "applyStandbyPlayerBar" not in pending_branch
    assert "updateHomeHeroNowPlaying" not in pending_branch
    assert "&& !statusValid" not in pending_branch

    assert pending < hero < standby


def test_q10b_restore_session_blocks_false_ready_before_standby():
    block = js_block("restoreSession")
    pending = block.index("if (qobuzReplacementPending) {")
    standby = block.index("applyStandbyPlayerBar()", pending)
    pending_branch = block[pending:standby]

    assert "playing = !!s.playing" in pending_branch
    assert "updatePlayPauseIcon()" in pending_branch
    assert "updatePlayerInfinitePlayControl()" in pending_branch
    assert "return;" in pending_branch

    # /session must also preserve the last committed presentation.
    assert "q10bApplyPendingQobuzQueuePresentation" not in pending_branch
    assert "playerArt.src" not in pending_branch
    assert "playerTrack.textContent" not in pending_branch
    assert "playerArtist.textContent" not in pending_branch
    assert "applyStandbyPlayerBar" not in pending_branch
    assert "&& sessionInvalid" not in pending_branch

    assert pending < standby


def test_q10b_play_pause_does_not_convert_transitional_idle_to_stop():
    block = js_block("togglePlayPause")
    pending = block.index("lastKnownPlaybackStatus.qobuz_replacement_pending === true")
    idle = block.index("lastKnownPlaybackStatus.current_track_valid === false", pending)
    standby = block.index("applyStandbyPlayerBar()", idle)
    assert pending < idle < standby


def test_q10b_tidal_reference_lifecycle_remains_unmodified():
    block = py_block("play_queue_index")
    tidal = block.index('if queue_source != "tidal":')
    resolution = block.index("_begin_tidal_stream_resolution(", tidal)
    handoff = block.index("player.load(uri)", resolution)
    assert resolution < handoff
    assert "qobuz_replacement_pending" not in block[tidal:handoff]


def test_q10b_q10a_cache_bust_preserves_locked_q10a_token():
    assert "/ui_web/ui.js?v=20260912_v2_0_q10a_infinite_play_pause_logo_js4" in INDEX
    assert "q10b_20260913_v2_0_q10b_qobuz_transition_js1" in INDEX


def test_q10b_queue_jump_preserves_q5_call_shape_and_infers_target():
    """Queue jump uses the shared Q10B lifecycle without changing Q5 API shape."""
    route_start = MAIN.index(
        '        if self.path.startswith("/tidal/queue/jump/"):'
    )
    route_end = MAIN.index(
        "        # -- Queue: remove track at index",
        route_start,
    )
    route = MAIN[route_start:route_end]

    assert 'QUEUE_INDEX = idx' in route
    assert '_cancel_qobuz_for_queue_transition("queue-jump")' in route
    assert route.index("QUEUE_INDEX = idx") < route.index(
        '_cancel_qobuz_for_queue_transition("queue-jump")'
    )

    cancel = py_block("_cancel_qobuz_for_queue_transition")

    assert 'elif reason == "queue-jump":' in cancel
    assert "0 <= QUEUE_INDEX < len(PLAY_QUEUE)" in cancel
    assert "jump_queue_id = str(PLAY_QUEUE[QUEUE_INDEX])" in cancel
    assert "PLAY_QUEUE_META_CACHE.get(jump_queue_id, {})" in cancel
    assert "_queue_item_source(" in cancel
    assert "target_queue_id = jump_queue_id" in cancel

    jump_branch = cancel.index('elif reason == "queue-jump":')
    mark = cancel.index(
        "_prepare_qobuz_replacement_pending(",
        jump_branch,
    )
    assert jump_branch < mark



def test_q10b_selected_mmap_running_is_hardware_commit_boundary():
    selected = py_block("_selected_alsa_pcm_running")
    assert r're.fullmatch(r"hw:(\d+)(?:,(\d+))?"' in selected
    assert '_AUDIO_PROC_ROOT / f"card{card_idx}" / f"pcm{pcm_idx}p"' in selected
    assert '"RUNNING" in status_text.upper()' in selected
    assert "PREPARED" not in selected

    committed = py_block("_qobuz_hardware_playback_committed")
    assert 'if ALSA_DRIVER == "alsa_mmap":' in committed
    assert "_selected_alsa_pcm_running() is True" in committed


def test_q10b_pending_is_armed_and_clears_only_after_hardware_commit():
    prepare = py_block("_prepare_qobuz_replacement_pending")
    assert '"armed": False' in prepare

    bind = py_block("_bind_qobuz_replacement_generation")
    assert 'state["armed"] = False' in bind

    arm = py_block("_arm_qobuz_replacement_hardware_commit")
    assert 'state["armed"] = True' in arm
    assert 'state.get("target_queue_id") != target_queue_id' in arm
    assert 'int(state.get("generation") or -1) != int(generation)' in arm

    pending = py_block("_qobuz_replacement_is_pending")
    assert "_maybe_commit_qobuz_replacement_hardware_ready()" in pending

    commit = py_block("_maybe_commit_qobuz_replacement_hardware_ready")
    assert 'not state.get("armed")' in commit
    assert "not _qobuz_hardware_playback_committed()" in commit
    assert '"qobuz-replacement-hardware-running"' in commit
    assert "generation=generation" in commit
    assert "target_queue_id=target_queue_id" in commit


def test_q10b_latest_wins_layers_on_locked_q4_busy_result():
    primitive = py_block("_qobuz_test_play_payload")

    assert "_QOBUZ_RESOLUTION_SLOTS.acquire(blocking=False)" in primitive
    assert '"qobuz_resolution_busy"' in primitive
    assert "_defer_qobuz_resolution(" not in primitive
    assert '"state": "queued"' not in primitive

    policy = py_block("_apply_qobuz_queue_resolution_policy")
    assert 'result.get("error") != "qobuz_resolution_busy"' in policy
    assert "_defer_qobuz_resolution(" in policy
    assert '"state": "queued"' in policy

    queue = py_block("play_queue_index")
    assert "_qobuz_test_play_payload(" in queue
    assert "_apply_qobuz_queue_resolution_policy(" in queue
    assert queue.index("_qobuz_test_play_payload(") < queue.index(
        "_apply_qobuz_queue_resolution_policy("
    )


def test_q10b_deferred_resolver_retains_only_newest_request():
    defer = py_block("_defer_qobuz_resolution")
    assert "_QOBUZ_DEFERRED_RESOLUTION" in defer
    assert 'current.get("request_serial")' in defer
    assert "> int(request_serial)" in defer

    drain = py_block("_drain_qobuz_deferred_resolution")
    assert "_take_qobuz_deferred_resolution()" in drain
    assert "_qobuz_queue_context_matches(queue_context)" in drain
    assert "_qobuz_test_play_payload(" in drain
    assert "_apply_qobuz_queue_resolution_policy(" in drain
    assert drain.index("_qobuz_test_play_payload(") < drain.index(
        "_apply_qobuz_queue_resolution_policy("
    )
    assert 'int(deferred.get("request_serial") or 0)' in drain

    policy = py_block("_apply_qobuz_queue_resolution_policy")
    assert '"qobuz_resolution_busy"' in policy
    assert "_defer_qobuz_resolution(" in policy


def test_q10b_true_idle_invalidation_cancels_deferred_request():
    invalidate = py_block("_invalidate_qobuz_playback")
    assert "if not preserve_replacement:" in invalidate
    assert "_clear_qobuz_deferred_resolution(reason)" in invalidate

    shutdown = py_block("_shutdown_qobuz_playback_bridge")
    assert "_clear_qobuz_deferred_resolution(reason)" in shutdown


def test_q10b_qobuz_track_change_does_not_fabricate_progress_clock():
    block = js_block("_onTrackChange")

    assert "var qobuzTransition" in block
    assert "lastKnownPlaybackStatus.qobuz_replacement_pending === true" in block
    assert 'String(lastKnownPlaybackStatus.source || "").toLowerCase() === "qobuz"' in block

    transition = block.index("if (qobuzTransition) {")
    normal = block.index("} else {", transition)

    pending_branch = block[transition:normal]

    assert "playing = false;" in pending_branch
    assert "updatePlayPauseIcon();" in pending_branch

    # No speculative Qobuz clock/progress reset before hardware RUNNING.
    assert "startTime" not in pending_branch
    assert "progressFill._elapsed" not in pending_branch
    assert "playing = true" not in pending_branch


def test_q10b_poll_status_starts_qobuz_clock_from_authoritative_position():
    block = js_block("pollStatus")
    assert 'String(s.source || "").toLowerCase() === "qobuz"' in block
    assert "applyPlaybackPosition(Number(s.position || 0), true)" in block
    assert "playing = statusPlaying;" in block


def test_q10b_qobuz_queue_jump_does_not_fabricate_playing():
    block = js_block("buildQueueRow")
    assert "var queueTrackIsQobuz" in block
    assert 'String((track && track.id) || "").indexOf("qobuz:") === 0' in block
    assert "playing   = !queueTrackIsQobuz;" in block


def test_q10b_cache_bust_adds_readiness_revision_without_losing_locked_tokens():
    assert "q10b_20260913_v2_0_q10b_qobuz_transition_js1" in INDEX
    assert "v1_4_point5_compat" in INDEX
    assert "q10b_readiness_js2" in INDEX

def test_q10b_replacement_request_propagates_to_playback_handoff():
    complete = py_block("_complete_qobuz_test_play")
    payload = py_block("_qobuz_test_play_payload")

    assert "_replacement_request=None" in complete
    assert "_replacement_request=_replacement_request" in complete
    assert "if _replacement_request is not None:" in complete
    assert "_arm_qobuz_replacement_hardware_commit(" in complete
    assert "if replacement_request is not None:" not in complete

    assert "_replacement_request=replacement_request" in payload


def test_q10b_clocktruth_selected_pcm_runtime_parse(tmp_path):
    import ast
    import re
    from pathlib import Path

    source = Path("src/main_headless.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    node = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef)
        and n.name == "_selected_alsa_pcm_running"
    )

    root = tmp_path
    status = root / "card0" / "pcm0p" / "sub0" / "status"
    status.parent.mkdir(parents=True)
    status.write_text("state: RUNNING\n", encoding="utf-8")

    namespace = {
        "re": re,
        "_AUDIO_PROC_ROOT": root,
        "ALSA_DEVICE": "hw:0,0",
    }

    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(
        compile(module, "<q10b-selected-pcm>", "exec"),
        namespace,
    )

    assert namespace["_selected_alsa_pcm_running"]() is True


def test_q10b_clocktruth_qobuz_handoff_does_not_start_clock_early():
    from pathlib import Path

    source = Path("src/main_headless.py").read_text(encoding="utf-8")

    start = source.index("def _complete_qobuz_test_play(")
    end = source.index("\ndef _qobuz_test_play_payload(", start)
    handoff = source[start:end]

    assert "_arm_qobuz_hardware_clock_commit(" in handoff
    assert handoff.index(
        "_arm_qobuz_hardware_clock_commit("
    ) < handoff.index("player.load(local_uri)")

    assert "PLAYBACK_START_TIME = time.time()" not in handoff

    assert (
        'build_current_scrobble_track("qobuz"),\n'
        '                    PLAYBACK_START_TIME'
    ) not in handoff


def test_q10b_clocktruth_status_uses_hardware_wall_clock_not_preroll():
    from pathlib import Path

    source = Path("src/main_headless.py").read_text(encoding="utf-8")

    start = source.index('if static_path == "/status":')
    end = source.index('if static_path == "/session":')
    status = source[start:end]

    assert "_maybe_commit_qobuz_hardware_clock_ready()" in status
    assert "qobuz_clock_pending" in status
    assert 'playback_source == "qobuz"' in status
    assert "time.time() - PLAYBACK_START_TIME" in status
    assert "status_playing = False" in status
    assert "raw_position = 0" in status


def test_q10b_clocktruth_session_and_invalidation_contract():
    from pathlib import Path

    source = Path("src/main_headless.py").read_text(encoding="utf-8")

    start = source.index('if static_path == "/session":')
    end = source.index("# -- Playback controls", start)
    session = source[start:end]

    assert "_maybe_commit_qobuz_hardware_clock_ready()" in session
    assert "qobuz_clock_pending" in session
    assert "session_playing = False" in session
    assert "time.time() - PLAYBACK_START_TIME" in session

    start = source.index("def _invalidate_qobuz_playback(")
    end = source.index(
        "\ndef _shutdown_qobuz_playback_bridge(",
        start,
    )
    invalidate = source[start:end]

    assert "_clear_qobuz_hardware_clock_pending(reason)" in invalidate


def test_q10b_qobuz_startup_overlap_contract():
    from pathlib import Path

    source = Path("src/main_headless.py").read_text(encoding="utf-8")

    assert 'if queue_source != "qobuz":' in source
    assert "Q10B overlap audio prep START:" in source
    assert "Q10B overlap audio prep CONFIGURED:" in source
    assert "Q10B overlap audio-ready remaining WAIT:" in source
    assert "Q10B overlap audio-ready wait fully hidden:" in source

    # The original 1500 ms safety window remains present. Q10B overlaps useful
    # provider work with that existing window rather than replacing it with a
    # shorter arbitrary delay.
    assert "1500.0 - overlap_elapsed_ms" in source

    # Q5/Q4 dispatch remains the existing primitive.
    assert "result = _qobuz_test_play_payload(" in source


def test_q10b_qobuz_segment_one_prefetch_uses_supported_fetch_callback():
    from pathlib import Path

    source = Path("src/main_headless.py").read_text(encoding="utf-8")

    assert "Q10B latency segment PREFETCH START:" in source
    assert "Q10B latency segment PREFETCH DONE:" in source
    assert "backend.fetch_decrypt_cmaf_segment(" in source
    assert "prefetched_segment_one" in source
    assert "Q10B latency segment PREFETCH HIT:" in source

    # main_headless must not seed QobuzVirtualFlacResource's private cache.
    assert "resource._cache" not in source
    assert "resource._segment_payload(" not in source


def test_q10b_warm_segment_one_cache_is_bounded_and_delivery_shape_verified():
    text = MAIN

    assert "_QOBUZ_WARM_SEGMENT_ONE_TTL_SECONDS = 180.0" in text
    assert "_QOBUZ_WARM_SEGMENT_ONE_MAX_ENTRIES = 6" in text
    assert "_QOBUZ_WARM_SEGMENT_ONE_MAX_BYTES = 24 * 1024 * 1024" in text

    assert "def _qobuz_warm_segment_one_key(" in text
    assert "getattr(delivery, \"track_id\", \"\")" in text
    assert "delivery_track_id != native_track_id" in text
    assert "expected_length = _qobuz_warm_segment_one_expected_length(delivery)" in text
    assert "len(payload) != int(key[2])" in text


def test_q10b_warm_segment_one_reuses_bytes_only_after_fresh_delivery_resolution():
    text = MAIN

    resolver_start = text.index("def _resolve_qobuz_delivery():")
    resolver_end = text.index(
        "resolver = threading.Thread(",
        resolver_start,
    )
    resolver = text[resolver_start:resolver_end]

    resolve_pos = resolver.index("delivery = backend.resolve_track_delivery(")
    cache_pos = resolver.index("_qobuz_warm_segment_one_get(")

    assert resolve_pos < cache_pos
    assert "backend.fetch_decrypt_cmaf_segment(" in resolver
    assert "_qobuz_warm_segment_one_put(" in resolver
    assert "Q10B warm segment-1 CACHE HIT:" in resolver


def test_q10b_warm_segment_one_cache_is_ram_only_and_clears_on_qobuz_logout():
    text = MAIN

    assert "_QOBUZ_WARM_SEGMENT_ONE_CACHE = {}" in text
    assert "def _clear_qobuz_warm_segment_one_cache(" in text

    logout_pos = text.index('if static_path == "/qobuz/logout":')
    logout_end = text.index(
        '# -- Login: start OAuth flow',
        logout_pos,
    )
    logout = text[logout_pos:logout_end]

    assert '_clear_qobuz_warm_segment_one_cache("qobuz-logout")' in logout
    assert 'backend.logout()' in logout
def test_q10b_pending_qobuz_keeps_last_committed_player_presentation():
    assert "function q10bApplyPendingQobuzQueuePresentation(" not in UI
    assert "q10bPendingQueuePresentationInFlight" not in UI

    poll = js_block("pollStatus")
    pending_start = poll.index("if (qobuzReplacementPending) {")
    pending_end = poll.index("updateHomeHeroNowPlaying(s);", pending_start)
    pending = poll[pending_start:pending_end]

    assert "playing = statusPlaying;" in pending
    assert "updatePlayPauseIcon();" in pending
    assert "updatePlayerInfinitePlayControl();" in pending
    assert "return;" in pending

    # Pending transport truth must not repaint the next queue row.
    assert "playerArt.src" not in pending
    assert "playerTrack.textContent" not in pending
    assert "playerArtist.textContent" not in pending
    assert "currentPlayingId =" not in pending
    assert "updateHomeHeroNowPlaying" not in pending


def test_q10b_restore_session_pending_keeps_last_committed_presentation():
    block = js_block("restoreSession")

    pending_start = block.index("if (qobuzReplacementPending) {")
    invalid_start = block.index("if (sessionInvalid) {", pending_start)
    pending = block[pending_start:invalid_start]

    assert "playing = !!s.playing;" in pending
    assert "updatePlayPauseIcon();" in pending
    assert "updatePlayerInfinitePlayControl();" in pending
    assert "return;" in pending

    assert "playerArt.src" not in pending
    assert "playerTrack.textContent" not in pending
    assert "playerArtist.textContent" not in pending
    assert "applyStandbyPlayerBar()" not in pending


def test_q10b_pending_infinite_play_uses_last_committed_provider_relation():
    visibility = js_block("shouldShowInfinitePlayUi")
    update = js_block("updatePlayerInfinitePlayControl")

    # Q10A active-media visibility is provider-aware whether playing
    # or paused. Q10B freezes that committed relation during replacement.
    assert "qobuz_replacement_pending" not in visibility
    assert "if (playing)" not in visibility
    assert (
        "return playerBarActivePlaybackSource === effectiveProvider;"
        in visibility
    )
    assert (
        'playerBarActivePlaybackSource === "tidal" ||'
        not in visibility
    )

    # Q10B overrides only the transient pending rendering result.
    assert (
        "lastKnownPlaybackStatus.qobuz_replacement_pending === true"
        in update
    )
    assert "pendingEffectiveProvider" in update
    assert (
        "playerBarActivePlaybackSource === pendingEffectiveProvider"
        in update
    )

    # Never blindly force the logo hidden merely because replacement is pending.
    pending_start = update.index(
        "lastKnownPlaybackStatus.qobuz_replacement_pending === true"
    )
    pending = update[pending_start:]
    relation = pending.index(
        "playerBarActivePlaybackSource === pendingEffectiveProvider"
    )
    assert relation >= 0


def test_q10b_track_change_freezes_qobuz_presentation_until_commit():
    block = js_block("_onTrackChange")

    transition = block.index("if (qobuzTransition) {")
    fallback = block.index("} else {", transition)
    pending = block[transition:fallback]

    assert "playing = false;" in pending
    assert "setPlayerHasActiveMedia(true);" in pending
    assert "updatePlayPauseIcon();" in pending

    # Qobuz pending must retain the old committed visual generation.
    assert "startTime =" not in pending
    assert "progressFill._elapsed =" not in pending
    assert "lastTechText" not in pending
    assert "lastTechClass" not in pending
    assert 'classList.remove("hires")' not in pending
    assert "nowPlayingQuality" not in pending
    assert 'getElementById("playerMeta")' not in pending

    normal = block[fallback:block.index("_syncHomePlayingTiles();", fallback)]

    # Non-Qobuz behavior retains the established immediate reset path.
    assert "startTime" in normal
    assert "progressFill._elapsed = 0;" in normal
    assert "lastTechText" in normal
    assert 'classList.remove("hires")' in normal
    assert "nowPlayingQuality" in normal
    assert 'getElementById("playerMeta")' in normal


def test_q10b_atomic_presentation_cache_bust_is_current():
    assert "q10b_atomic_presentation_js4" in INDEX

    # Preserve every previously qualified token.
    assert (
        "20260912_v2_0_q10a_infinite_play_pause_logo_js4"
        in INDEX
    )
    assert (
        "q10b_20260913_v2_0_q10b_qobuz_transition_js1"
        in INDEX
    )
    assert "v1_4_point5_compat" in INDEX
    assert "q10b_readiness_js2" in INDEX
    assert "q10b_pending_presentation_js3" in INDEX

def test_q10b_infinite_play_transition_latch_captures_before_playing_false():
    block = js_block("_onTrackChange")

    arm = block.index(
        "q10bBeginInfinitePlayTransitionFreeze();"
    )
    stopped = block.index(
        "playing = false;",
        arm,
    )

    assert arm < stopped


def test_q10b_infinite_play_transition_latch_freezes_central_renderer():
    update = js_block("updatePlayerInfinitePlayControl")

    latch = update.index(
        "if (q10bInfinitePlayTransitionActive) {"
    )
    frozen = update.index(
        "uiVisible = q10bInfinitePlayTransitionVisible;",
        latch,
    )
    backend_pending = update.index(
        "lastKnownPlaybackStatus.qobuz_replacement_pending === true",
        frozen,
    )

    assert latch < frozen < backend_pending


def test_q10b_infinite_play_transition_latch_captures_committed_visibility():
    begin = js_block("q10bBeginInfinitePlayTransitionFreeze")

    assert (
        "q10bInfinitePlayTransitionVisible ="
        in begin
    )
    assert (
        "shouldShowInfinitePlayUi("
        in begin
    )
    assert (
        "!!tidalInfinitePlayEnabled"
        in begin
    )
    assert (
        "q10bInfinitePlayTransitionStartTrackId"
        in begin
    )


def test_q10b_infinite_play_transition_latch_tracks_backend_pending():
    sync = js_block("q10bSyncInfinitePlayTransitionFromStatus")

    assert (
        "s.qobuz_replacement_pending === true"
        in sync
    )
    assert (
        "q10bInfinitePlayTransitionBackendPendingSeen = true;"
        in sync
    )
    assert (
        "committedDifferentQobuzTrack"
        in sync
    )
    assert "terminalState" in sync

    # Committed Qobuz status marks release-ready; it must not clear early.
    assert (
        "q10bInfinitePlayTransitionReleaseReady = true;"
        in sync
    )

    terminal = sync.index("if (terminalState) {")
    clear = sync.index(
        "q10bClearInfinitePlayTransitionFreeze();",
        terminal,
    )
    release_ready = sync.index(
        "q10bInfinitePlayTransitionReleaseReady = true;",
        clear,
    )

    assert terminal < clear < release_ready


def test_q10b_status_syncs_transition_latch_before_infinite_play_render():
    poll = js_block("pollStatus")

    sync = poll.index(
        "q10bSyncInfinitePlayTransitionFromStatus(s);"
    )
    render = poll.index(
        "updatePlayerInfinitePlayControl();",
        sync,
    )

    assert sync < render


def test_q10b_infinite_visibility_latch_cache_bust_is_current():
    assert "q10b_infinite_visibility_latch_js5" in INDEX
    assert "q10b_atomic_presentation_js4" in INDEX
    assert "q10b_pending_presentation_js3" in INDEX
    assert "q10b_readiness_js2" in INDEX

def test_q10b_infinite_play_commit_release_occurs_after_source_and_playing():
    poll = js_block("pollStatus")

    sync = poll.index(
        "q10bSyncInfinitePlayTransitionFromStatus(s);"
    )

    first_render = poll.index(
        "updatePlayerInfinitePlayControl();",
        sync,
    )

    source = poll.index(
        "setPlayerBarActivePlaybackSource(",
        first_render,
    )

    position = poll.index(
        "applyPlaybackPosition(Number(s.position || 0), true)",
        source,
    )

    clear = poll.index(
        "q10bClearInfinitePlayTransitionFreeze();",
        position,
    )

    final_render = poll.index(
        "updatePlayerInfinitePlayControl();",
        clear,
    )

    assert (
        sync
        < first_render
        < source
        < position
        < clear
        < final_render
    )


def test_q10b_commit_status_does_not_clear_latch_inside_status_sync():
    sync = js_block("q10bSyncInfinitePlayTransitionFromStatus")

    release_ready = sync.index(
        "q10bInfinitePlayTransitionReleaseReady = true;"
    )

    # The only clear in this helper is the terminal-state path.
    terminal = sync.index("if (terminalState) {")
    terminal_clear = sync.index(
        "q10bClearInfinitePlayTransitionFreeze();",
        terminal,
    )

    assert terminal_clear < release_ready
    assert (
        "q10bClearInfinitePlayTransitionFreeze();"
        not in sync[release_ready:]
    )


def test_q10b_backend_only_pending_can_arm_infinite_play_freeze():
    sync = js_block("q10bSyncInfinitePlayTransitionFromStatus")

    inactive = sync.index(
        "if (!q10bInfinitePlayTransitionActive) {"
    )
    pending = sync.index(
        "s.qobuz_replacement_pending === true",
        inactive,
    )
    capture = sync.index(
        "q10bInfinitePlayTransitionVisible =",
        pending,
    )

    assert inactive < pending < capture
    assert "shouldShowInfinitePlayUi(" in sync[capture:]


def test_q10b_infinite_commit_order_cache_bust_is_current():
    assert "q10b_infinite_commit_order_js6" in INDEX
    assert "q10b_infinite_visibility_latch_js5" in INDEX
    assert "q10b_atomic_presentation_js4" in INDEX
