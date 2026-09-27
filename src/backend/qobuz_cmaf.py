"""Pure Qobuz CMAF parsing and cryptographic helpers.

The delivery layout is adapted from the MIT-licensed ``vicrodh/qbz``
project at commit ``aa5690e4491507976b56a982025eb4b38ec8e064``.
This module deliberately performs no network, persistence, or playback work.
"""

from dataclasses import dataclass, field
import base64
import binascii
import hashlib
import hmac
import re

import pyaes

try:
    from cryptography.hazmat.primitives.ciphers import (
        Cipher,
        algorithms,
        modes,
    )
except ImportError:
    Cipher = None
    algorithms = None
    modes = None


QBZ_INIT_UUID = bytes.fromhex("c7c75df0fdd951e98fc22971e4acf8d2")
QBZ_SEGMENT_UUID = bytes.fromhex("3b42129256f35f75923663b69a1f52b2")
FLAC_MAGIC = b"fLaC"


class QobuzCmafError(ValueError):
    """Raised when Qobuz CMAF metadata or encrypted bytes are invalid."""


@dataclass(frozen=True)
class SegmentTableEntry:
    byte_len: int
    sample_count: int


@dataclass(frozen=True)
class CmafInitInfo:
    track_id: int
    file_id: int
    sample_rate: int
    bit_depth: int
    channels: int
    total_samples: int
    flac_header: bytes
    segment_table: tuple[SegmentTableEntry, ...]

    @property
    def virtual_flac_length(self):
        return len(self.flac_header) + sum(
            entry.byte_len for entry in self.segment_table
        )


@dataclass(frozen=True)
class CmafFrameEntry:
    size: int
    flags: int
    iv: bytes


@dataclass(frozen=True)
class CmafSegmentCrypto:
    data_offset: int
    mdat_end: int
    entries: tuple[CmafFrameEntry, ...]


@dataclass(frozen=True)
class QobuzCmafDelivery:
    track_id: int
    requested_format_id: int
    returned_format_id: int | None
    actual_format_id: int
    mime_type: str
    sample_rate: int
    bit_depth: int
    channels: int
    total_samples: int
    n_segments: int
    flac_header: bytes
    segment_table: tuple[SegmentTableEntry, ...]
    url_template: str = field(repr=False)
    content_key: bytes = field(repr=False)

    @property
    def virtual_flac_length(self):
        return len(self.flac_header) + sum(
            entry.byte_len for entry in self.segment_table
        )

    def safe_summary(self):
        """Return delivery metadata without signed URLs or key material."""
        return {
            "track_id": self.track_id,
            "requested_format_id": self.requested_format_id,
            "returned_format_id": self.returned_format_id,
            "actual_format_id": self.actual_format_id,
            "mime_type": self.mime_type,
            "sample_rate": self.sample_rate,
            "bit_depth": self.bit_depth,
            "channels": self.channels,
            "total_samples": self.total_samples,
            "n_segments": self.n_segments,
            "flac_header_bytes": len(self.flac_header),
            "virtual_flac_length": self.virtual_flac_length,
        }


def _decode_base64url(value, label):
    if not isinstance(value, str) or not value:
        raise QobuzCmafError(f"{label} must be a non-empty base64url string")
    if not value.isascii() or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise QobuzCmafError(f"{label} is not valid unpadded base64url")
    raw = value.encode("ascii")
    raw += b"=" * ((4 - len(raw) % 4) % 4)
    try:
        return base64.b64decode(raw, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise QobuzCmafError(f"{label} is not valid base64url") from exc


def _decode_seed(seed):
    if not isinstance(seed, str) or len(seed) % 2:
        raise QobuzCmafError("CMAF seed must contain an even number of hex digits")
    try:
        return bytes.fromhex(seed)
    except ValueError as exc:
        raise QobuzCmafError("CMAF seed contains non-hexadecimal data") from exc


def hkdf_sha256(ikm, salt, info, length):
    """RFC 5869 HKDF-SHA256, implemented with the Python standard library."""
    if not isinstance(length, int) or not 1 <= length <= 255 * hashlib.sha256().digest_size:
        raise QobuzCmafError("invalid HKDF output length")
    prk = hmac.new(bytes(salt), bytes(ikm), hashlib.sha256).digest()
    output = bytearray()
    previous = b""
    counter = 1
    while len(output) < length:
        previous = hmac.new(
            prk,
            previous + bytes(info) + bytes([counter]),
            hashlib.sha256,
        ).digest()
        output.extend(previous)
        counter += 1
    return bytes(output[:length])


def derive_session_key(seed, infos):
    """Derive the 16-byte key from ``salt_b64url.info_b64url`` session data."""
    if not isinstance(infos, str):
        raise QobuzCmafError("session infos must be a string")
    parts = infos.split(".")
    if len(parts) < 2:
        raise QobuzCmafError(
            "session infos must have at least two dot-separated parts"
        )
    salt = _decode_base64url(parts[0], "session salt")
    info = _decode_base64url(parts[1], "session info")
    return hkdf_sha256(_decode_seed(seed), salt, info, 16)


def unwrap_content_key(session_key, key_string):
    """Unwrap a ``qbz-1.wrapped_key_b64url.iv_b64url`` AES content key."""
    session_key = bytes(session_key)
    if len(session_key) != 16:
        raise QobuzCmafError("session key must be 16 bytes")
    if not isinstance(key_string, str):
        raise QobuzCmafError("wrapped content key must be a string")
    parts = key_string.split(".")
    if len(parts) < 3 or parts[0] != "qbz-1":
        raise QobuzCmafError("wrapped content key has an unsupported format")
    wrapped = _decode_base64url(parts[1], "wrapped content key")
    iv = _decode_base64url(parts[2], "content-key IV")
    if len(iv) != 16:
        raise QobuzCmafError("content-key IV must be 16 bytes")
    if not wrapped or len(wrapped) % 16:
        raise QobuzCmafError("wrapped content key must contain complete AES blocks")

    cipher = pyaes.AESModeOfOperationCBC(session_key, iv=iv)
    padded = bytearray()
    for offset in range(0, len(wrapped), 16):
        padded.extend(cipher.decrypt(wrapped[offset:offset + 16]))
    padding_length = padded[-1]
    if not 1 <= padding_length <= 16:
        raise QobuzCmafError("wrapped content key has invalid PKCS#7 padding")
    if padded[-padding_length:] != bytes([padding_length]) * padding_length:
        raise QobuzCmafError("wrapped content key has invalid PKCS#7 padding")
    content_key = bytes(padded[:-padding_length])
    if len(content_key) != 16:
        raise QobuzCmafError("unwrapped content key must be 16 bytes")
    return content_key


def decrypt_frame(content_key, iv, data):
    """Decrypt one frame with AES-128-CTR and QBZ's 8-byte IV layout."""
    content_key = bytes(content_key)
    iv = bytes(iv)
    if len(content_key) != 16:
        raise QobuzCmafError("content key must be 16 bytes")
    if len(iv) != 8:
        raise QobuzCmafError("frame IV must be 8 bytes")
    if Cipher is None or algorithms is None or modes is None:
        raise QobuzCmafError(
            "native AES-CTR backend is unavailable"
        )

    nonce = iv + (b"\x00" * 8)
    decryptor = Cipher(
        algorithms.AES(content_key),
        modes.CTR(nonce),
    ).decryptor()
    return decryptor.update(bytes(data)) + decryptor.finalize()


def compute_request_signature(method, arguments, timestamp, seed):
    """Compute the lowercase MD5 signature required by Qobuz CMAF calls."""
    if not isinstance(arguments, dict):
        raise QobuzCmafError("signature arguments must be a dictionary")
    material = [str(method)]
    for key in sorted(arguments):
        material.extend((str(key), str(arguments[key])))
    material.extend((str(timestamp), str(seed)))
    return hashlib.md5("".join(material).encode("utf-8")).hexdigest()


def flac_format_id(sample_rate, bit_depth):
    """Map verified FLAC STREAMINFO to Qobuz's lossless quality tier."""
    sample_rate = int(sample_rate)
    bit_depth = int(bit_depth)
    if sample_rate <= 0 or bit_depth <= 0:
        raise QobuzCmafError("invalid FLAC format metadata")
    if bit_depth <= 16:
        return 6
    if sample_rate <= 96000:
        return 7
    return 27


def _parse_flac_streaminfo(header):
    if len(header) != 42 or not header.startswith(FLAC_MAGIC):
        raise QobuzCmafError("FLAC STREAMINFO header is invalid")
    if header[4] & 0x7F or int.from_bytes(header[5:8], "big") != 34:
        raise QobuzCmafError("FLAC STREAMINFO block is invalid")
    packed = int.from_bytes(header[18:26], "big")
    sample_rate = (packed >> 44) & 0xFFFFF
    channels = ((packed >> 41) & 0x07) + 1
    bit_depth = ((packed >> 36) & 0x1F) + 1
    total_samples = packed & ((1 << 36) - 1)
    if sample_rate <= 0 or bit_depth <= 0 or channels <= 0:
        raise QobuzCmafError("FLAC STREAMINFO audio metadata is invalid")
    return sample_rate, bit_depth, channels, total_samples


def _iter_boxes(data):
    data = bytes(data)
    position = 0
    while position < len(data):
        if position + 8 > len(data):
            raise QobuzCmafError("truncated ISO BMFF box header")
        size = int.from_bytes(data[position:position + 4], "big")
        box_type = data[position + 4:position + 8]
        if size == 0:
            size = len(data) - position
        elif size == 1:
            raise QobuzCmafError("extended-size ISO BMFF boxes are unsupported")
        if size < 8 or position + size > len(data):
            raise QobuzCmafError("invalid ISO BMFF box size")
        yield position, position + size, box_type
        position += size


def _find_uuid_box(data, target_uuid):
    for start, end, box_type in _iter_boxes(data):
        if box_type == b"uuid" and end - start >= 24:
            if data[start + 8:start + 24] == target_uuid:
                return start, start + 24, end
    raise QobuzCmafError("required Qobuz UUID box was not found")



def _flac_header_with_segment_seektable(
    flac_header,
    segment_table,
    total_samples,
):
    """Add conservative segment-boundary FLAC seek points when geometry is safe.

    Qobuz CMAF init metadata contains exact byte and sample counts for each
    decrypted audio segment.  SROVA emits seek points only when STREAMINFO
    itself proves a fixed FLAC block size and every non-final Qobuz segment
    contains an integral number of those blocks.

    If any geometry cannot be proven, the original STREAMINFO-only FLAC header
    is returned byte-for-byte.
    """
    header = bytes(flac_header)
    table = tuple(segment_table)

    # Q3 currently constructs exactly:
    #   "fLaC" + one 34-byte STREAMINFO metadata block.
    # Do not rewrite unfamiliar metadata layouts.
    if (
        len(header) != 42
        or header[:4] != FLAC_MAGIC
        or (header[4] & 0x7F) != 0
        or int.from_bytes(header[5:8], "big") != 34
    ):
        return header

    if not table:
        return header

    min_block_size = int.from_bytes(header[8:10], "big")
    max_block_size = int.from_bytes(header[10:12], "big")

    # Unknown or variable-block FLAC remains on the existing path.
    if (
        min_block_size <= 0
        or max_block_size <= 0
        or min_block_size != max_block_size
    ):
        return header

    block_size = min_block_size

    try:
        declared_total_samples = int(total_samples)
    except (TypeError, ValueError):
        return header

    if declared_total_samples <= 0:
        return header

    sample_cursor = 0
    byte_cursor = 0
    seek_points = []

    for index, entry in enumerate(table):
        try:
            sample_count = int(entry.sample_count)
            byte_len = int(entry.byte_len)
        except (TypeError, ValueError):
            return header

        if sample_count <= 0 or byte_len <= 0:
            return header

        # Qobuz CMAF segments decrypt as complete ordered FLAC frames.
        # For fixed-block FLAC, every non-final segment must therefore contain
        # an exact number of full blocks before its next segment boundary can
        # safely be advertised as a seek point.
        if index < len(table) - 1 and sample_count % block_size:
            return header

        # A final FLAC frame may legitimately be shorter than STREAMINFO's
        # fixed block size.
        frame_samples = min(block_size, sample_count)

        if frame_samples <= 0 or frame_samples > 0xFFFF:
            return header

        # FLAC SEEKTABLE offsets are relative to the first audio frame,
        # not to the start of the file or metadata area.
        seek_points.append(
            int(sample_cursor).to_bytes(8, "big")
            + int(byte_cursor).to_bytes(8, "big")
            + int(frame_samples).to_bytes(2, "big")
        )

        sample_cursor += sample_count
        byte_cursor += byte_len

    if sample_cursor != declared_total_samples:
        return header

    payload = b"".join(seek_points)

    if not payload or len(payload) > 0xFFFFFF:
        return header

    output = bytearray(header)

    # STREAMINFO is no longer the final metadata block.
    output[4] &= 0x7F

    # Metadata block type 3 = SEEKTABLE.
    # This new SEEKTABLE is the final metadata block.
    seektable_header = bytes([0x80 | 3]) + len(payload).to_bytes(3, "big")

    return bytes(output) + seektable_header + payload

def parse_init_segment(data):
    """Extract the FLAC header, format metadata and complete segment table."""
    data = bytes(data)
    _box_start, payload_start, box_end = _find_uuid_box(data, QBZ_INIT_UUID)
    payload = data[payload_start:box_end]
    if len(payload) < 28:
        raise QobuzCmafError("init UUID payload is too short")

    track_id = int.from_bytes(payload[4:8], "big")
    file_id = int.from_bytes(payload[8:12], "big")
    uuid_sample_rate = int.from_bytes(payload[12:16], "big")
    uuid_bit_depth = payload[16]
    uuid_channels = payload[17]
    if uuid_sample_rate <= 0 or uuid_bit_depth <= 0 or uuid_channels <= 0:
        raise QobuzCmafError("init UUID contains invalid audio metadata")

    position = 26
    raw_length = int.from_bytes(payload[position:position + 2], "big")
    position += 2
    if position + raw_length > len(payload):
        raise QobuzCmafError("init UUID raw data is truncated")
    raw_data = payload[position:position + raw_length]
    position += raw_length

    flac_position = raw_data.find(FLAC_MAGIC)
    if flac_position < 0:
        raise QobuzCmafError("init UUID does not contain FLAC magic")
    header_length = 42
    if flac_position + header_length > len(raw_data):
        raise QobuzCmafError("FLAC STREAMINFO is truncated")
    flac_header = bytearray(
        raw_data[flac_position:flac_position + header_length]
    )
    flac_header[4] |= 0x80
    sample_rate, bit_depth, channels, total_samples = _parse_flac_streaminfo(
        flac_header
    )

    if position >= len(payload):
        raise QobuzCmafError("init UUID is missing its key identifier")
    key_id_length = payload[position]
    position += 1
    if position + key_id_length > len(payload):
        raise QobuzCmafError("init UUID key identifier is truncated")
    position += key_id_length

    if position + 2 > len(payload):
        raise QobuzCmafError("init UUID is missing its segment count")
    segment_count = int.from_bytes(payload[position:position + 2], "big")
    position += 2
    if segment_count <= 0:
        raise QobuzCmafError("init UUID contains an empty segment table")
    if position + segment_count * 8 > len(payload):
        raise QobuzCmafError("init UUID segment table is truncated")

    segment_table = []
    for _index in range(segment_count):
        byte_len = int.from_bytes(payload[position:position + 4], "big")
        sample_count = int.from_bytes(payload[position + 4:position + 8], "big")
        position += 8
        if byte_len <= 0 or sample_count <= 0:
            raise QobuzCmafError("init UUID contains an invalid segment entry")
        segment_table.append(SegmentTableEntry(byte_len, sample_count))

    # Qobuz segment-boundary SEEKTABLE.  Unsafe or unproven layouts fall back
    # inside the helper to the original STREAMINFO-only header.
    flac_header = _flac_header_with_segment_seektable(
        flac_header,
        tuple(segment_table),
        total_samples,
    )

    return CmafInitInfo(
        track_id=track_id,
        file_id=file_id,
        sample_rate=sample_rate,
        bit_depth=bit_depth,
        channels=channels,
        total_samples=total_samples,
        flac_header=bytes(flac_header),
        segment_table=tuple(segment_table),
    )


def parse_segment_crypto(data):
    """Extract frame sizes, flags and IVs from one encrypted audio segment."""
    data = bytes(data)
    uuid_start = uuid_payload = uuid_end = None
    mdat_start = mdat_end = None
    for start, end, box_type in _iter_boxes(data):
        if box_type == b"uuid" and end - start >= 24:
            if data[start + 8:start + 24] == QBZ_SEGMENT_UUID:
                uuid_start, uuid_payload, uuid_end = start, start + 24, end
        elif box_type == b"mdat":
            mdat_start, mdat_end = start + 8, end
    if uuid_start is None:
        raise QobuzCmafError("audio segment UUID box was not found")
    if mdat_start is None:
        raise QobuzCmafError("audio segment mdat box was not found")
    if uuid_payload + 12 > uuid_end:
        raise QobuzCmafError("audio segment UUID header is truncated")

    position = uuid_payload + 4
    data_offset_raw = int.from_bytes(data[position:position + 4], "big")
    data_offset = uuid_start + data_offset_raw
    position += 4
    iv_size = data[position]
    position += 1
    frame_count = int.from_bytes(data[position:position + 3], "big")
    position += 3
    if iv_size != 8:
        raise QobuzCmafError("audio segment frame IV size is not 8 bytes")
    if frame_count <= 0:
        raise QobuzCmafError("audio segment contains no frame entries")
    entry_size = 8 + iv_size
    if position + frame_count * entry_size > uuid_end:
        raise QobuzCmafError("audio segment frame table is truncated")
    if not mdat_start <= data_offset <= mdat_end:
        raise QobuzCmafError("audio segment data offset is outside mdat")

    entries = []
    total_frame_bytes = 0
    for _index in range(frame_count):
        size = int.from_bytes(data[position:position + 4], "big")
        position += 4
        position += 2
        flags = int.from_bytes(data[position:position + 2], "big")
        position += 2
        iv = data[position:position + iv_size]
        position += iv_size
        if size <= 0:
            raise QobuzCmafError("audio segment contains an empty frame")
        total_frame_bytes += size
        entries.append(CmafFrameEntry(size=size, flags=flags, iv=iv))
    if data_offset + total_frame_bytes > mdat_end:
        raise QobuzCmafError("audio segment frame data exceeds mdat")
    return CmafSegmentCrypto(
        data_offset=data_offset,
        mdat_end=mdat_end,
        entries=tuple(entries),
    )


def decrypt_segment(content_key, segment_data, expected_length=None):
    """Recover ordered FLAC frame bytes from one Qobuz CMAF segment."""
    segment_data = bytes(segment_data)
    crypto = parse_segment_crypto(segment_data)
    output = bytearray()
    position = crypto.data_offset
    for entry in crypto.entries:
        frame_end = position + entry.size
        frame = segment_data[position:frame_end]
        if entry.flags:
            frame = decrypt_frame(content_key, entry.iv, frame)
        output.extend(frame)
        position = frame_end
    if position < crypto.mdat_end:
        output.extend(segment_data[position:crypto.mdat_end])
    if expected_length is not None and len(output) != int(expected_length):
        raise QobuzCmafError(
            f"decrypted segment length {len(output)} does not match "
            f"the init table length {expected_length}"
        )
    return bytes(output)


def reconstruct_flac(flac_header, segment_payloads, segment_table):
    """Join an init FLAC header and already decrypted segment payloads."""
    header = bytes(flac_header)
    payloads = tuple(bytes(payload) for payload in segment_payloads)
    table = tuple(segment_table)
    if len(payloads) != len(table):
        raise QobuzCmafError("decrypted segment count does not match the init table")
    for index, (payload, entry) in enumerate(zip(payloads, table), start=1):
        if len(payload) != entry.byte_len:
            raise QobuzCmafError(
                f"decrypted segment {index} has an unexpected byte length"
            )
    output = header + b"".join(payloads)
    validate_flac_structure(output)
    return output


def validate_flac_structure(data):
    """Perform bounded structural checks before an external FLAC decoder test."""
    data = bytes(data)
    if len(data) < 44 or not data.startswith(FLAC_MAGIC):
        raise QobuzCmafError("reconstructed data does not start with FLAC magic")
    if data[4] & 0x7F:
        raise QobuzCmafError("first FLAC metadata block is not STREAMINFO")
    streaminfo_length = int.from_bytes(data[5:8], "big")
    if streaminfo_length != 34 or len(data) < 8 + streaminfo_length:
        raise QobuzCmafError("FLAC STREAMINFO block is invalid")
    frame_offset = 8 + streaminfo_length
    if frame_offset + 2 > len(data):
        raise QobuzCmafError("reconstructed FLAC contains no audio frame")
    if data[frame_offset] != 0xFF or data[frame_offset + 1] & 0xFC != 0xF8:
        raise QobuzCmafError("reconstructed FLAC frame sync is invalid")
    return True
