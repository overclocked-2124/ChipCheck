import math
import unittest
from datetime import datetime, timezone

from activequal.tools import hardware_check
from activequal.tools.calibrate import CalibrationError, build_record, fit_channel


def points(gain=1.002, offset=-0.004, noise=(0.0, 0.0, 0.0)):
    return [{"setV": v, "readV": v, "meterV": gain * v + offset + n} for v, n in zip((3.0, 3.3, 3.6), noise)]


class CalibrateTests(unittest.TestCase):
    def test_exact_points_recover_gain_and_offset(self):
        fit = fit_channel(points(), 0.002)
        self.assertAlmostEqual(fit.gain, 1.002, places=9)
        self.assertAlmostEqual(fit.offset, -0.004, places=9)
        self.assertAlmostEqual(fit.uncertainty, 0.002, places=9)     # never better than the meter

    def test_residuals_widen_the_uncertainty(self):
        fit = fit_channel(points(noise=(0.003, -0.006, 0.003)), 0.002)
        sigma = math.sqrt(sum(r * r for r in (0.003, -0.006, 0.003)) / 1)     # residuals are exact here
        self.assertAlmostEqual(fit.uncertainty, math.sqrt((2 * sigma) ** 2 + 0.002 ** 2), places=6)

    def test_bad_inputs_are_refused(self):
        for bad in (points()[:2], [{"readV": 3.3, "meterV": 3.3}] * 3, points(gain=1.2),
                    [{"readV": float("nan"), "meterV": 3.0}] + points()[1:]):
            with self.assertRaises(CalibrationError):
                fit_channel(bad, 0.0)

    def test_record_matches_the_control_plane_fields(self):
        now = datetime(2026, 11, 8, tzinfo=timezone.utc)
        record = build_record({"meter": "DMM-1", "meterUncertaintyV": 0.002, "channels": {"supply.ch2": points()}},
                              "dana", now)
        self.assertEqual(set(record), {"channels", "meterIdentity", "operator", "validUntil"})
        self.assertEqual(set(record["channels"]["supply.ch2"]), {"gain", "offset", "uncertainty"})
        self.assertTrue(record["validUntil"].startswith("2026-12-08"))


class HardwareCheckCliTests(unittest.TestCase):
    def test_emulator_self_test_passes(self):
        self.assertEqual(hardware_check.main(["--emulator", "--energize", "--json"]), 0)


if __name__ == "__main__":
    unittest.main()
