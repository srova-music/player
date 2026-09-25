from dataclasses import dataclass
import http.client
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backend.qobuz_stream import (
    DEFAULT_MAX_CACHE_BYTES,
    DEFAULT_MAX_CACHE_SEGMENTS,
    DEFAULT_MAX_REQUEST_THREADS,
    LOOPBACK_HOST,
    QobuzLoopbackServer,
    QobuzPlaybackGeneration,
    QobuzRangeMalformed,
    QobuzRangeUnsatisfiable,
    QobuzStreamError,
    QobuzStreamInvalidated,
    QobuzVirtualFlacResource,
    parse_single_byte_range,
)


@dataclass(frozen=True)
class FakeSegment:
    byte_len: int


@dataclass(frozen=True)
class FakeDelivery:
    flac_header: bytes
    segment_table: tuple
    n_segments: int

    @property
    def virtual_flac_length(self):
        return len(self.flac_header) + sum(
            int(entry.byte_len) for entry in self.segment_table
        )


HEADER = b"fLaCHEAD"
SEGMENTS = {
    1: b"abcde",
    2: b"FGHIJK",
    3: b"0123456",
}


def make_delivery(segment_lengths=(5, 6, 7), header=HEADER):
    table = tuple(FakeSegment(length) for length in segment_lengths)
    return FakeDelivery(
        flac_header=header,
        segment_table=table,
        n_segments=len(table),
    )


def make_fetcher(payloads=None, calls=None):
    payloads = dict(payloads or SEGMENTS)
    calls = calls if calls is not None else []

    def fetch(_delivery, index):
        calls.append(index)
        return payloads[index]

    return fetch


def make_resource(
    *,
    delivery=None,
    payloads=None,
    calls=None,
    max_cache_segments=DEFAULT_MAX_CACHE_SEGMENTS,
    max_cache_bytes=DEFAULT_MAX_CACHE_BYTES,
):
    delivery = delivery or make_delivery()
    return QobuzVirtualFlacResource(
        delivery,
        make_fetcher(payloads=payloads, calls=calls),
        max_cache_segments=max_cache_segments,
        max_cache_bytes=max_cache_bytes,
    )


def test_virtual_total_length_and_exact_boundaries():
    resource = make_resource()

    expected = HEADER + SEGMENTS[1] + SEGMENTS[2] + SEGMENTS[3]

    assert resource.total_length == len(expected)
    assert resource.read_range(0, resource.total_length) == expected

    header_end = len(HEADER)
    seg1_end = header_end + len(SEGMENTS[1])
    seg2_end = seg1_end + len(SEGMENTS[2])

    assert resource.read_range(0, header_end) == HEADER
    assert resource.read_range(header_end, seg1_end) == SEGMENTS[1]
    assert resource.read_range(seg1_end, seg2_end) == SEGMENTS[2]
    assert resource.read_range(resource.total_length - 1, resource.total_length) == expected[-1:]


def test_virtual_range_inside_segment_and_cross_segment():
    resource = make_resource()
    expected = HEADER + SEGMENTS[1] + SEGMENTS[2] + SEGMENTS[3]

    start = len(HEADER) + 2
    end = len(HEADER) + len(SEGMENTS[1]) + 3

    assert resource.read_range(start, end) == expected[start:end]


def test_virtual_empty_and_invalid_intervals():
    resource = make_resource()

    assert resource.read_range(3, 3) == b""

    with pytest.raises(QobuzStreamError):
        resource.read_range(-1, 3)

    with pytest.raises(QobuzStreamError):
        resource.read_range(4, 3)

    with pytest.raises(QobuzStreamError):
        resource.read_range(0, resource.total_length + 1)


def test_layout_rejects_zero_segments_and_bad_lengths():
    with pytest.raises(QobuzStreamError):
        make_resource(delivery=make_delivery(segment_lengths=()))

    bad = FakeDelivery(
        flac_header=HEADER,
        segment_table=(FakeSegment(0),),
        n_segments=1,
    )
    with pytest.raises(QobuzStreamError):
        make_resource(delivery=bad)

    mismatch = FakeDelivery(
        flac_header=HEADER,
        segment_table=(FakeSegment(5),),
        n_segments=2,
    )
    with pytest.raises(QobuzStreamError):
        make_resource(delivery=mismatch)


def test_layout_rejects_non_flac_header():
    with pytest.raises(QobuzStreamError):
        make_resource(delivery=make_delivery(header=b"NOTFLAC"))


def test_segment_fetch_failure_propagates_without_disk_fallback():
    delivery = make_delivery(segment_lengths=(5,))

    def fetch(_delivery, _index):
        raise RuntimeError("network failed")

    resource = QobuzVirtualFlacResource(delivery, fetch)

    with pytest.raises(RuntimeError, match="network failed"):
        resource.read_range(len(HEADER), resource.total_length)


def test_segment_length_mismatch_fails_closed():
    delivery = make_delivery(segment_lengths=(5,))

    resource = QobuzVirtualFlacResource(
        delivery,
        lambda _delivery, _index: b"bad",
    )

    with pytest.raises(QobuzStreamError, match="length"):
        resource.read_range(len(HEADER), resource.total_length)


def test_cache_hit_miss_and_lru_eviction():
    calls = []
    resource = make_resource(
        calls=calls,
        max_cache_segments=1,
        max_cache_bytes=1024,
    )

    h = len(HEADER)
    s1_end = h + len(SEGMENTS[1])
    s2_end = s1_end + len(SEGMENTS[2])

    assert resource.read_range(h, s1_end) == SEGMENTS[1]
    assert resource.read_range(h, s1_end) == SEGMENTS[1]
    assert calls == [1]

    assert resource.read_range(s1_end, s2_end) == SEGMENTS[2]
    assert calls == [1, 2]

    info = resource.cache_info()
    assert info["segments"] == 1
    assert info["bytes"] == len(SEGMENTS[2])

    assert resource.read_range(h, s1_end) == SEGMENTS[1]
    assert calls == [1, 2, 1]


def test_segment_larger_than_byte_budget_is_served_but_not_cached():
    calls = []
    delivery = make_delivery(segment_lengths=(5,))
    resource = QobuzVirtualFlacResource(
        delivery,
        make_fetcher(payloads={1: b"abcde"}, calls=calls),
        max_cache_segments=3,
        max_cache_bytes=4,
    )

    h = len(HEADER)
    assert resource.read_range(h, resource.total_length) == b"abcde"
    assert resource.read_range(h, resource.total_length) == b"abcde"

    assert calls == [1, 1]
    assert resource.cache_info()["segments"] == 0
    assert resource.cache_info()["bytes"] == 0


def test_invalidation_clears_cache_and_blocks_future_reads():
    resource = make_resource()

    h = len(HEADER)
    resource.read_range(h, h + len(SEGMENTS[1]))
    assert resource.cache_info()["segments"] == 1

    resource.invalidate()

    info = resource.cache_info()
    assert info["closed"] is True
    assert info["segments"] == 0
    assert info["bytes"] == 0

    with pytest.raises(QobuzStreamInvalidated):
        resource.read_range(0, 1)


def test_generation_track_b_replaces_track_a_deterministically():
    gate = QobuzPlaybackGeneration()

    a = ("track-a", 27)
    b = ("track-b", 27)

    token_a = gate.begin(a)
    token_b = gate.begin(b)

    assert gate.matches(token_a, a) is False
    assert gate.matches(token_b, b) is True
    assert gate.matches(token_b, b, consume=True) is True
    assert gate.matches(token_b, b) is False


def test_generation_stop_invalidates_late_completion():
    gate = QobuzPlaybackGeneration()

    identity = ("track-a", 27)
    token = gate.begin(identity)
    gate.invalidate("stop")

    assert gate.matches(token, identity) is False
    assert gate.pending is False


def test_generation_logout_invalidates_late_completion():
    gate = QobuzPlaybackGeneration()

    identity = ("track-a", 27)
    token = gate.begin(identity)
    gate.invalidate("logout")

    assert gate.matches(token, identity, consume=True) is False


@pytest.mark.parametrize(
    ("value", "total", "expected"),
    [
        ("bytes=0-0", 10, (0, 1)),
        ("bytes=2-5", 10, (2, 6)),
        ("bytes=7-", 10, (7, 10)),
        ("bytes=-3", 10, (7, 10)),
        ("bytes=8-99", 10, (8, 10)),
    ],
)
def test_parse_single_byte_range(value, total, expected):
    assert parse_single_byte_range(value, total) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "items=0-1",
        "bytes=",
        "bytes=abc-3",
        "bytes=0-1,3-4",
    ],
)
def test_parse_single_byte_range_rejects_malformed(value):
    with pytest.raises(QobuzRangeMalformed):
        parse_single_byte_range(value, 10)


@pytest.mark.parametrize(
    "value",
    [
        "bytes=10-",
        "bytes=5-4",
        "bytes=-0",
    ],
)
def test_parse_single_byte_range_rejects_unsatisfiable(value):
    with pytest.raises(QobuzRangeUnsatisfiable):
        parse_single_byte_range(value, 10)


def read_url(url, *, method="GET", headers=None):
    req = urllib.request.Request(
        url,
        method=method,
        headers=headers or {},
    )
    with urllib.request.urlopen(req, timeout=3.0) as response:
        return (
            response.status,
            dict(response.headers.items()),
            response.read(),
        )


def test_loopback_server_binds_ipv4_loopback_only():
    server = QobuzLoopbackServer()
    try:
        port = server.start()
        assert server.host == "127.0.0.1"
        assert isinstance(port, int)
        assert port > 0

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2.0)
        conn.request("GET", "/not-active")
        response = conn.getresponse()
        assert response.status == 404
        response.read()
        conn.close()
    finally:
        server.stop()


def test_http_head_full_get_and_single_ranges():
    resource = make_resource()
    expected = HEADER + SEGMENTS[1] + SEGMENTS[2] + SEGMENTS[3]
    server = QobuzLoopbackServer()

    try:
        url = server.publish(resource)

        status, headers, body = read_url(url, method="HEAD")
        assert status == 200
        assert body == b""
        assert int(headers["Content-Length"]) == len(expected)
        assert headers["Accept-Ranges"] == "bytes"
        assert headers["Content-Type"] == "audio/flac"

        status, headers, body = read_url(url)
        assert status == 200
        assert body == expected
        assert int(headers["Content-Length"]) == len(expected)

        status, headers, body = read_url(
            url,
            headers={"Range": "bytes=2-11"},
        )
        assert status == 206
        assert body == expected[2:12]
        assert headers["Content-Range"] == (
            f"bytes 2-11/{len(expected)}"
        )
        assert int(headers["Content-Length"]) == 10

        start = len(HEADER) + 2
        status, headers, body = read_url(
            url,
            headers={"Range": f"bytes={start}-"},
        )
        assert status == 206
        assert body == expected[start:]

        status, headers, body = read_url(
            url,
            headers={"Range": "bytes=-4"},
        )
        assert status == 206
        assert body == expected[-4:]

        eof = len(expected) - 1
        status, headers, body = read_url(
            url,
            headers={"Range": f"bytes={eof}-{eof}"},
        )
        assert status == 206
        assert body == expected[-1:]
    finally:
        server.stop()


def test_http_cross_segment_range_is_exact():
    resource = make_resource()
    expected = HEADER + SEGMENTS[1] + SEGMENTS[2] + SEGMENTS[3]
    server = QobuzLoopbackServer()

    try:
        url = server.publish(resource)
        start = len(HEADER) + len(SEGMENTS[1]) - 2
        end_inclusive = start + 8

        status, headers, body = read_url(
            url,
            headers={
                "Range": f"bytes={start}-{end_inclusive}",
            },
        )

        assert status == 206
        assert body == expected[start:end_inclusive + 1]
        assert headers["Content-Range"] == (
            f"bytes {start}-{end_inclusive}/{len(expected)}"
        )
    finally:
        server.stop()


def test_http_malformed_and_unsatisfiable_ranges_fail_deterministically():
    resource = make_resource()
    server = QobuzLoopbackServer()

    try:
        url = server.publish(resource)

        with pytest.raises(urllib.error.HTTPError) as malformed:
            read_url(
                url,
                headers={"Range": "bytes=0-1,3-4"},
            )
        assert malformed.value.code == 400

        total = resource.total_length
        with pytest.raises(urllib.error.HTTPError) as unsat:
            read_url(
                url,
                headers={"Range": f"bytes={total}-"},
            )
        assert unsat.value.code == 416
        assert unsat.value.headers["Content-Range"] == (
            f"bytes */{total}"
        )
    finally:
        server.stop()


def test_publish_replaces_and_invalidates_old_opaque_resource():
    first = make_resource()
    second = make_resource()
    server = QobuzLoopbackServer()

    try:
        first_url = server.publish(first)
        second_url = server.publish(second)

        assert first.closed is True
        assert second.closed is False
        assert first_url != second_url

        with pytest.raises(urllib.error.HTTPError) as old:
            read_url(first_url)
        assert old.value.code == 404

        status, _headers, body = read_url(second_url)
        assert status == 200
        assert body.startswith(b"fLaC")
    finally:
        server.stop()


def test_invalidation_closes_inflight_stale_connection():
    fetch_started = threading.Event()
    release_fetch = threading.Event()

    payload = b"x" * 64
    delivery = make_delivery(segment_lengths=(len(payload),))

    def slow_fetch(_delivery, _index):
        fetch_started.set()
        assert release_fetch.wait(timeout=3.0)
        return payload

    resource = QobuzVirtualFlacResource(
        delivery,
        slow_fetch,
        max_cache_segments=1,
        max_cache_bytes=1024,
    )
    server = QobuzLoopbackServer()
    outcome = {}

    try:
        url = server.publish(resource)

        def client():
            try:
                with urllib.request.urlopen(url, timeout=4.0) as response:
                    outcome["status"] = response.status
                    outcome["body"] = response.read()
            except Exception as exc:
                outcome["error"] = type(exc).__name__

        thread = threading.Thread(target=client, daemon=True)
        thread.start()

        assert fetch_started.wait(timeout=3.0)

        server.invalidate()
        assert resource.closed is True
        assert server.has_active_resource is False

        release_fetch.set()
        thread.join(timeout=4.0)

        full = HEADER + payload
        assert outcome.get("body") != full
        assert not thread.is_alive()
    finally:
        release_fetch.set()
        server.stop()


def test_server_stop_invalidates_resource_and_joins_listener():
    resource = make_resource()
    server = QobuzLoopbackServer()

    server.publish(resource)
    assert server.running is True
    assert server.has_active_resource is True

    server.stop()

    assert server.running is False
    assert resource.closed is True
    assert resource.cache_info()["segments"] == 0


def test_q4_stream_module_keeps_provider_and_player_layers_separate():
    root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..")
    )
    source = open(
        os.path.join(root, "src", "backend", "qobuz_stream.py"),
        "r",
        encoding="utf-8",
    ).read().lower()

    assert "player.load" not in source
    assert "qobuzbackend" not in source
    assert "signed delivery" in source
    assert "threadinghttpserver" in source
    assert '"127.0.0.1"' in source

def _main_headless_source():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return open(
        os.path.join(root, "src", "main_headless.py"),
        "r",
        encoding="utf-8",
    ).read()


def test_q4_main_handoff_uses_existing_player_load_and_no_second_engine():
    source = _main_headless_source()

    start = source.index("def _complete_qobuz_test_play(")
    end = source.index("\ndef _qobuz_test_play_payload(", start)
    block = source[start:end]

    assert "QobuzVirtualFlacResource" in block
    assert "server.publish(resource)" in block
    assert "player.load(local_uri)" in block
    assert "player.play()" in block
    assert "create_audio_engine" not in block
    assert "appsrc" not in block.lower()
    assert "fdsrc" not in block.lower()


def test_q4_status_classifies_active_qobuz_as_qobuz_not_tidal():
    source = _main_headless_source()

    start = source.index("def _status_playback_context(")
    end = source.index("\ndef ", start + 1)
    block = source[start:end]

    assert "if _qobuz_playback_is_active():" in block
    assert '"source": "qobuz"' in block


def test_q4_existing_seek_endpoint_accepts_qobuz_and_has_qobuz_mmap_path():
    source = _main_headless_source()

    start = source.index("def _tidal_seek_payload(")
    end = source.index("\ndef ", start + 1)
    block = source[start:end]

    assert '("local", "tidal", "qobuz")' in block
    assert 'if source == "qobuz":' in block
    assert "player.pause()" in block
    assert "player.seek(target)" in block
    assert "player.play()" in block


def test_q4_control_routes_never_return_opaque_media_uri():
    source = _main_headless_source()

    assert '"/qobuz/test-play"' in source
    assert '"/qobuz/test-stop"' in source
    assert '"/qobuz/test-status"' in source

    start = source.index("def _qobuz_test_play_payload(")
    end = source.index("\ndef _qobuz_test_stop_payload(", start)
    play_block = source[start:end]

    start = source.index("def _qobuz_test_status_payload(")
    end = source.index("\ndef play_queue_index(", start)
    status_block = source[start:end]

    assert "local_uri" not in play_block
    assert "local_uri" not in status_block
    assert '"uri"' not in play_block
    assert '"uri"' not in status_block


def test_q4_replacement_logout_source_change_and_shutdown_invalidate():
    source = _main_headless_source()

    required = (
        '_invalidate_qobuz_playback("qobuz-track-replacement")',
        '_invalidate_qobuz_playback("local-playback")',
        '_invalidate_qobuz_playback("radio-start")',
        '_invalidate_qobuz_playback("tidal-playback")',
        '_invalidate_qobuz_playback("queue-clear")',
        '_invalidate_qobuz_playback("dac-release")',
        '_invalidate_qobuz_playback("direct-tidal-selection")',
        '_invalidate_qobuz_playback("local-test-playback")',
        '_invalidate_qobuz_playback("queue-replace")',
        '_invalidate_qobuz_playback("qobuz-logout")',
        '_shutdown_qobuz_playback_bridge("service-restart")',
        '_shutdown_qobuz_playback_bridge("main-loop-exit")',
    )

    for item in required:
        assert item in source


def test_q4_keeps_q3_provider_crypto_layer_unchanged_in_responsibility():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    qobuz = open(
        os.path.join(root, "src", "backend", "qobuz.py"),
        "r",
        encoding="utf-8",
    ).read().lower()

    cmaf = open(
        os.path.join(root, "src", "backend", "qobuz_cmaf.py"),
        "r",
        encoding="utf-8",
    ).read().lower()

    assert "player.load" not in qobuz
    assert "player.load" not in cmaf
    assert "httpserver" not in qobuz
    assert "httpserver" not in cmaf

def test_loopback_request_threads_have_hard_concurrency_limit():
    server = QobuzLoopbackServer()
    clients = []

    try:
        port = server.start()
        assert port > 0

        with server._lock:
            httpd = server._httpd
        assert httpd is not None

        # Do not send an HTTP request line. Each accepted socket therefore
        # occupies one request handler until the client closes it.
        for _ in range(DEFAULT_MAX_REQUEST_THREADS + 4):
            sock = socket.create_connection(
                ("127.0.0.1", port),
                timeout=1.0,
            )
            clients.append(sock)

        deadline = time.monotonic() + 2.0
        stats = None

        while time.monotonic() < deadline:
            stats = httpd.request_thread_stats
            if stats["active"] == DEFAULT_MAX_REQUEST_THREADS:
                break
            time.sleep(0.01)

        assert stats is not None
        assert stats["limit"] == DEFAULT_MAX_REQUEST_THREADS
        assert stats["active"] <= DEFAULT_MAX_REQUEST_THREADS
        assert stats["peak"] == DEFAULT_MAX_REQUEST_THREADS

        # Give the listener an additional scheduling window; it still must
        # never exceed the fixed handler-thread ceiling.
        time.sleep(0.15)
        stats = httpd.request_thread_stats
        assert stats["active"] <= DEFAULT_MAX_REQUEST_THREADS
        assert stats["peak"] <= DEFAULT_MAX_REQUEST_THREADS

    finally:
        for sock in clients:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

        server.stop()


def test_q4_qobuz_resolution_workers_are_statically_bounded():
    source = _main_headless_source()

    assert "_QOBUZ_MAX_RESOLUTION_THREADS = 2" in source
    assert "_QOBUZ_RESOLUTION_SLOTS = threading.BoundedSemaphore(" in source
    assert "_QOBUZ_RESOLUTION_SLOTS.acquire(blocking=False)" in source
    assert '"qobuz_resolution_busy"' in source
    assert "_QOBUZ_RESOLUTION_SLOTS.release()" in source



def test_qobuz_eos_hook_distinguishes_direct_proof_and_shared_queue():
    """Direct Q4 proof stays isolated; queued Qobuz advances Q5 shared queue."""
    from pathlib import Path
    source = (
        Path(__file__).resolve().parents[1] / "src" / "main_headless.py"
    ).read_text(encoding="utf-8")

    start = source.index("def install_eos_hook():")
    end = source.index("\ndef _cancel_idle_release(", start)
    block = source[start:end]

    assert "_qobuz_playback_is_active()" in block
    assert "_qobuz_active_queue_id()" in block
    assert '_invalidate_qobuz_playback("qobuz-queue-eos")' in block
    assert "Queued Qobuz EOS advancing shared queue" in block
    assert "Direct Qobuz proof EOS observed" in block
    assert "play_next_track()" in block
    assert "player.stop()" in block

    assert (
        block.index("original(*args, **kwargs)")
        < block.index("if _qobuz_playback_is_active():")
    )


def test_q4_resolver_refreshes_only_ephemeral_cmaf_before_delivery():
    """Each Q4 track gets a fresh ephemeral CMAF playback session."""
    import ast
    from pathlib import Path

    source_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "main_headless.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    play_payload = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_qobuz_test_play_payload"
    )

    resolver = next(
        node
        for node in ast.walk(play_payload)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_resolve_qobuz_delivery"
    )

    discard_calls = [
        node
        for node in ast.walk(resolver)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_discard_cmaf_session"
    ]

    resolve_calls = [
        node
        for node in ast.walk(resolver)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "resolve_track_delivery"
    ]

    assert len(discard_calls) == 1
    assert len(resolve_calls) == 1
    assert discard_calls[0].lineno < resolve_calls[0].lineno

    attributes = {
        node.attr
        for node in ast.walk(resolver)
        if isinstance(node, ast.Attribute)
    }

    assert "_cmaf_lock" in attributes
    assert "_cmaf_session" in attributes
    assert "_discard_cmaf_session" in attributes
    assert "resolve_track_delivery" in attributes

    string_constants = {
        node.value
        for node in ast.walk(resolver)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
    }

    assert "session_id" in string_constants

    # The Q4 resolver may refresh only the ephemeral CMAF playback session.
    # It must not alter persistent login/auth/session storage.
    forbidden_calls = {
        "logout",
        "save_session",
        "_save_session",
        "clear_session",
        "_clear_session",
        "restore_session",
    }

    called_attributes = {
        node.func.attr
        for node in ast.walk(resolver)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
    }

    assert not (called_attributes & forbidden_calls)

    assert "qobuz_session.json" not in source[
        resolver.lineno - 1:
        resolver.end_lineno
    ]


def test_q4_resolver_serializes_http_rotation_and_delivery_resolution():
    """Q4 rotates stale HTTP transport without resolver races."""
    import ast
    from pathlib import Path

    source_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "main_headless.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    module_assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
    ]

    lock_assignment = next(
        node
        for node in module_assignments
        if any(
            isinstance(target, ast.Name)
            and target.id == "_QOBUZ_DELIVERY_HTTP_LOCK"
            for target in node.targets
        )
    )

    assert isinstance(lock_assignment.value, ast.Call)
    assert isinstance(lock_assignment.value.func, ast.Attribute)
    assert isinstance(lock_assignment.value.func.value, ast.Name)
    assert lock_assignment.value.func.value.id == "threading"
    assert lock_assignment.value.func.attr == "Lock"

    payload = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_qobuz_test_play_payload"
    )

    resolver = next(
        node
        for node in ast.walk(payload)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_resolve_qobuz_delivery"
    )

    http_lock_with = next(
        node
        for node in ast.walk(resolver)
        if isinstance(node, ast.With)
        and any(
            isinstance(item.context_expr, ast.Name)
            and item.context_expr.id == "_QOBUZ_DELIVERY_HTTP_LOCK"
            for item in node.items
        )
    )

    resolve_calls = [
        node
        for node in ast.walk(http_lock_with)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "resolve_track_delivery"
    ]

    build_calls = [
        node
        for node in ast.walk(http_lock_with)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_build_http_session"
    ]

    discard_calls = [
        node
        for node in ast.walk(http_lock_with)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_discard_cmaf_session"
    ]

    close_calls = [
        node
        for node in ast.walk(http_lock_with)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "close"
    ]

    assert len(build_calls) == 1
    assert len(discard_calls) == 1
    assert len(resolve_calls) == 1
    assert len(close_calls) == 1

    assert build_calls[0].lineno < discard_calls[0].lineno
    assert discard_calls[0].lineno < resolve_calls[0].lineno
    assert resolve_calls[0].lineno < close_calls[0].lineno

    # The retired transport must be closed from a finally block so both
    # successful and failed delivery resolutions retire it.
    enclosing_finally = [
        node
        for node in ast.walk(http_lock_with)
        if isinstance(node, ast.Try)
        and any(
            close_call in list(ast.walk(node))
            for close_call in close_calls
        )
        and node.finalbody
    ]

    assert enclosing_finally

    attrs = {
        node.attr
        for node in ast.walk(http_lock_with)
        if isinstance(node, ast.Attribute)
    }

    assert "_http" in attrs
    assert "_build_http_session" in attrs
    assert "_cmaf_lock" in attrs
    assert "_cmaf_session" in attrs
    assert "_discard_cmaf_session" in attrs
    assert "resolve_track_delivery" in attrs

    called_attrs = {
        node.func.attr
        for node in ast.walk(http_lock_with)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
    }

    forbidden = {
        "logout",
        "restore_session",
        "_save_session",
        "_atomic_json_write",
        "_expire_service_cache",
    }

    assert not (called_attrs & forbidden)


def test_q4_http_rotation_remains_inside_bounded_resolver_worker():
    """Transport rotation must not create another unbounded worker."""
    import ast
    from pathlib import Path

    source_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "main_headless.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    payload = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_qobuz_test_play_payload"
    )

    resolver = next(
        node
        for node in ast.walk(payload)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_resolve_qobuz_delivery"
    )

    http_lock_names = [
        node
        for node in ast.walk(resolver)
        if isinstance(node, ast.Name)
        and node.id == "_QOBUZ_DELIVERY_HTTP_LOCK"
    ]

    assert http_lock_names

    nested_thread_creation = [
        node
        for node in ast.walk(resolver)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "threading"
        and node.func.attr == "Thread"
    ]

    assert nested_thread_creation == []

    # The outer Q4 admission path remains semaphore bounded.
    acquire_calls = [
        node
        for node in ast.walk(payload)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "acquire"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "_QOBUZ_RESOLUTION_SLOTS"
    ]

    release_calls = [
        node
        for node in ast.walk(payload)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "release"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "_QOBUZ_RESOLUTION_SLOTS"
    ]

    assert len(acquire_calls) == 1
    assert len(release_calls) >= 2
