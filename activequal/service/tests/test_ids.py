import unittest
import uuid
from datetime import datetime, timezone

from activequal.service.ids import FixedClock, isoformat, new_id, parse_time


class IdTests(unittest.TestCase):
    def test_uuid7_shape_and_order(self):
        ids = [new_id() for _ in range(5000)]
        self.assertEqual(len(set(ids)), 5000)
        self.assertEqual(ids, sorted(ids), "ids must sort in creation order")
        for text in ids[:20]:
            value = uuid.UUID(text)
            self.assertEqual((value.version, value.variant), (7, uuid.RFC_4122))

    def test_time_round_trip_and_sorting(self):
        early = datetime(2026, 11, 16, 9, 0, 0, 123000, tzinfo=timezone.utc)
        late = datetime(2026, 11, 16, 9, 0, 1, tzinfo=timezone.utc)
        self.assertEqual(isoformat(early), "2026-11-16T09:00:00.123Z")
        self.assertEqual(parse_time(isoformat(early)), early)
        self.assertLess(isoformat(early), isoformat(late))

    def test_fixed_clock(self):
        clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        clock.advance(90)
        self.assertEqual(clock.now(), datetime(2026, 1, 1, 0, 1, 30, tzinfo=timezone.utc))
        with self.assertRaises(ValueError):
            FixedClock(datetime(2026, 1, 1))


if __name__ == "__main__":
    unittest.main()
