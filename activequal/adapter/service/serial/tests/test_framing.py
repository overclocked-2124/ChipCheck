import random
import struct
import unittest

from activequal.adapter.service.serial import framing as fr
from activequal.adapter.service.serial.framing import (Duplicate, Frame, FrameDecoder, FrameError, Gap, cobs_decode,
                                                       cobs_encode, crc16_ccitt_false, encode_frame)

SEQ_RUN = bytes(range(1, 255))        # 254 non-zero bytes


class CrcTests(unittest.TestCase):
    def test_check_value(self):
        self.assertEqual(crc16_ccitt_false(b"123456789"), 0x29B1)
        self.assertEqual(crc16_ccitt_false(b""), 0xFFFF)


class CobsTests(unittest.TestCase):
    VECTORS = [
        (b"", b"\x01"),
        (b"\x00", b"\x01\x01"),
        (b"\x00\x00", b"\x01\x01\x01"),
        (b"\x00\x11\x00", b"\x01\x02\x11\x01"),
        (b"\x11\x22\x00\x33", b"\x03\x11\x22\x02\x33"),
        (b"\x11\x22\x33\x44", b"\x05\x11\x22\x33\x44"),
        (b"\x11\x00\x00\x00", b"\x02\x11\x01\x01\x01"),
        (bytes(range(1, 255)), b"\xff" + bytes(range(1, 255))),                              # 254 bytes
        (b"\x00" + bytes(range(1, 255)), b"\x01\xff" + bytes(range(1, 255))),
        (bytes(range(1, 256)), b"\xff" + bytes(range(1, 255)) + b"\x02\xff"),                # 255 bytes
        (bytes(range(2, 256)) + b"\x00", b"\xff" + bytes(range(2, 256)) + b"\x01\x01"),
        (bytes(range(3, 256)) + b"\x00\x01", b"\xfe" + bytes(range(3, 256)) + b"\x02\x01"),
        (b"\x00" * 254, b"\x01" * 255),
    ]

    def test_standard_vectors(self):
        for plain, encoded in self.VECTORS:
            with self.subTest(plain=plain[:6], n=len(plain)):
                self.assertEqual(cobs_encode(plain), encoded)
                self.assertEqual(cobs_decode(encoded), plain)

    def test_encoded_never_contains_zero_and_round_trips(self):
        rng = random.Random(1)
        for _ in range(500):
            n = rng.choice([0, 1, 2, 253, 254, 255, 256, 508, 509, rng.randrange(0, 700)])
            zeros = rng.choice([0.0, 0.01, 0.5, 1.0])
            data = bytes(0 if rng.random() < zeros else rng.randrange(1, 256) for _ in range(n))
            enc = cobs_encode(data)
            self.assertNotIn(0, enc)
            self.assertEqual(cobs_decode(enc), data)

    def test_decode_rejects_malformed(self):
        for bad in (b"\x05\x01\x02", b"\x01\x00\x01", b"\xff\x01"):
            with self.assertRaises(fr.CobsError):
                cobs_decode(bad)


def random_frame(rng, seq):
    payload = bytes(rng.randrange(256) for _ in range(rng.choice([0, 1, 5, 40, rng.randrange(0, 300)])))
    return Frame(1, rng.randrange(256), seq, rng.getrandbits(32), payload)


def wire(frame):
    return encode_frame(frame.type, frame.seq, frame.payload, frame.episode_tag)


class DecoderTests(unittest.TestCase):
    def test_layout(self):
        data = encode_frame(0x10, 0x0102, b"\xaa\xbb", 0x0A0B0C0D)
        self.assertEqual(data[-1], 0)
        raw = cobs_decode(data[:-1])
        self.assertEqual(raw[:10], struct.pack("<BBHIH", 1, 0x10, 0x0102, 0x0A0B0C0D, 2))
        self.assertEqual(raw[10:12], b"\xaa\xbb")
        self.assertEqual(struct.unpack("<H", raw[-2:])[0], crc16_ccitt_false(raw[:-2]))
        self.assertEqual(len(raw), 10 + 2 + 2)

    def test_round_trip_random_payloads(self):
        rng = random.Random(7)
        decoder = FrameDecoder()
        for seq in range(300):
            f = random_frame(rng, seq)
            self.assertEqual(decoder.feed(wire(f)), [f])

    def test_oversize_encoding_is_refused(self):
        with self.assertRaises(ValueError):
            encode_frame(1, 0, bytes(fr.MAX_PAYLOAD + 1))

    def test_split_at_every_byte_equals_one_shot(self):
        rng = random.Random(3)
        frames = [random_frame(rng, i) for i in range(20)]
        stream = b"".join(wire(f) for f in frames)
        one_shot = FrameDecoder().feed(stream)
        self.assertEqual(one_shot, frames)
        byte_by_byte = []
        decoder = FrameDecoder()
        for b in stream:
            byte_by_byte += decoder.feed(bytes([b]))
        self.assertEqual(byte_by_byte, one_shot)
        for chunk in (2, 3, 7, 64):
            decoder, out = FrameDecoder(), []
            for i in range(0, len(stream), chunk):
                out += decoder.feed(stream[i:i + chunk])
            self.assertEqual(out, one_shot)

    def test_resynchronizes_after_garbage(self):
        rng = random.Random(5)
        good = random_frame(rng, 0)
        decoder = FrameDecoder()
        events = decoder.feed(b"\x13\x37\x55" + wire(good))     # garbage glued to the front of a frame
        self.assertEqual([e for e in events if isinstance(e, Frame)], [])
        self.assertTrue(any(isinstance(e, FrameError) for e in events))
        after = random_frame(rng, 1)
        self.assertEqual(decoder.feed(wire(after)), [after])        # the stream is alive again

    def test_error_kinds(self):
        body = struct.pack("<BBHIH", 1, 5, 1, 0, 0)
        crc = struct.pack("<H", crc16_ccitt_false(body))
        bad_crc = cobs_encode(body + b"\x00\x00") + b"\x00"
        self.assertEqual(FrameDecoder().feed(bad_crc)[0].kind, fr.ERR_CRC)
        wrong_version = struct.pack("<BBHIH", 2, 5, 1, 0, 0)
        wrong_version += struct.pack("<H", crc16_ccitt_false(wrong_version))
        self.assertEqual(FrameDecoder().feed(cobs_encode(wrong_version) + b"\x00")[0].kind, fr.ERR_VERSION)
        bad_len = struct.pack("<BBHIH", 1, 5, 1, 0, 7)           # claims 7 payload bytes, has none
        bad_len += struct.pack("<H", crc16_ccitt_false(bad_len))
        self.assertEqual(FrameDecoder().feed(cobs_encode(bad_len) + b"\x00")[0].kind, fr.ERR_LENGTH)
        huge = struct.pack("<BBHIH", 1, 5, 1, 0, fr.MAX_PAYLOAD + 1) + bytes(fr.MAX_PAYLOAD + 1)
        huge += struct.pack("<H", crc16_ccitt_false(huge))
        self.assertEqual(FrameDecoder().feed(cobs_encode(huge) + b"\x00")[0].kind, fr.ERR_OVERSIZE)
        self.assertEqual(FrameDecoder().feed(cobs_encode(b"\x01\x02") + b"\x00")[0].kind, fr.ERR_SHORT)
        self.assertEqual(FrameDecoder().feed(b"\x09\x01\x00")[0].kind, fr.ERR_COBS)
        self.assertEqual(crc, crc)

    def test_endless_garbage_is_bounded_and_recovers(self):
        decoder = FrameDecoder()
        events = decoder.feed(b"\x55" * 5000)
        self.assertEqual([e.kind for e in events], [fr.ERR_OVERSIZE])           # reported once
        good = Frame(1, 9, 0, 0, b"ok")
        events = decoder.feed(b"\x00" + wire(good))
        self.assertEqual(events, [good])

    def test_duplicate_and_gap_detection(self):
        decoder = FrameDecoder()
        f = lambda seq: Frame(1, 4, seq, 0, b"")
        self.assertEqual(decoder.feed(wire(f(10))), [f(10)])
        self.assertEqual(decoder.feed(wire(f(10))), [Duplicate(f(10), stale=False)])
        self.assertEqual(decoder.feed(wire(f(11))), [f(11)])
        self.assertEqual(decoder.feed(wire(f(14))), [Gap(12, 14, 2), f(14)])
        self.assertEqual(decoder.feed(wire(f(12))), [Duplicate(f(12), stale=True)])     # late / reordered
        self.assertEqual(decoder.feed(wire(f(15))), [f(15)])

    def test_sequence_wraps(self):
        decoder = FrameDecoder()
        for seq in (0xFFFE, 0xFFFF, 0, 1):
            frame = Frame(1, 4, seq, 0, b"")
            self.assertEqual(decoder.feed(wire(frame)), [frame])

    def test_resync_type_restarts_tracking(self):
        decoder = FrameDecoder(resync_types=[1])
        decoder.feed(wire(Frame(1, 4, 500, 0, b"")))
        hello = Frame(1, 1, 0, 0, b"")
        self.assertEqual(decoder.feed(wire(hello)), [hello])
        self.assertEqual(decoder.feed(wire(Frame(1, 4, 1, 0, b""))), [Frame(1, 4, 1, 0, b"")])


class PropertyTests(unittest.TestCase):
    def test_single_bit_corruption_is_never_delivered_as_valid(self):
        rng = random.Random(11)
        for seq in range(120):
            f = random_frame(rng, seq)
            f = f._replace(payload=f.payload[:60])
            sentinel = Frame(1, 77, (seq + 1) & 0xFFFF, 0, b"sentinel")
            encoded = bytearray(wire(f))
            for bit in range(8 * len(encoded)):
                corrupted = bytearray(encoded)
                corrupted[bit // 8] ^= 1 << (bit % 8)
                decoder = FrameDecoder(track_seq=False)
                events = decoder.feed(bytes(corrupted) + wire(sentinel))
                delivered = [e for e in events if isinstance(e, Frame)]
                self.assertNotIn(f, delivered, f"bit {bit} of frame {seq}")
                for d in delivered:
                    self.assertIn(d, (f, sentinel), "a wrongly decoded frame was delivered")
                # Anything other than the delimiter bit must also stop the corrupted frame itself.
                if bit // 8 != len(encoded) - 1:
                    self.assertNotIn(f, delivered)
                    # and the stream recovers by the next frame
                    self.assertEqual(decoder.feed(wire(Frame(1, 78, 9, 0, b"x"))), [Frame(1, 78, 9, 0, b"x")])

    def test_dropped_duplicated_reordered_bytes_never_yield_a_wrong_valid_frame(self):
        rng = random.Random(21)
        sent = [random_frame(rng, i)._replace(payload=bytes(rng.randrange(256) for _ in range(rng.randrange(0, 40))))
                for i in range(12)]
        clean = b"".join(wire(f) for f in sent)
        valid = set(sent)
        for trial in range(3000):
            data = bytearray(clean)
            for _ in range(rng.randrange(1, 4)):
                op = rng.choice(["drop", "dup", "swap", "dupchunk", "dropchunk"])
                i = rng.randrange(len(data))
                if op == "drop":
                    del data[i]
                elif op == "dup":
                    data.insert(i, data[i])
                elif op == "swap" and i + 1 < len(data):
                    data[i], data[i + 1] = data[i + 1], data[i]
                elif op == "dupchunk":
                    n = rng.randrange(1, 30)
                    data[i:i] = data[i:i + n]
                elif op == "dropchunk":
                    del data[i:i + rng.randrange(1, 30)]
            for e in FrameDecoder(track_seq=False).feed(bytes(data)):
                if isinstance(e, Frame):
                    self.assertIn(e, valid, f"trial {trial}: wrong frame delivered")

    def test_random_byte_streams_never_raise(self):
        rng = random.Random(31)
        decoder = FrameDecoder()
        for _ in range(300):
            decoder.feed(bytes(rng.randrange(256) for _ in range(rng.randrange(0, 400))))


if __name__ == "__main__":
    unittest.main()
