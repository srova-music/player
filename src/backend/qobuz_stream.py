"""Loopback-only virtual FLAC playback bridge for Qobuz CMAF delivery.

This module is intentionally independent from the Qobuz authentication/CMAF
implementation.  It receives an already-resolved delivery object plus a
segment-fetch callback and exposes the resulting logical FLAC byte space over
an ephemeral IPv4 loopback HTTP resource.

No provider credentials, signed delivery URLs, content keys, or decrypted
media are persisted here.
"""

from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import secrets
import socket
import threading
from urllib.parse import urlsplit


LOOPBACK_HOST = "127.0.0.1"
DEFAULT_MAX_CACHE_SEGMENTS = 3
DEFAULT_MAX_CACHE_BYTES = 96 * 1024 * 1024
DEFAULT_MAX_REQUEST_THREADS = 8


class QobuzStreamError(RuntimeError):
    """Base error for the local virtual FLAC bridge."""


class QobuzStreamInvalidated(QobuzStreamError):
    """Raised when a request refers to an invalidated virtual stream."""


class QobuzRangeMalformed(QobuzStreamError):
    """Raised when an HTTP Range header is syntactically unsupported."""


class QobuzRangeUnsatisfiable(QobuzStreamError):
    """Raised when an HTTP byte range cannot intersect the resource."""


class QobuzPlaybackGeneration:
    """Small deterministic generation gate for asynchronous stream resolution."""

    def __init__(self):
        self._lock = threading.Lock()
        self._generation = 0
        self._pending = None

    @staticmethod
    def _identity(identity):
        if isinstance(identity, tuple):
            return tuple(identity)
        if isinstance(identity, list):
            return tuple(identity)
        return (identity,)

    def begin(self, identity):
        normalized = self._identity(identity)
        with self._lock:
            self._generation += 1
            token = self._generation
            self._pending = (token, normalized)
            return token

    def invalidate(self, reason=None):
        del reason
        with self._lock:
            self._generation += 1
            self._pending = None
            return self._generation

    def matches(self, token, identity, consume=False):
        expected = (int(token), self._identity(identity))
        with self._lock:
            if self._pending != expected:
                return False
            if consume:
                self._pending = None
            return True

    @property
    def generation(self):
        with self._lock:
            return int(self._generation)

    @property
    def pending(self):
        with self._lock:
            return self._pending is not None


class QobuzVirtualFlacResource:
    """Map Q3 FLAC header/segments into one seekable virtual byte resource."""

    def __init__(
        self,
        delivery,
        segment_fetcher,
        *,
        max_cache_segments=DEFAULT_MAX_CACHE_SEGMENTS,
        max_cache_bytes=DEFAULT_MAX_CACHE_BYTES,
    ):
        if delivery is None:
            raise QobuzStreamError("delivery is required")
        if not callable(segment_fetcher):
            raise QobuzStreamError("segment_fetcher must be callable")

        try:
            header = bytes(delivery.flac_header)
            table = tuple(delivery.segment_table)
            n_segments = int(delivery.n_segments)
        except Exception as exc:
            raise QobuzStreamError("delivery layout is invalid") from exc

        if not header or not header.startswith(b"fLaC"):
            raise QobuzStreamError("virtual FLAC header is invalid")
        if not table:
            raise QobuzStreamError("virtual FLAC has no audio segments")
        if n_segments != len(table):
            raise QobuzStreamError("segment count does not match delivery layout")

        lengths = []
        for entry in table:
            try:
                byte_len = int(entry.byte_len)
            except Exception as exc:
                raise QobuzStreamError("segment byte length is invalid") from exc
            if byte_len <= 0:
                raise QobuzStreamError("segment byte length must be positive")
            lengths.append(byte_len)

        try:
            max_cache_segments = int(max_cache_segments)
            max_cache_bytes = int(max_cache_bytes)
        except (TypeError, ValueError) as exc:
            raise QobuzStreamError("cache bounds must be integers") from exc

        if max_cache_segments < 0 or max_cache_bytes < 0:
            raise QobuzStreamError("cache bounds must not be negative")

        self.delivery = delivery
        self._segment_fetcher = segment_fetcher
        self.flac_header = header
        self.segment_lengths = tuple(lengths)

        self.max_cache_segments = max_cache_segments
        self.max_cache_bytes = max_cache_bytes

        offset = len(self.flac_header)
        layout = []
        for index, byte_len in enumerate(self.segment_lengths, start=1):
            start = offset
            end = start + byte_len
            layout.append((start, end, index))
            offset = end

        self._segment_layout = tuple(layout)
        self.total_length = offset

        declared_length = getattr(delivery, "virtual_flac_length", None)
        if declared_length is not None:
            try:
                declared_length = int(declared_length)
            except (TypeError, ValueError) as exc:
                raise QobuzStreamError(
                    "declared virtual FLAC length is invalid"
                ) from exc
            if declared_length != self.total_length:
                raise QobuzStreamError(
                    "declared virtual FLAC length does not match layout"
                )

        self._state_lock = threading.RLock()
        self._segment_fetch_lock = threading.Lock()
        self._cache = OrderedDict()
        self._cache_bytes = 0
        self._closed = False

    @property
    def closed(self):
        with self._state_lock:
            return bool(self._closed)

    def invalidate(self):
        with self._state_lock:
            self._closed = True
            self._cache.clear()
            self._cache_bytes = 0

    def cache_info(self):
        with self._state_lock:
            return {
                "segments": len(self._cache),
                "bytes": int(self._cache_bytes),
                "max_segments": int(self.max_cache_segments),
                "max_bytes": int(self.max_cache_bytes),
                "closed": bool(self._closed),
            }

    def _ensure_open(self):
        with self._state_lock:
            if self._closed:
                raise QobuzStreamInvalidated("virtual FLAC stream is invalidated")

    def _cached_segment_locked(self, segment_index):
        payload = self._cache.get(segment_index)
        if payload is None:
            return None
        self._cache.move_to_end(segment_index)
        return payload

    def _segment_payload(self, segment_index):
        segment_index = int(segment_index)
        if not 1 <= segment_index <= len(self.segment_lengths):
            raise QobuzStreamError("segment index is out of range")

        with self._state_lock:
            if self._closed:
                raise QobuzStreamInvalidated(
                    "virtual FLAC stream is invalidated"
                )
            cached = self._cached_segment_locked(segment_index)
            if cached is not None:
                return cached

        # Only one cache miss is fetched at a time.  The state lock is not held
        # during network I/O, so invalidate() can immediately mark the stream
        # closed while a slow segment request is still in flight.
        with self._segment_fetch_lock:
            with self._state_lock:
                if self._closed:
                    raise QobuzStreamInvalidated(
                        "virtual FLAC stream is invalidated"
                    )
                cached = self._cached_segment_locked(segment_index)
                if cached is not None:
                    return cached

            payload = self._segment_fetcher(self.delivery, segment_index)
            payload = bytes(payload)
            expected = self.segment_lengths[segment_index - 1]
            if len(payload) != expected:
                raise QobuzStreamError(
                    "decrypted segment length does not match virtual layout"
                )

            with self._state_lock:
                if self._closed:
                    raise QobuzStreamInvalidated(
                        "virtual FLAC stream was invalidated during fetch"
                    )

                # An individual segment larger than the byte budget is served
                # normally but never cached.  This preserves a hard memory
                # cache bound without rejecting a valid Q3 segment.
                if (
                    self.max_cache_segments > 0
                    and self.max_cache_bytes > 0
                    and len(payload) <= self.max_cache_bytes
                ):
                    self._cache[segment_index] = payload
                    self._cache.move_to_end(segment_index)
                    self._cache_bytes += len(payload)

                    while (
                        len(self._cache) > self.max_cache_segments
                        or self._cache_bytes > self.max_cache_bytes
                    ):
                        _old_index, old_payload = self._cache.popitem(last=False)
                        self._cache_bytes -= len(old_payload)

            return payload

    def iter_range(self, start, end):
        """Yield exact bytes for the half-open virtual interval [start, end)."""
        try:
            start = int(start)
            end = int(end)
        except (TypeError, ValueError) as exc:
            raise QobuzStreamError("virtual byte interval is invalid") from exc

        if start < 0 or end < 0 or start > end or end > self.total_length:
            raise QobuzStreamError("virtual byte interval is out of bounds")
        if start == end:
            return

        self._ensure_open()
        cursor = start
        header_len = len(self.flac_header)

        if cursor < header_len:
            header_end = min(end, header_len)
            chunk = self.flac_header[cursor:header_end]
            if chunk:
                self._ensure_open()
                yield chunk
            cursor = header_end

        if cursor >= end:
            return

        for segment_start, segment_end, segment_index in self._segment_layout:
            if segment_end <= cursor:
                continue
            if segment_start >= end:
                break

            overlap_start = max(cursor, segment_start)
            overlap_end = min(end, segment_end)
            if overlap_start >= overlap_end:
                continue

            payload = self._segment_payload(segment_index)
            local_start = overlap_start - segment_start
            local_end = overlap_end - segment_start
            chunk = payload[local_start:local_end]

            if len(chunk) != overlap_end - overlap_start:
                raise QobuzStreamError("virtual FLAC range mapping failed")

            self._ensure_open()
            if chunk:
                yield chunk
            cursor = overlap_end

            if cursor >= end:
                break

        if cursor != end:
            raise QobuzStreamError("virtual FLAC range was not fully mapped")

    def read_range(self, start, end):
        return b"".join(self.iter_range(start, end))


def parse_single_byte_range(value, total_length):
    """Parse one HTTP bytes range and return a half-open [start, end) pair."""
    total_length = int(total_length)
    if total_length <= 0:
        raise QobuzRangeUnsatisfiable("resource is empty")
    if not isinstance(value, str):
        raise QobuzRangeMalformed("Range header must be text")

    value = value.strip()
    if not value.startswith("bytes="):
        raise QobuzRangeMalformed("only byte ranges are supported")

    spec = value[6:].strip()
    if not spec or "," in spec or "-" not in spec:
        raise QobuzRangeMalformed("only one byte range is supported")

    first, last = spec.split("-", 1)
    first = first.strip()
    last = last.strip()

    if not first:
        if not last.isdigit():
            raise QobuzRangeMalformed("suffix byte range is invalid")
        suffix = int(last)
        if suffix <= 0:
            raise QobuzRangeUnsatisfiable("suffix byte range is empty")
        start = max(0, total_length - suffix)
        return start, total_length

    if not first.isdigit():
        raise QobuzRangeMalformed("byte range start is invalid")

    start = int(first)
    if start >= total_length:
        raise QobuzRangeUnsatisfiable("byte range starts beyond EOF")

    if not last:
        return start, total_length

    if not last.isdigit():
        raise QobuzRangeMalformed("byte range end is invalid")

    inclusive_end = int(last)
    if inclusive_end < start:
        raise QobuzRangeUnsatisfiable("byte range end precedes start")

    inclusive_end = min(inclusive_end, total_length - 1)
    return start, inclusive_end + 1


class _QobuzLoopbackHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self):
        self._resource_lock = threading.RLock()
        self._resource = None
        self._token = None
        self._handlers_lock = threading.Lock()
        self._handlers = set()

        # ThreadingHTTPServer is unbounded by default. Q4 deliberately caps
        # concurrent request handlers so a local client cannot create an
        # unlimited number of worker threads.
        self._request_slots = threading.BoundedSemaphore(
            DEFAULT_MAX_REQUEST_THREADS
        )
        self._request_threads_lock = threading.Lock()
        self._request_threads_active = 0
        self._request_threads_peak = 0

        super().__init__(
            (LOOPBACK_HOST, 0),
            _QobuzLoopbackRequestHandler,
        )

        host, _port = self.server_address[:2]
        if host != LOOPBACK_HOST:
            super().server_close()
            raise QobuzStreamError("loopback server did not bind to IPv4 loopback")

    @property
    def request_thread_stats(self):
        with self._request_threads_lock:
            return {
                "active": int(self._request_threads_active),
                "peak": int(self._request_threads_peak),
                "limit": int(DEFAULT_MAX_REQUEST_THREADS),
            }

    def process_request(self, request, client_address):
        # Acquire before ThreadingMixIn creates the worker. When the limit is
        # reached, the listener blocks here instead of creating another thread.
        self._request_slots.acquire()
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        with self._request_threads_lock:
            self._request_threads_active += 1
            self._request_threads_peak = max(
                self._request_threads_peak,
                self._request_threads_active,
            )

        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._request_threads_lock:
                self._request_threads_active -= 1
            self._request_slots.release()

    def publish(self, token, resource):
        with self._resource_lock:
            old = self._resource
            self._resource = resource
            self._token = str(token)

        if old is not None and old is not resource:
            old.invalidate()

        self.close_active_connections()

    def invalidate(self):
        with self._resource_lock:
            old = self._resource
            self._resource = None
            self._token = None

        if old is not None:
            old.invalidate()

        self.close_active_connections()

    def resolve(self, path):
        with self._resource_lock:
            resource = self._resource
            token = self._token
            if resource is None or token is None:
                return None
            if path != "/" + token:
                return None
            if resource.closed:
                return None
            return resource

    def register_handler(self, handler):
        with self._handlers_lock:
            self._handlers.add(handler)

    def unregister_handler(self, handler):
        with self._handlers_lock:
            self._handlers.discard(handler)

    def close_active_connections(self):
        with self._handlers_lock:
            handlers = list(self._handlers)

        for handler in handlers:
            conn = getattr(handler, "connection", None)
            if conn is None:
                continue
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass


class _QobuzLoopbackRequestHandler(BaseHTTPRequestHandler):
    server_version = "SROVAQobuzLoopback/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        # The opaque stream token must not enter normal HTTP access logs.
        return

    def setup(self):
        super().setup()
        server = getattr(self, "server", None)
        if server is not None:
            server.register_handler(self)

    def finish(self):
        try:
            super().finish()
        finally:
            server = getattr(self, "server", None)
            if server is not None:
                server.unregister_handler(self)

    def do_HEAD(self):
        self._serve(head_only=True)

    def do_GET(self):
        self._serve(head_only=False)

    def _send_empty(self, status, *, content_range=None):
        self.send_response(int(status))
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        if content_range is not None:
            self.send_header("Content-Range", str(content_range))
        self.end_headers()
        self.close_connection = True

    def _serve(self, *, head_only):
        self.close_connection = True

        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment:
            self._send_empty(404)
            return

        resource = self.server.resolve(parsed.path)
        if resource is None:
            self._send_empty(404)
            return

        total = int(resource.total_length)
        range_header = self.headers.get("Range")

        if range_header is None:
            start = 0
            end = total
            status = 200
        else:
            try:
                start, end = parse_single_byte_range(range_header, total)
            except QobuzRangeMalformed:
                self._send_empty(400)
                return
            except QobuzRangeUnsatisfiable:
                self._send_empty(
                    416,
                    content_range=f"bytes */{total}",
                )
                return
            status = 206

        length = end - start

        self.send_response(status)
        self.send_header("Content-Type", "audio/flac")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")

        if status == 206:
            self.send_header(
                "Content-Range",
                f"bytes {start}-{end - 1}/{total}",
            )

        self.end_headers()

        if head_only:
            return

        try:
            for chunk in resource.iter_range(start, end):
                self.wfile.write(chunk)
        except (
            BrokenPipeError,
            ConnectionResetError,
            OSError,
            QobuzStreamInvalidated,
        ):
            # Invalidation deliberately terminates any stale in-flight request.
            self.close_connection = True
        except Exception:
            # Never expose provider/network/decryption details over the local
            # HTTP resource.  A short response makes the player fail cleanly.
            self.close_connection = True


class QobuzLoopbackServer:
    """Own one loopback-only HTTP listener and one opaque active resource."""

    def __init__(self):
        self._lock = threading.RLock()
        self._httpd = None
        self._thread = None

    @property
    def running(self):
        with self._lock:
            return self._httpd is not None

    @property
    def host(self):
        return LOOPBACK_HOST

    @property
    def port(self):
        with self._lock:
            if self._httpd is None:
                return None
            return int(self._httpd.server_address[1])

    @property
    def has_active_resource(self):
        with self._lock:
            httpd = self._httpd
            if httpd is None:
                return False
            with httpd._resource_lock:
                return (
                    httpd._resource is not None
                    and not httpd._resource.closed
                )

    def start(self):
        with self._lock:
            if self._httpd is not None:
                return self.port

            httpd = _QobuzLoopbackHTTPServer()
            thread = threading.Thread(
                target=httpd.serve_forever,
                kwargs={"poll_interval": 0.1},
                daemon=True,
                name="srova-qobuz-loopback",
            )
            thread.start()

            self._httpd = httpd
            self._thread = thread
            return int(httpd.server_address[1])

    def publish(self, resource):
        if not isinstance(resource, QobuzVirtualFlacResource):
            raise QobuzStreamError("resource must be QobuzVirtualFlacResource")
        if resource.closed:
            raise QobuzStreamInvalidated("cannot publish an invalidated resource")

        self.start()

        token = secrets.token_urlsafe(24)
        with self._lock:
            httpd = self._httpd
            if httpd is None:
                raise QobuzStreamError("loopback server is unavailable")
            httpd.publish(token, resource)
            port = int(httpd.server_address[1])

        return f"http://{LOOPBACK_HOST}:{port}/{token}"

    def invalidate(self):
        with self._lock:
            httpd = self._httpd
        if httpd is not None:
            httpd.invalidate()

    def stop(self):
        with self._lock:
            httpd = self._httpd
            thread = self._thread
            self._httpd = None
            self._thread = None

        if httpd is None:
            return

        httpd.invalidate()
        try:
            httpd.shutdown()
        finally:
            httpd.server_close()

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
