import threading
import time
import logging
import struct
import urllib.request
import urllib.parse
import json
import re

logger = logging.getLogger(__name__)


def probe_flac_technical_info(stream_url, timeout=4, max_bytes=262144):
    """Return native FLAC technical info from a short independent probe."""
    try:
        req = urllib.request.Request(
            stream_url,
            headers={"User-Agent": "SROVA/1.0", "Range": "bytes=0-{}".format(max_bytes - 1)},
        )
        chunks = []
        remaining = int(max_bytes)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            while remaining > 0:
                chunk = resp.read(min(8192, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        data = b"".join(chunks)
        marker = data.find(b"fLaC")
        if marker < 0:
            return {}

        pos = marker + 4
        end = len(data)
        while pos + 4 <= end:
            header = data[pos:pos + 4]
            block_type = header[0] & 0x7f
            block_len = int.from_bytes(header[1:4], "big")
            pos += 4
            if block_len < 0 or pos + block_len > end:
                return {}
            block = data[pos:pos + block_len]
            if block_type == 0:
                if block_len < 34:
                    return {}
                x = int.from_bytes(block[10:18], "big")
                sample_rate = (x >> 44) & 0xFFFFF
                bit_depth = ((x >> 36) & 0x1F) + 1
                if not (8000 <= sample_rate <= 384000):
                    return {}
                if bit_depth not in {8, 12, 16, 20, 24, 32}:
                    return {}
                return {
                    "codec": "FLAC",
                    "sample_rate": sample_rate,
                    "bit_depth": bit_depth,
                    "radio_observed_rate_confidence": "flac_streaminfo",
                }
            pos += block_len
    except Exception as e:
        logger.debug("FLAC technical probe failed for %s: %s", stream_url, e)
    return {}


class RadioMetadataResolver:
    def probe(self, stream_url):
        raise NotImplementedError

    def start(self, stream_url, on_update_callback):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError


class IcecastJsonResolver(RadioMetadataResolver):
    """Polls /status-json.xsl on the Icecast server every 5 seconds."""

    def __init__(self):
        self._stop_flag = False
        self._thread = None

    def _base_url(self, stream_url):
        parsed = urllib.parse.urlparse(stream_url)
        port = ""
        if parsed.port:
            port = ":{}".format(parsed.port)
        return "{}://{}{}".format(parsed.scheme, parsed.hostname, port)

    def _fetch_status(self, base_url):
        url = base_url + "/status-json.xsl"
        req = urllib.request.Request(url, headers={"User-Agent": "SROVA/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return data

    def probe(self, stream_url):
        try:
            data = self._fetch_status(self._base_url(stream_url))
            return isinstance(data, dict) and "icestats" in data and \
                   "source" in data["icestats"]
        except Exception as e:
            logger.debug("IcecastJsonResolver.probe failed for %s: %s", stream_url, e)
            return False

    def _find_source(self, data, stream_url):
        icestats = data.get("icestats", {})
        sources = icestats.get("source", [])
        if isinstance(sources, dict):
            sources = [sources]

        parsed = urllib.parse.urlparse(stream_url)
        mount_suffix = parsed.path.lstrip("/")

        # Pass 1: match listenurl exactly
        for src in sources:
            if src.get("listenurl", "") == stream_url:
                return src

        # Pass 2: mount path suffix match
        for src in sources:
            listen = src.get("listenurl", "")
            if listen:
                listen_path = urllib.parse.urlparse(listen).path.lstrip("/")
                if listen_path == mount_suffix:
                    return src

        # Pass 3: first available source
        return sources[0] if sources else None

    @staticmethod
    def _resolve_title(matched, all_sources):
        """Return the title string for matched source, using a sibling as
        fallback when the matched source carries no title of its own.

        Sibling priority:
          1. Same non-empty server_name as matched source.
          2. Same basename of listenurl path (extension stripped).
        First qualifying sibling in array order wins at each tier.
        """
        raw = str(matched.get("title", "") or "").strip()
        if raw:
            return raw

        own_name = str(matched.get("server_name", "") or "").strip()
        own_listen = str(matched.get("listenurl", "") or "")
        own_base = urllib.parse.urlparse(own_listen).path.rsplit(".", 1)[0]

        by_name = None
        by_base = None
        for src in all_sources:
            if src is matched:
                continue
            candidate = str(src.get("title", "") or "").strip()
            if not candidate:
                continue
            if by_name is None and own_name:
                sib_name = str(src.get("server_name", "") or "").strip()
                if sib_name == own_name:
                    by_name = candidate
            if by_base is None and own_base:
                sib_listen = str(src.get("listenurl", "") or "")
                sib_base = urllib.parse.urlparse(sib_listen).path.rsplit(".", 1)[0]
                if sib_base == own_base:
                    by_base = candidate
            if by_name is not None and by_base is not None:
                break

        return by_name or by_base or ""

    def _poll_loop(self, stream_url, on_update_callback, base_url):
        last_raw = None
        while not self._stop_flag:
            try:
                data = self._fetch_status(base_url)
                icestats = data.get("icestats", {})
                raw_sources = icestats.get("source", [])
                all_sources = [raw_sources] if isinstance(raw_sources, dict) else raw_sources
                src = self._find_source(data, stream_url)
                if src:
                    raw = self._resolve_title(src, all_sources)
                    if raw and raw != last_raw:
                        last_raw = raw
                        parts = raw.split(" - ", 1)
                        if len(parts) == 2:
                            artist, title = parts[0].strip(), parts[1].strip()
                        else:
                            artist, title = "", raw
                        try:
                            on_update_callback({
                                "artist":     artist,
                                "title":      title,
                                "raw":        raw,
                                "updated_at": time.time(),
                            })
                        except Exception as cb_err:
                            logger.debug("IcecastJsonResolver callback error: %s", cb_err)
            except Exception as e:
                logger.debug("IcecastJsonResolver poll error: %s", e)

            for _ in range(50):
                if self._stop_flag:
                    break
                time.sleep(0.1)

    def start(self, stream_url, on_update_callback):
        self._stop_flag = False
        base_url = self._base_url(stream_url)
        self._thread = threading.Thread(
            target=self._poll_loop,
            args=(stream_url, on_update_callback, base_url),
            daemon=True,
            name="icecast-metadata",
        )
        self._thread.start()
        logger.info("IcecastJsonResolver started for %s", stream_url)

    def stop(self):
        self._stop_flag = True
        logger.debug("IcecastJsonResolver stop requested")


# ---------------------------------------------------------------------------
# Easy Radio website now-playing endpoint
# ---------------------------------------------------------------------------

class EasyRadioWebsiteResolver(RadioMetadataResolver):
    """Poll Easy Radio's website now-playing JSON endpoint.

    This resolver is observe-only. It does not open or inspect the playback
    stream; it only emits parsed artist/title metadata for the active station.
    """

    _ENDPOINT = "https://easyradio.bg/playing/get/"
    _POLL_INTERVAL = 10
    _FALLBACK_TITLES = {
        "your relaxing music mix",
        "easyradio.bg",
        "easy radio",
    }

    def __init__(self):
        self._stop_flag = False
        self._thread = None
        self._station = {}

    def set_station(self, station):
        self._station = dict(station or {})

    @staticmethod
    def _contains_easy_radio(value):
        text = str(value or "").strip().lower()
        return "easyradio.bg" in text or "easy radio" in text

    def probe(self, stream_url):
        if self._contains_easy_radio(stream_url):
            return True

        station = self._station or {}
        for key in ("name", "title", "display_name", "url", "homepage", "website", "domain"):
            if self._contains_easy_radio(station.get(key, "")):
                return True
        return False

    def _fetch_now_playing(self):
        req = urllib.request.Request(self._ENDPOINT, headers={"User-Agent": "SROVA/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))

    @classmethod
    def _parse_title(cls, data):
        if not isinstance(data, dict):
            return None

        raw = str(data.get("title", "") or "").strip()
        if not raw:
            return None
        if raw.lower() in cls._FALLBACK_TITLES:
            return None

        parts = raw.split(" - ", 1)
        if len(parts) != 2:
            return {
                "artist":     "",
                "title":      raw,
                "raw":        raw,
                "updated_at": time.time(),
            }

        artist = parts[0].strip()
        title = parts[1].strip()
        if not artist or not title:
            return None

        return {
            "artist":     artist,
            "title":      title,
            "raw":        raw,
            "updated_at": time.time(),
        }

    def _interruptible_sleep(self, delay):
        for _ in range(int(delay * 10)):
            if self._stop_flag:
                break
            time.sleep(0.1)

    def _poll_loop(self, on_update_callback):
        last_raw = None
        backoff = self._POLL_INTERVAL

        while not self._stop_flag:
            try:
                meta = self._parse_title(self._fetch_now_playing())
                backoff = self._POLL_INTERVAL
                if meta and meta.get("raw") != last_raw:
                    last_raw = meta.get("raw")
                    try:
                        on_update_callback(meta)
                    except Exception as cb_err:
                        logger.debug("EasyRadioWebsiteResolver callback error: %s", cb_err)
            except Exception as e:
                logger.debug("EasyRadioWebsiteResolver poll error: %s", e)
                backoff = min(max(backoff * 2, self._POLL_INTERVAL), 60)

            self._interruptible_sleep(backoff)

    def start(self, stream_url, on_update_callback):
        self._stop_flag = False
        self._thread = threading.Thread(
            target=self._poll_loop,
            args=(on_update_callback,),
            daemon=True,
            name="easy-radio-metadata",
        )
        self._thread.start()
        logger.info("EasyRadioWebsiteResolver started for %s", stream_url)

    def stop(self):
        self._stop_flag = True
        logger.debug("EasyRadioWebsiteResolver stop requested")


# ---------------------------------------------------------------------------
# Radio Paradise ICY metadata stream
# ---------------------------------------------------------------------------

class RadioParadiseIcyMetadataResolver(RadioMetadataResolver):
    """Reads ICY metadata blocks from Radio Paradise FLAC metadata streams.

    The audio stream is left to the player.  This resolver opens its own small
    observe-only connection with Icy-MetaData enabled and emits StreamTitle.
    """

    _MATCH_HOST = "radioparadise.com"
    _MATCH_PATHS = (
        "/flacm",
        "/mellow-flacm",
        "/rock-flacm",
        "/global-flacm",
    )
    _BACKOFF = [2, 5, 15, 30]
    _READ_CHUNK = 16384

    def __init__(self):
        self._stop_flag = False
        self._thread = None
        self._conn = None
        self._conn_lock = threading.Lock()
        self._diagnosed = False

    @classmethod
    def _matches(cls, stream_url):
        parsed = urllib.parse.urlparse(stream_url)
        host = str(parsed.hostname or "").lower()
        path = str(parsed.path or "").lower()
        if cls._MATCH_HOST not in host:
            return False
        if path in cls._MATCH_PATHS:
            return True
        return "flacm" in path

    @staticmethod
    def _icy_headers(headers):
        out = {}
        for key, value in headers.items():
            if str(key).lower().startswith("icy-") or str(key).lower() == "ice-audio-info":
                out[str(key)] = str(value)
        return out

    @staticmethod
    def _header_value(headers, name):
        wanted = name.lower()
        for key, value in headers.items():
            if str(key).lower() == wanted:
                return str(value)
        return ""

    @staticmethod
    def _read_exact(stream, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = stream.read(n - len(buf))
            if not chunk:
                raise EOFError("short read: wanted {} got {}".format(n, len(buf)))
            buf.extend(chunk)
        return bytes(buf)

    def _discard_exact(self, stream, n):
        remaining = n
        while remaining > 0 and not self._stop_flag:
            chunk = stream.read(min(self._READ_CHUNK, remaining))
            if not chunk:
                raise EOFError("EOF while skipping audio bytes")
            remaining -= len(chunk)

    @staticmethod
    def _extract_stream_title(block):
        text = block.rstrip(b"\0").decode("utf-8", errors="replace").strip()
        if not text:
            return ""
        match = re.search(r"StreamTitle='([^']*)'", text)
        if match:
            return match.group(1).strip()
        match = re.search(r'StreamTitle="([^"]*)"', text)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _parse_title(raw):
        raw = str(raw or "").strip()
        if not raw:
            return None
        parts = raw.split(" - ", 1)
        if len(parts) == 2:
            artist = parts[0].strip()
            title = parts[1].strip()
        else:
            artist = ""
            title = raw
        if not title:
            return None
        return {
            "artist": artist,
            "title": title,
            "raw": raw,
            "updated_at": time.time(),
        }

    def probe(self, stream_url):
        if not self._matches(stream_url):
            return False
        try:
            req = urllib.request.Request(
                stream_url,
                headers={
                    "User-Agent": "SROVA/1.0",
                    "Icy-MetaData": "1",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                headers = resp.headers
                metaint = self._header_value(headers, "icy-metaint")
                logger.info(
                    "Radio Paradise metadata diagnostic: path=RadioParadiseIcyMetadataResolver.probe sends_icy_metadata=1 icy_metaint=%r icy_headers=%r",
                    metaint,
                    self._icy_headers(headers),
                )
                return bool(metaint and int(metaint) > 0)
        except Exception as e:
            logger.info(
                "Radio Paradise metadata diagnostic: path=RadioParadiseIcyMetadataResolver.probe failed sends_icy_metadata=1 error=%s",
                e,
            )
            return False

    def _poll_loop(self, stream_url, on_update_callback):
        last_raw = None
        backoff_idx = 0

        while not self._stop_flag:
            resp = None
            try:
                req = urllib.request.Request(
                    stream_url,
                    headers={
                        "User-Agent": "SROVA/1.0",
                        "Icy-MetaData": "1",
                    },
                )
                resp = urllib.request.urlopen(req, timeout=30)
                with self._conn_lock:
                    self._conn = resp

                headers = resp.headers
                metaint_text = self._header_value(headers, "icy-metaint")
                metaint = int(metaint_text or "0")
                if metaint <= 0:
                    raise ValueError("missing icy-metaint")

                if not self._diagnosed:
                    self._diagnosed = True
                    logger.info(
                        "Radio Paradise metadata diagnostic: path=RadioParadiseIcyMetadataResolver.stream sends_icy_metadata=1 icy_metaint=%s icy_headers=%r",
                        metaint,
                        self._icy_headers(headers),
                    )

                backoff_idx = 0
                while not self._stop_flag:
                    self._discard_exact(resp, metaint)
                    length_byte = resp.read(1)
                    if not length_byte:
                        raise EOFError("EOF before ICY metadata length")
                    block_len = length_byte[0] * 16
                    if block_len <= 0:
                        continue
                    block = self._read_exact(resp, block_len)
                    raw = self._extract_stream_title(block)
                    if not raw:
                        continue
                    if raw != last_raw:
                        logger.info("Radio Paradise metadata diagnostic: raw StreamTitle=%r", raw)
                    meta = self._parse_title(raw)
                    if not meta or raw == last_raw:
                        continue
                    last_raw = raw
                    try:
                        on_update_callback(meta)
                    except Exception as cb_err:
                        logger.debug("RadioParadiseIcyMetadataResolver callback error: %s", cb_err)

            except Exception as e:
                if self._stop_flag:
                    break
                delay = self._BACKOFF[min(backoff_idx, len(self._BACKOFF) - 1)]
                logger.info(
                    "Radio Paradise metadata diagnostic: path=RadioParadiseIcyMetadataResolver.stream error=%s reconnecting_in=%ds",
                    e,
                    delay,
                )
                backoff_idx = min(backoff_idx + 1, len(self._BACKOFF) - 1)
                for _ in range(delay * 10):
                    if self._stop_flag:
                        break
                    time.sleep(0.1)
            finally:
                if resp is not None:
                    try:
                        resp.close()
                    except Exception:
                        pass
                with self._conn_lock:
                    if self._conn is resp:
                        self._conn = None

    def start(self, stream_url, on_update_callback):
        self._stop_flag = False
        self._thread = threading.Thread(
            target=self._poll_loop,
            args=(stream_url, on_update_callback),
            daemon=True,
            name="radio-paradise-icy-metadata",
        )
        self._thread.start()
        logger.info("RadioParadiseIcyMetadataResolver started for %s", stream_url)

    def stop(self):
        self._stop_flag = True
        with self._conn_lock:
            conn = self._conn
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        logger.debug("RadioParadiseIcyMetadataResolver stop requested")


# ---------------------------------------------------------------------------
# Ogg / FLAC-in-Ogg in-stream parser
# ---------------------------------------------------------------------------

class OggVorbisResolver(RadioMetadataResolver):
    """Reads the raw Ogg byte stream and extracts VORBIS_COMMENT packets.

    Handles both pure Vorbis (comment header type 0x03 + 'vorbis') and
    FLAC-in-Ogg (FLAC metadata block type 4 = VORBIS_COMMENT).  At each
    track boundary Icecast sends a new logical bitstream (BOS page) followed
    by an updated VORBIS_COMMENT block containing TITLE= and ARTIST= tags.
    """

    _BACKOFF = [1, 2, 5, 10, 30]

    def __init__(self):
        self._stop_flag = False
        self._thread = None
        self._conn = None
        self._conn_lock = threading.Lock()

    # ------------------------------------------------------------------
    # probe
    # ------------------------------------------------------------------

    def probe(self, stream_url):
        try:
            req = urllib.request.Request(
                stream_url,
                headers={"User-Agent": "SROVA/1.0", "Range": "bytes=0-4095"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                magic = resp.read(4)
            return magic == b"OggS"
        except Exception as e:
            logger.debug("[OggVorbisResolver] probe failed for %s: %s", stream_url, e)
            return False

    # ------------------------------------------------------------------
    # Ogg page reader helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_exact(stream, n):
        buf = b""
        while len(buf) < n:
            chunk = stream.read(n - len(buf))
            if not chunk:
                raise EOFError("short read: wanted {} got {}".format(n, len(buf)))
            buf += chunk
        return buf

    def _sync_and_read_page(self, stream):
        """Scan forward to the next OggS capture pattern then read the full
        page.  Returns (header_type, seg_table, data) or raises on error."""
        window = b""
        while window != b"OggS":
            b = stream.read(1)
            if not b:
                raise EOFError("EOF while seeking OggS")
            window = (window + b)[-4:]
        # 23 bytes of header remain after the 4-byte capture pattern:
        #   version(1) header_type(1) granule(8) serial(4) seqno(4) crc(4) nseg(1)
        rest = self._read_exact(stream, 23)
        header_type = rest[1]
        n_seg = rest[22]
        seg_table = self._read_exact(stream, n_seg)
        data = self._read_exact(stream, sum(seg_table))
        return header_type, seg_table, data

    # ------------------------------------------------------------------
    # Vorbis comment parser
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_vorbis_comment(payload):
        """Parse a raw Vorbis comment payload (vendor string already at
        offset 0).  Returns dict of UPPERCASE_KEY -> value, or {} on error.
        """
        try:
            if len(payload) < 4:
                return {}
            vendor_len = struct.unpack_from("<I", payload, 0)[0]
            pos = 4 + vendor_len
            if pos + 4 > len(payload):
                return {}
            n_comments = struct.unpack_from("<I", payload, pos)[0]
            pos += 4
            if n_comments > 10000:
                return {}
            tags = {}
            for _ in range(n_comments):
                if pos + 4 > len(payload):
                    break
                clen = struct.unpack_from("<I", payload, pos)[0]
                pos += 4
                if clen > len(payload) - pos:
                    break
                raw = payload[pos:pos + clen].decode("utf-8", errors="replace")
                pos += clen
                if "=" in raw:
                    k, v = raw.split("=", 1)
                    tags[k.upper()] = v
            return tags
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Packet extraction from a page's segment table + data
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_packets(seg_table, data, pending):
        """Reassemble Ogg packets from a page.  pending is a bytearray
        accumulating bytes for a packet that spans multiple pages.
        Returns (list_of_complete_packets, updated_pending_bytearray)."""
        packets = []
        offset = 0
        for seg_len in seg_table:
            pending += data[offset:offset + seg_len]
            offset += seg_len
            if seg_len < 255:
                packets.append(bytes(pending))
                pending = bytearray()
        return packets, pending

    # ------------------------------------------------------------------
    # Streaming poll loop
    # ------------------------------------------------------------------

    def _poll_loop(self, stream_url, on_update_callback):
        backoff_idx = 0
        last_raw = None

        while not self._stop_flag:
            resp = None
            try:
                req = urllib.request.Request(
                    stream_url, headers={"User-Agent": "SROVA/1.0"}
                )
                resp = urllib.request.urlopen(req, timeout=30)
                with self._conn_lock:
                    self._conn = resp

                pending = bytearray()
                good_pages = 0

                while not self._stop_flag:
                    header_type, seg_table, data = self._sync_and_read_page(resp)

                    if header_type & 0x02:
                        # BOS: new logical bitstream (track boundary or initial)
                        pending = bytearray()

                    packets, pending = self._extract_packets(seg_table, data, pending)
                    good_pages += 1
                    if good_pages == 1:
                        backoff_idx = 0  # reset backoff after first good page

                    for pkt in packets:
                        if not pkt:
                            continue
                        payload = None

                        # Standard Vorbis comment header: 0x03 + b'vorbis'
                        if len(pkt) >= 7 and pkt[0] == 0x03 and pkt[1:7] == b"vorbis":
                            payload = pkt[7:]

                        # FLAC-in-Ogg: FLAC metadata block type 4 (VORBIS_COMMENT)
                        # First byte: [is_last:1 | type:7], type 4 = 0x04 / 0x84
                        elif (pkt[0] & 0x7f) == 4 and len(pkt) >= 4:
                            payload = pkt[4:]

                        if payload is None:
                            continue

                        tags = self._parse_vorbis_comment(payload)
                        if not tags:
                            continue

                        title = str(tags.get("TITLE", "") or "").strip()
                        artist = str(tags.get("ARTIST", "") or "").strip()
                        if not title:
                            continue

                        raw = "{} - {}".format(artist, title) if artist else title
                        if raw == last_raw:
                            continue
                        last_raw = raw

                        try:
                            on_update_callback({
                                "artist":     artist,
                                "title":      title,
                                "raw":        raw,
                                "updated_at": time.time(),
                            })
                        except Exception as cb_err:
                            logger.debug("[OggVorbisResolver] callback error: %s", cb_err)

            except Exception as e:
                if self._stop_flag:
                    break
                delay = self._BACKOFF[min(backoff_idx, len(self._BACKOFF) - 1)]
                logger.info(
                    "[OggVorbisResolver] stream error for %s (%s), reconnecting in %ds",
                    stream_url, e, delay,
                )
                backoff_idx = min(backoff_idx + 1, len(self._BACKOFF) - 1)
                # Interruptible sleep
                for _ in range(delay * 10):
                    if self._stop_flag:
                        break
                    time.sleep(0.1)
            finally:
                if resp is not None:
                    try:
                        resp.close()
                    except Exception:
                        pass
                with self._conn_lock:
                    if self._conn is resp:
                        self._conn = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self, stream_url, on_update_callback):
        self._stop_flag = False
        self._thread = threading.Thread(
            target=self._poll_loop,
            args=(stream_url, on_update_callback),
            daemon=True,
            name="ogg-metadata",
        )
        self._thread.start()
        logger.info("[OggVorbisResolver] started for %s", stream_url)

    def stop(self):
        self._stop_flag = True
        with self._conn_lock:
            conn = self._conn
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        logger.debug("[OggVorbisResolver] stop requested")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ResolverRegistry:
    """Holds an ordered list of resolver classes. attach() probes each in
    order and starts the first match. Only one resolver is active at a time."""

    def __init__(self, resolver_classes):
        # resolver_classes: ordered list of classes (not instances)
        # Future slot: IcyInStreamResolver
        self._resolver_classes = list(resolver_classes)
        self._active = None

    def attach(self, stream_url, on_update_callback, station=None):
        self.detach()
        for cls in self._resolver_classes:
            instance = cls()
            try:
                if hasattr(instance, "set_station"):
                    instance.set_station(station)
                if instance.probe(stream_url):
                    instance.start(stream_url, on_update_callback)
                    self._active = instance
                    logger.info("ResolverRegistry: attached %s for %s",
                                cls.__name__, stream_url)
                    return instance
            except Exception as e:
                logger.debug("ResolverRegistry: %s probe/start error: %s",
                             cls.__name__, e)
        logger.info("ResolverRegistry: no resolver matched %s", stream_url)
        return None

    def detach(self):
        if self._active is not None:
            try:
                self._active.stop()
            except Exception as e:
                logger.debug("ResolverRegistry: detach stop error: %s", e)
            self._active = None
