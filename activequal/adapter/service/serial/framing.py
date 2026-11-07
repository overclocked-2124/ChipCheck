"""COBS + CRC-16/CCITT-FALSE framing for the test-controller serial link (HLD 05 §9.1).

Frame before COBS encoding (all little-endian)::

    version u8 | type u8 | seq u16 | episodeTag u32 | length u16 | payload[length] | crc u16

``crc`` is CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, no final xor) over every
preceding byte. On the wire a frame is ``cobs(frame) + 0x00``; the delimiter never occurs inside an
encoded frame, so after any garbage the decoder resynchronizes at the next delimiter and a lost
byte costs one frame, not the stream.

``FrameDecoder`` never raises on bad input. Everything it sees becomes an event:
``Frame`` (valid), ``FrameError`` (crc / cobs / short / length / version / oversize), ``Gap``
(valid frames were skipped; the frame itself is still delivered) and ``Duplicate`` (same seq
replayed, or a stale seq that went backwards; the frame is *not* delivered as new).
"""

from __future__ import annotations

import struct
from typing import Iterable, NamedTuple

PROTOCOL_VERSION = 1
HEADER_SIZE = 10                    # version, type, seq, episodeTag, length
CRC_SIZE = 2
MAX_PAYLOAD = 512
DELIMITER = 0x00

ERR_CRC = "CRC"
ERR_COBS = "COBS"
ERR_SHORT = "SHORT"
ERR_LENGTH = "LENGTH"
ERR_VERSION = "VERSION"
ERR_OVERSIZE = "OVERSIZE"


# ------------------------------------------------------------------------------------------ CRC

def _make_table() -> tuple[int, ...]:
    table = []
    for byte in range(256):
        crc = byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
        table.append(crc)
    return tuple(table)


_TABLE = _make_table()


def crc16_ccitt_false(data: bytes, init: int = 0xFFFF) -> int:
    crc = init
    for byte in data:
        crc = ((crc << 8) & 0xFFFF) ^ _TABLE[(crc >> 8) ^ byte]
    return crc


# ----------------------------------------------------------------------------------------- COBS

class CobsError(ValueError):
    pass


def cobs_encode(data: bytes) -> bytes:
    """Consistent Overhead Byte Stuffing (Cheshire and Baker). The output contains no 0x00 byte."""
    out = bytearray()
    block = bytearray()
    for byte in data:
        if byte == 0:
            out.append(len(block) + 1)
            out += block
            block.clear()
        else:
            block.append(byte)
            if len(block) == 254:           # a full block gets code 0xFF and implies no zero after it
                out.append(0xFF)
                out += block
                block.clear()
    # Final block. A input that ends exactly on a full block gets no extra (empty) code byte.
    if block or not data or data[-1] == 0:
        out.append(len(block) + 1)
        out += block
    return bytes(out)


def cobs_decode(encoded: bytes) -> bytes:
    if 0 in encoded:
        raise CobsError("zero byte inside a COBS block")
    out = bytearray()
    i, n = 0, len(encoded)
    while i < n:
        code = encoded[i]
        end = i + code
        if end > n:
            raise CobsError("COBS block runs past the end of the frame")
        out += encoded[i + 1:end]
        i = end
        if code != 0xFF and i < n:
            out.append(0)
    return bytes(out)


# ---------------------------------------------------------------------------------------- frames

class Frame(NamedTuple):
    version: int
    type: int
    seq: int
    episode_tag: int
    payload: bytes


class FrameError(NamedTuple):
    kind: str
    detail: str


class Gap(NamedTuple):
    expected: int
    got: int
    missing: int


class Duplicate(NamedTuple):
    frame: Frame
    stale: bool          # False: exact replay of the last seq; True: seq went backwards (reordered or late)


Event = Frame | FrameError | Gap | Duplicate


def encode_frame(msg_type: int, seq: int, payload: bytes = b"", episode_tag: int = 0,
                 version: int = PROTOCOL_VERSION) -> bytes:
    """Serialize one frame, COBS-encode it and append the 0x00 delimiter."""
    if not 0 <= msg_type <= 0xFF or not 0 <= seq <= 0xFFFF or not 0 <= episode_tag <= 0xFFFFFFFF:
        raise ValueError("frame header field out of range")
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload of {len(payload)} bytes exceeds {MAX_PAYLOAD}")
    body = struct.pack("<BBHIH", version, msg_type, seq, episode_tag, len(payload)) + payload
    body += struct.pack("<H", crc16_ccitt_false(body))
    return cobs_encode(body) + b"\x00"


def parse_frame_body(raw: bytes, *, version: int = PROTOCOL_VERSION, max_payload: int = MAX_PAYLOAD
                     ) -> Frame | FrameError:
    """Validate a COBS-decoded frame. Order: size, CRC, version, length, so a corrupted header is
    never believed."""
    if len(raw) < HEADER_SIZE + CRC_SIZE:
        return FrameError(ERR_SHORT, f"{len(raw)} bytes")
    (crc,) = struct.unpack("<H", raw[-CRC_SIZE:])
    if crc16_ccitt_false(raw[:-CRC_SIZE]) != crc:
        return FrameError(ERR_CRC, "checksum mismatch")
    ver, mtype, seq, tag, length = struct.unpack("<BBHIH", raw[:HEADER_SIZE])
    if ver != version:
        return FrameError(ERR_VERSION, f"version {ver}, expected {version}")
    if length > max_payload:
        return FrameError(ERR_OVERSIZE, f"payload length {length}")
    if HEADER_SIZE + length + CRC_SIZE != len(raw):
        return FrameError(ERR_LENGTH, f"length field {length} does not match {len(raw)} bytes")
    return Frame(ver, mtype, seq, tag, bytes(raw[HEADER_SIZE:HEADER_SIZE + length]))


class FrameDecoder:
    """Incremental stream decoder. ``feed`` accepts chunks of any size, including one byte.

    ``track_seq`` enables duplicate and gap detection on valid frames. Frames whose type is in
    ``resync_types`` (HELLO) restart the sequence tracking and are always delivered.
    """

    def __init__(self, *, max_payload: int = MAX_PAYLOAD, version: int = PROTOCOL_VERSION,
                 track_seq: bool = True, resync_types: Iterable[int] = ()) -> None:
        self.max_payload = max_payload
        self.version = version
        self.track_seq = track_seq
        self.resync_types = frozenset(resync_types)
        full = max_payload + HEADER_SIZE + CRC_SIZE
        self._max_encoded = full + full // 254 + 2
        self._buf = bytearray()
        self._discarding = False
        self._last_seq: int | None = None
        self.error_count = 0
        self.frames_ok = 0

    def reset_sequence(self) -> None:
        self._last_seq = None

    def feed(self, data: bytes) -> list[Event]:
        events: list[Event] = []
        for byte in data:
            if byte != DELIMITER:
                if self._discarding:
                    continue
                self._buf.append(byte)
                if len(self._buf) > self._max_encoded:
                    self._buf.clear()
                    self._discarding = True
                    events.append(self._error(ERR_OVERSIZE, "frame longer than the maximum"))
                continue
            if self._discarding:                           # end of an oversize frame: resynchronized
                self._discarding = False
                self._buf.clear()
                continue
            if not self._buf:
                continue                                   # idle or doubled delimiter
            encoded = bytes(self._buf)
            self._buf.clear()
            events.extend(self._decode(encoded))
        return events

    def _error(self, kind: str, detail: str) -> FrameError:
        self.error_count += 1
        return FrameError(kind, detail)

    def _decode(self, encoded: bytes) -> list[Event]:
        try:
            raw = cobs_decode(encoded)
        except CobsError as exc:
            return [self._error(ERR_COBS, str(exc))]
        parsed = parse_frame_body(raw, version=self.version, max_payload=self.max_payload)
        if isinstance(parsed, FrameError):
            return [self._error(parsed.kind, parsed.detail)]
        self.frames_ok += 1
        if not self.track_seq:
            return [parsed]
        if parsed.type in self.resync_types or self._last_seq is None:
            self._last_seq = parsed.seq
            return [parsed]
        diff = (parsed.seq - self._last_seq) & 0xFFFF
        if diff == 0:
            return [Duplicate(parsed, stale=False)]
        if diff >= 0x8000:
            return [Duplicate(parsed, stale=True)]
        events: list[Event] = []
        if diff > 1:
            events.append(Gap((self._last_seq + 1) & 0xFFFF, parsed.seq, diff - 1))
        self._last_seq = parsed.seq
        events.append(parsed)
        return events
