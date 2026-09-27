import os
import sys
from concurrent.futures import ThreadPoolExecutor

import pyaes
import pytest
import requests


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backend.qobuz import (
    QobuzBackend,
    QobuzDeliveryError,
    QobuzDeliveryRejected,
    QobuzTrackUnavailable,
)
from backend.qobuz_cmaf import (
    QBZ_INIT_UUID,
    QBZ_SEGMENT_UUID,
    QobuzCmafError,
    SegmentTableEntry,
    compute_request_signature,
    decrypt_frame,
    decrypt_segment,
    derive_session_key,
    flac_format_id,
    parse_init_segment,
    parse_segment_crypto,
    reconstruct_flac,
    unwrap_content_key,
)


NOW = 1_775_500_000
CMAF_SEED = "abb21364945c0583309667d13ca3d93a"
INFOS = "AAECAwQFBgcICQoLDA0ODw.U1JPVkEtUTMtUUJaLXJlZmVyZW5jZQ"
SESSION_KEY = bytes.fromhex("0e8baaceb60cd1b14fac77abc204905e")
CONTENT_KEY = bytes.fromhex("00112233445566778899aabbccddeeff")
KEY_STRING = (
    "qbz-1."
    "pOaoCS0xZGH40dkqHiXoQfx5A6ty_9lSs4iw7O4WdCw."
    "Dw4NDAsKCQgHBgUEAwIBAA"
)
FRAME_IV = bytes.fromhex("0102030405060708")
FRAME_PLAINTEXT = bytes.fromhex(
    "fff8c964000102030405060708090a0b"
    "0c0d0e0f101112131415161718191a1b"
)
FRAME_CIPHERTEXT = bytes.fromhex(
    "5e834f5900c70f576132ff543e3249d0"
    "1c69a2dfc98c775e6eb42c71ad65d766"
)
TRAILING_AUDIO = b"\xaa\xbb"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b"", headers=None):
        self.status_code = status_code
        self._payload = payload
        self._content = content
        self.headers = dict(headers or {})

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def iter_content(self, chunk_size=65536):
        for offset in range(0, len(self._content), chunk_size):
            yield self._content[offset:offset + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeHttp:
    def __init__(self, get_responses=None, post_responses=None):
        self.get_responses = list(get_responses or [])
        self.post_responses = list(post_responses or [])
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        response = self.get_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        response = self.post_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def iso_box(box_type, payload):
    return (8 + len(payload)).to_bytes(4, "big") + box_type + payload


def make_flac_header(
    sample_rate=44100,
    bit_depth=16,
    channels=2,
    total_samples=441000,
    block_size=None,
):
    streaminfo = bytearray(34)
    if block_size is not None:
        streaminfo[0:2] = int(block_size).to_bytes(2, "big")
        streaminfo[2:4] = int(block_size).to_bytes(2, "big")
    packed = (
        (sample_rate << 44)
        | ((channels - 1) << 41)
        | ((bit_depth - 1) << 36)
        | total_samples
    )
    streaminfo[10:18] = packed.to_bytes(8, "big")
    return b"fLaC" + b"\x00\x00\x00\x22" + bytes(streaminfo)


def make_init_segment(
    track_id=123456,
    table=None,
    sample_rate=44100,
    bit_depth=16,
    channels=2,
    total_samples=441000,
    block_size=None,
):
    table = table or [SegmentTableEntry(len(FRAME_PLAINTEXT) + 2, 441000)]
    flac_header = make_flac_header(
        sample_rate=sample_rate,
        bit_depth=bit_depth,
        channels=channels,
        total_samples=total_samples,
        block_size=block_size,
    )
    raw_data = b"\x00\x01prefix" + flac_header
    payload = bytearray()
    payload.extend(b"\x00" * 4)
    payload.extend(track_id.to_bytes(4, "big"))
    payload.extend((9876).to_bytes(4, "big"))
    payload.extend(sample_rate.to_bytes(4, "big"))
    payload.append(bit_depth)
    payload.append(channels)
    payload.extend(b"\x00\x00")
    payload.extend(total_samples.to_bytes(6, "big"))
    payload.extend(len(raw_data).to_bytes(2, "big"))
    payload.extend(raw_data)
    payload.append(4)
    payload.extend(b"key1")
    payload.extend(len(table).to_bytes(2, "big"))
    for entry in table:
        payload.extend(entry.byte_len.to_bytes(4, "big"))
        payload.extend(entry.sample_count.to_bytes(4, "big"))
    return iso_box(b"ftyp", b"cmfa") + iso_box(b"uuid", QBZ_INIT_UUID + payload)


def make_audio_segment(
    frame=FRAME_CIPHERTEXT,
    frame_iv=FRAME_IV,
    flags=1,
    trailing=TRAILING_AUDIO,
):
    frame_count = 1
    uuid_payload_length = 4 + 4 + 1 + 3 + (4 + 2 + 2 + len(frame_iv))
    uuid_box_length = 8 + 16 + uuid_payload_length
    data_offset = uuid_box_length + 8
    payload = bytearray()
    payload.extend(b"\x00" * 4)
    payload.extend(data_offset.to_bytes(4, "big"))
    payload.append(len(frame_iv))
    payload.extend(frame_count.to_bytes(3, "big"))
    payload.extend(len(frame).to_bytes(4, "big"))
    payload.extend(b"\x00\x00")
    payload.extend(flags.to_bytes(2, "big"))
    payload.extend(frame_iv)
    return (
        iso_box(b"uuid", QBZ_SEGMENT_UUID + payload)
        + iso_box(b"mdat", frame + trailing)
    )


def service_metadata():
    return {
        "version": 1,
        "bundle_url": "/resources/8.1.0-b019/bundle.js",
        "bundle_version": "8.1.0-b019",
        "app_id": "123456789",
        "private_key": "PrivateKey123",
        "fetched_at": NOW,
    }


def authenticated_backend(tmp_path, http):
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=http,
        now=lambda: NOW,
    )
    backend._service_metadata = service_metadata()
    backend.available = True
    backend.authenticated = True
    backend._auth_state = backend.AUTH_AUTHENTICATED
    backend._session = {"user_auth_token": "synthetic-user-token"}
    return backend


def session_response(status_code=200):
    return FakeResponse(
        status_code=status_code,
        payload={
            "session_id": "synthetic-session-id",
            "expires_at": NOW + 3600,
            "infos": INFOS,
        },
    )


def file_url_response(status_code=200, **changes):
    payload = {
        "url_template": "https://cdn.invalid/audio/$SEGMENT$",
        "mime_type": "audio/mp4",
        "n_segments": 1,
        "key": KEY_STRING,
        "sampling_rate": 44100,
        "bit_depth": 16,
        "format_id": 27,
        "track_id": 123456,
    }
    payload.update(changes)
    return FakeResponse(status_code=status_code, payload=payload)


def test_qbz_crypto_vectors_are_exact():
    assert derive_session_key(CMAF_SEED, INFOS) == SESSION_KEY
    assert unwrap_content_key(SESSION_KEY, KEY_STRING) == CONTENT_KEY
    assert decrypt_frame(CONTENT_KEY, FRAME_IV, FRAME_CIPHERTEXT) == FRAME_PLAINTEXT
    assert compute_request_signature(
        "sessionstart",
        {"profile": "qbz-1"},
        NOW,
        CMAF_SEED,
    ) == "4f3829cbe04f94f4e65e5d1bfdeecd22"
    assert compute_request_signature(
        "fileurl",
        {"track_id": 123456, "format_id": 27, "intent": "stream"},
        NOW,
        CMAF_SEED,
    ) == "6de2b2df0f35fcb30d916f70bd42bfa1"


@pytest.mark.parametrize(
    ("iv", "payload"),
    [
        (FRAME_IV, FRAME_CIPHERTEXT),
        (b"\x00" * 8, b"\x01"),
        (
            bytes.fromhex("ffffffffffffffff"),
            bytes(range(17)),
        ),
        (
            bytes.fromhex("1020304050607080"),
            bytes((index * 37) % 256 for index in range(257)),
        ),
    ],
)
def test_native_aes_ctr_matches_legacy_pyaes_byte_for_byte(iv, payload):
    nonce = iv + (b"\x00" * 8)
    counter = pyaes.Counter(int.from_bytes(nonce, "big"))
    legacy_cipher = pyaes.AESModeOfOperationCTR(
        CONTENT_KEY,
        counter=counter,
    )
    legacy = legacy_cipher.decrypt(bytes(payload))

    assert decrypt_frame(CONTENT_KEY, iv, payload) == legacy


@pytest.mark.parametrize(
    ("seed", "infos"),
    [
        ("abc", INFOS),
        ("not-hex!!", INFOS),
        (CMAF_SEED, "missing-separator"),
        (CMAF_SEED, "bad*.YQ"),
    ],
)
def test_session_key_rejects_malformed_material(seed, infos):
    with pytest.raises(QobuzCmafError):
        derive_session_key(seed, infos)


def test_content_key_rejects_wrong_key_and_malformed_material():
    with pytest.raises(QobuzCmafError):
        unwrap_content_key(b"\x00" * 16, KEY_STRING)
    with pytest.raises(QobuzCmafError):
        unwrap_content_key(SESSION_KEY, "only.two")
    with pytest.raises(QobuzCmafError):
        unwrap_content_key(SESSION_KEY, "qbz-1.bad*.YQ")


def test_aes_ctr_counter_layout_has_a_negative_control():
    wrong_iv = (b"\x00" * 7) + b"\x01"
    assert decrypt_frame(CONTENT_KEY, wrong_iv, FRAME_CIPHERTEXT) != FRAME_PLAINTEXT
    with pytest.raises(QobuzCmafError):
        decrypt_frame(CONTENT_KEY, b"short", FRAME_CIPHERTEXT)


def test_parse_init_segment_exposes_complete_virtual_layout():
    table = [SegmentTableEntry(34, 220500), SegmentTableEntry(77, 220500)]
    parsed = parse_init_segment(make_init_segment(table=table))

    assert parsed.track_id == 123456
    assert parsed.file_id == 9876
    assert parsed.sample_rate == 44100
    assert parsed.bit_depth == 16
    assert parsed.channels == 2
    assert parsed.total_samples == 441000
    assert parsed.flac_header.startswith(b"fLaC")
    assert parsed.flac_header[4] & 0x80
    assert parsed.segment_table == tuple(table)
    assert parsed.virtual_flac_length == 42 + 34 + 77
    assert flac_format_id(parsed.sample_rate, parsed.bit_depth) == 6


def test_init_parser_rejects_missing_uuid_and_truncated_table():
    with pytest.raises(QobuzCmafError):
        parse_init_segment(iso_box(b"ftyp", b"cmfa"))

    valid = make_init_segment()
    with pytest.raises(QobuzCmafError):
        parse_init_segment(valid[:-1])


def test_segment_parser_and_decrypt_match_qbz_layout():
    segment = make_audio_segment()
    parsed = parse_segment_crypto(segment)

    assert len(parsed.entries) == 1
    assert parsed.entries[0].size == len(FRAME_CIPHERTEXT)
    assert parsed.entries[0].flags == 1
    assert parsed.entries[0].iv == FRAME_IV
    assert decrypt_segment(
        CONTENT_KEY,
        segment,
        expected_length=len(FRAME_PLAINTEXT) + len(TRAILING_AUDIO),
    ) == FRAME_PLAINTEXT + TRAILING_AUDIO


def test_segment_parser_rejects_malformed_or_wrong_length_data():
    with pytest.raises(QobuzCmafError):
        parse_segment_crypto(iso_box(b"mdat", b"audio"))
    with pytest.raises(QobuzCmafError):
        parse_segment_crypto(make_audio_segment(frame_iv=b"short"))
    with pytest.raises(QobuzCmafError):
        decrypt_segment(CONTENT_KEY, make_audio_segment(), expected_length=1)


def test_reconstruct_flac_validates_segment_contract_and_structure():
    header = make_flac_header()
    payload = FRAME_PLAINTEXT + TRAILING_AUDIO
    table = [SegmentTableEntry(len(payload), 441000)]

    reconstructed = reconstruct_flac(header, [payload], table)
    assert reconstructed == header + payload

    with pytest.raises(QobuzCmafError):
        reconstruct_flac(header, [payload], [SegmentTableEntry(1, 1)])
    with pytest.raises(QobuzCmafError):
        reconstruct_flac(header, [], table)


def test_resolve_fetch_and_reconstruct_isolated_qobuz_delivery(tmp_path):
    init_segment = make_init_segment()
    audio_segment = make_audio_segment()
    http = FakeHttp(
        post_responses=[session_response()],
        get_responses=[
            file_url_response(),
            FakeResponse(content=init_segment),
            FakeResponse(content=audio_segment),
        ],
    )
    backend = authenticated_backend(tmp_path, http)

    delivery = backend.resolve_track_delivery(123456, 27)
    summary = delivery.safe_summary()

    assert summary == {
        "track_id": 123456,
        "requested_format_id": 27,
        "returned_format_id": 27,
        "actual_format_id": 6,
        "mime_type": "audio/mp4",
        "sample_rate": 44100,
        "bit_depth": 16,
        "channels": 2,
        "total_samples": 441000,
        "n_segments": 1,
        "flac_header_bytes": 42,
        "virtual_flac_length": 42 + len(FRAME_PLAINTEXT) + 2,
    }
    assert "cdn.invalid" not in repr(delivery)
    assert CONTENT_KEY.hex() not in repr(delivery)

    session_call = http.post_calls[0]
    assert session_call[0].endswith("/session/start")
    assert session_call[1]["data"] == {
        "profile": "qbz-1",
        "request_ts": str(NOW),
        "request_sig": "4f3829cbe04f94f4e65e5d1bfdeecd22",
    }
    assert session_call[1]["headers"]["X-User-Auth-Token"] == "synthetic-user-token"

    file_call = http.get_calls[0]
    assert file_call[0].endswith("/file/url")
    assert file_call[1]["headers"]["X-Session-Id"] == "synthetic-session-id"
    assert file_call[1]["params"]["request_sig"] == (
        "6de2b2df0f35fcb30d916f70bd42bfa1"
    )

    flac = backend.reconstruct_flac_for_validation(delivery)
    assert flac == delivery.flac_header + FRAME_PLAINTEXT + TRAILING_AUDIO
    assert len(http.get_calls) == 3


def test_cmaf_session_is_reused_and_logout_clears_it(tmp_path):
    http = FakeHttp(post_responses=[session_response()])
    backend = authenticated_backend(tmp_path, http)
    app_id, token = backend._delivery_auth_context()

    first = backend._ensure_cmaf_session(app_id, token)
    second = backend._ensure_cmaf_session(app_id, token)

    assert first == second
    assert len(http.post_calls) == 1
    assert backend._cmaf_session is not None
    backend.logout()
    assert backend._cmaf_session is None


def test_concurrent_cmaf_session_requests_share_one_network_result(tmp_path):
    http = FakeHttp(post_responses=[session_response()])
    backend = authenticated_backend(tmp_path, http)
    app_id, token = backend._delivery_auth_context()

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                lambda _index: backend._ensure_cmaf_session(app_id, token),
                range(4),
            )
        )

    assert results == [results[0]] * 4
    assert len(http.post_calls) == 1


def test_delivery_requires_qobuz_auth_without_network(tmp_path):
    http = FakeHttp()
    backend = QobuzBackend(
        config_dir=str(tmp_path / "config"),
        cache_dir=str(tmp_path / "cache"),
        http_session=http,
        now=lambda: NOW,
    )
    with pytest.raises(QobuzDeliveryRejected):
        backend.resolve_track_delivery(123456, 27)
    assert not http.get_calls
    assert not http.post_calls


def test_q3_rejects_non_flac_format_before_network(tmp_path):
    http = FakeHttp()
    backend = authenticated_backend(tmp_path, http)
    with pytest.raises(QobuzDeliveryError):
        backend.resolve_track_delivery(123456, 5)
    assert not http.get_calls
    assert not http.post_calls


def test_session_auth_rejection_is_isolated(tmp_path):
    http = FakeHttp(post_responses=[session_response(status_code=401)])
    backend = authenticated_backend(tmp_path, http)

    with pytest.raises(QobuzDeliveryRejected):
        backend.resolve_track_delivery(123456, 27)

    assert backend.authenticated is True
    assert backend.status()["auth_state"] == "authenticated"


def test_expired_session_response_fails_without_retry(tmp_path):
    expired = session_response()
    expired._payload["expires_at"] = NOW + 10
    http = FakeHttp(post_responses=[expired])
    backend = authenticated_backend(tmp_path, http)

    with pytest.raises(QobuzDeliveryError):
        backend.resolve_track_delivery(123456, 27)

    assert len(http.post_calls) == 1
    assert not http.get_calls


def test_file_url_unavailable_and_session_discard_are_bounded(tmp_path):
    http = FakeHttp(
        post_responses=[session_response()],
        get_responses=[file_url_response(status_code=404)],
    )
    backend = authenticated_backend(tmp_path, http)

    with pytest.raises(QobuzTrackUnavailable):
        backend.resolve_track_delivery(123456, 27)
    assert len(http.post_calls) == 1
    assert len(http.get_calls) == 1

    http = FakeHttp(
        post_responses=[session_response()],
        get_responses=[file_url_response(status_code=403)],
    )
    backend = authenticated_backend(tmp_path, http)
    with pytest.raises(QobuzDeliveryRejected):
        backend.resolve_track_delivery(123456, 27)
    assert backend._cmaf_session is None
    assert backend.authenticated is True


def test_network_timeout_and_malformed_response_fail_safely(tmp_path):
    http = FakeHttp(post_responses=[requests.exceptions.Timeout("synthetic")])
    backend = authenticated_backend(tmp_path, http)
    with pytest.raises(QobuzDeliveryError):
        backend.resolve_track_delivery(123456, 27)

    http = FakeHttp(
        post_responses=[session_response()],
        get_responses=[FakeResponse(payload={"n_segments": 1})],
    )
    backend = authenticated_backend(tmp_path, http)
    with pytest.raises(QobuzDeliveryError):
        backend.resolve_track_delivery(123456, 27)


def test_segment_fetch_error_remains_inside_qobuz(tmp_path):
    http = FakeHttp(
        post_responses=[session_response()],
        get_responses=[
            file_url_response(),
            FakeResponse(content=make_init_segment()),
            FakeResponse(status_code=503),
        ],
    )
    backend = authenticated_backend(tmp_path, http)
    delivery = backend.resolve_track_delivery(123456, 27)

    with pytest.raises(QobuzDeliveryError):
        backend.fetch_decrypt_cmaf_segment(delivery, 1)

    assert backend.authenticated is True
    assert backend.status()["auth_state"] == "authenticated"


def test_q3_has_no_tidal_player_or_loopback_server_coupling():
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

    assert "tidal" not in qobuz
    assert "player.load" not in qobuz
    assert "player.load" not in cmaf
    assert "httpserver" not in qobuz
    assert "httpserver" not in cmaf


def test_fixed_block_qobuz_init_adds_segment_boundary_seektable():
    block_size = 4608
    table = [
        SegmentTableEntry(byte_len=100000, sample_count=block_size * 209),
        SegmentTableEntry(byte_len=110000, sample_count=block_size * 209),
        SegmentTableEntry(byte_len=120000, sample_count=(block_size * 2) + 123),
    ]
    total_samples = sum(entry.sample_count for entry in table)

    parsed = parse_init_segment(
        make_init_segment(
            table=table,
            sample_rate=96000,
            bit_depth=24,
            channels=2,
            total_samples=total_samples,
            block_size=block_size,
        )
    )

    header = parsed.flac_header

    assert len(header) == 42 + 4 + (18 * 3)

    # STREAMINFO remains type 0 but is no longer last.
    assert header[4] == 0x00
    assert int.from_bytes(header[5:8], "big") == 34

    seektable_offset = 42

    # Final metadata block, type 3 SEEKTABLE.
    assert header[seektable_offset] == 0x83
    assert int.from_bytes(
        header[seektable_offset + 1:seektable_offset + 4],
        "big",
    ) == 18 * 3

    payload = header[seektable_offset + 4:]

    points = []
    for offset in range(0, len(payload), 18):
        point = payload[offset:offset + 18]
        points.append(
            (
                int.from_bytes(point[0:8], "big"),
                int.from_bytes(point[8:16], "big"),
                int.from_bytes(point[16:18], "big"),
            )
        )

    assert points == [
        (0, 0, block_size),
        (
            table[0].sample_count,
            table[0].byte_len,
            block_size,
        ),
        (
            table[0].sample_count + table[1].sample_count,
            table[0].byte_len + table[1].byte_len,
            block_size,
        ),
    ]


def test_qobuz_seektable_falls_back_when_segment_geometry_is_not_block_aligned():
    block_size = 4608
    table = [
        SegmentTableEntry(
            byte_len=100000,
            sample_count=(block_size * 2) + 1,
        ),
        SegmentTableEntry(
            byte_len=110000,
            sample_count=block_size,
        ),
    ]
    total_samples = sum(entry.sample_count for entry in table)

    parsed = parse_init_segment(
        make_init_segment(
            table=table,
            sample_rate=96000,
            bit_depth=24,
            channels=2,
            total_samples=total_samples,
            block_size=block_size,
        )
    )

    assert len(parsed.flac_header) == 42
    assert parsed.flac_header[4] == 0x80


def test_qobuz_seektable_falls_back_when_streaminfo_block_size_is_unknown():
    table = [
        SegmentTableEntry(byte_len=100000, sample_count=963072),
        SegmentTableEntry(byte_len=110000, sample_count=963072),
    ]
    total_samples = sum(entry.sample_count for entry in table)

    parsed = parse_init_segment(
        make_init_segment(
            table=table,
            sample_rate=96000,
            bit_depth=24,
            channels=2,
            total_samples=total_samples,
            block_size=None,
        )
    )

    assert len(parsed.flac_header) == 42
    assert parsed.flac_header[4] == 0x80


def test_qobuz_seektable_falls_back_when_total_samples_disagree():
    block_size = 4608
    table = [
        SegmentTableEntry(byte_len=100000, sample_count=block_size * 2),
        SegmentTableEntry(byte_len=110000, sample_count=block_size),
    ]

    parsed = parse_init_segment(
        make_init_segment(
            table=table,
            sample_rate=96000,
            bit_depth=24,
            channels=2,
            total_samples=(block_size * 3) + 1,
            block_size=block_size,
        )
    )

    assert len(parsed.flac_header) == 42
    assert parsed.flac_header[4] == 0x80
