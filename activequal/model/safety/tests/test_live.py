import dataclasses
import math
import unittest

from activequal.model.contract import parse_contract
from activequal.model.examples import oled_example_contract
from activequal.model.safety import LiveReadings, capture_trips, live_trips

CONTRACT = parse_contract(oled_example_contract(), require_oracle=True)


def readings(**overrides):
    base = dict(volts={"supply.ch2": 3.3, "supply.ch3": 3.3}, amps={"supply.ch2": 0.05, "supply.ch3": 0.05},
                temp_c=30.0, elapsed_s=2.0)
    base.update(overrides)
    return LiveReadings(**base)


class LiveTripTests(unittest.TestCase):
    def test_nominal_readings_do_not_trip(self):
        self.assertEqual(live_trips(CONTRACT, readings()), ())

    def test_limits_are_exclusive_so_equal_does_not_trip(self):
        at_limit = readings(volts={"supply.ch2": 3.6, "supply.ch3": 3.6}, amps={"supply.ch2": 0.2, "supply.ch3": 0.2},
                            temp_c=60, elapsed_s=10)
        self.assertEqual(live_trips(CONTRACT, at_limit), ())

    def test_each_limit_trips(self):
        cases = {
            "voltage": readings(volts={"supply.ch2": 3.61, "supply.ch3": 3.3}),
            "current": readings(amps={"supply.ch2": 0.05, "supply.ch3": 0.21}),
            "temperature": readings(temp_c=60.1),
            "episode": readings(elapsed_s=10.1),
        }
        for label, value in cases.items():
            trips = live_trips(CONTRACT, value)
            self.assertEqual(len(trips), 1, (label, trips))
            self.assertIn(label[:4], trips[0])

    def test_all_trips_are_reported(self):
        trips = live_trips(CONTRACT, readings(volts={"supply.ch2": 9, "supply.ch3": 9}, temp_c=99, elapsed_s=99))
        self.assertEqual(len(trips), 4)

    def test_missing_or_non_finite_channel_readings_trip(self):
        self.assertEqual(len(live_trips(CONTRACT, readings(volts={"supply.ch2": 3.3}))), 1)
        self.assertEqual(len(live_trips(CONTRACT, readings(amps={}))), 2)
        for bad in (math.nan, math.inf, -math.inf, None, True, "3.3"):
            self.assertTrue(live_trips(CONTRACT, readings(volts={"supply.ch2": bad, "supply.ch3": 3.3})), bad)
            self.assertTrue(live_trips(CONTRACT, readings(amps={"supply.ch2": bad, "supply.ch3": 0.05})), bad)

    def test_missing_or_non_finite_temperature_and_elapsed_trip(self):
        for bad in (None, math.nan, math.inf, "hot"):
            self.assertTrue(live_trips(CONTRACT, readings(temp_c=bad)), bad)
            self.assertTrue(live_trips(CONTRACT, readings(elapsed_s=bad)), bad)

    def test_unevaluable_input_trips(self):
        self.assertTrue(live_trips(dataclasses.replace(CONTRACT, safety=None), readings()))
        self.assertTrue(live_trips(CONTRACT, None))
        self.assertTrue(live_trips(CONTRACT, LiveReadings(volts=None, amps=None, temp_c=30.0, elapsed_s=1.0)))
        self.assertTrue(live_trips(None, readings()))


if __name__ == "__main__":
    unittest.main()


class CaptureTripTests(unittest.TestCase):
    """HLD 03 §13.1: read-backs above the limit trip; within the read-back uncertainty of the limit they do not."""

    def test_nominal_and_at_limit_readings_pass(self):
        self.assertEqual(capture_trips(CONTRACT, {"oledRailV": 3.3}, {"oledRailA": 0.05}), ())
        self.assertEqual(capture_trips(CONTRACT, {"oledRailV": 3.608}, {"oledRailA": 0.2}), ())   # U = 0.01 V

    def test_over_limit_readings_trip(self):
        self.assertIn("voltage on supply.ch2", capture_trips(CONTRACT, {"oledRailV": 3.62}, {})[0])
        self.assertIn("current on supply.ch3", capture_trips(CONTRACT, {}, {"sensorRailA": 0.21})[0])

    def test_non_finite_reading_trips_and_missing_is_not_judged(self):
        self.assertEqual(len(capture_trips(CONTRACT, {"oledRailV": math.nan}, {})), 1)
        self.assertEqual(capture_trips(CONTRACT, {}, {}), ())
