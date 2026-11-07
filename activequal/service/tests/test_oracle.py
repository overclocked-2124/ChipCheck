import copy
import unittest

from activequal.model.contract import parse_contract
from activequal.model.errors import InvalidRequest
from activequal.model.examples import oled_example_contract
from activequal.service.oracle import (ALL_REQUIREMENTS_MET, CONDITIONS_NOT_APPLIED, DUT_FAILURE, INCONCLUSIVE,
                                       INSTRUMENT_ERROR, INVALID_EXPERIMENT, MISSING_OBSERVATION, PASS,
                                       REQUIREMENT_VIOLATED, SAFETY_ABORT, UNTRUSTWORTHY_OBSERVATION, Evidence,
                                       classify, judge, margin)

CONTRACT = parse_contract(oled_example_contract(), require_oracle=True)


def requested(**overrides):
    base = {"oledRailV": 3.25, "sensorRailV": 3.30, "redLed": True, "greenLed": False,
            "workload": "oled_refresh", "flashOffsetMs": 0, "dwellMs": 500}
    base.update(overrides)
    return base


def evidence(**overrides):
    base = {"oledLatencyMs": 31.0, "maxHeartbeatGapMs": 200.0, "resetCount": 0.0,
            "measuredOledRailV": 3.248, "measuredDut3v3MinV": 3.30}
    base.update(overrides)
    return Evidence(base)


class MarginTests(unittest.TestCase):
    def test_option_a_formulas_and_clipping(self):
        kw = dict(lo=None, hi=None)
        self.assertEqual(margin("<=", 31, limit=120, nominal=31, **kw), 1.0)
        self.assertEqual(margin("<=", 120, limit=120, nominal=31, **kw), 0.0)
        self.assertAlmostEqual(margin("<=", 75.5, limit=120, nominal=31, **kw), 0.5)
        self.assertEqual(margin("<=", 251, limit=120, nominal=31, **kw), -1.0)   # clipped, not -1.47
        self.assertEqual(margin("<=", 0, limit=120, nominal=31, **kw), 1.0)
        self.assertAlmostEqual(margin(">=", 5, limit=2, nominal=4, lo=None, hi=None), 1.0)
        self.assertAlmostEqual(margin(">=", 3, limit=2, nominal=4, lo=None, hi=None), 0.5)
        self.assertEqual(margin("exact", 0, limit=0, lo=None, hi=None, nominal=None), 1.0)
        self.assertEqual(margin("exact", 3, limit=0, lo=None, hi=None, nominal=None), -1.0)
        band = dict(limit=None, lo=3.135, hi=3.465, nominal=3.30)
        self.assertEqual(margin("band", 3.30, **band), 1.0)
        self.assertAlmostEqual(margin("band", 3.2175, **band), 0.5)
        self.assertEqual(margin("band", 3.465, **band), 0.0)
        self.assertAlmostEqual(margin("band", 3.0, **band), -0.135 / 0.165)
        self.assertEqual(margin("band", 2.9, **band), -1.0)


class JudgeTests(unittest.TestCase):
    def test_less_equal_guard_band(self):
        kw = dict(lo=None, hi=None, limit=120)
        self.assertEqual(judge("<=", 115, 5, **kw), "pass")
        self.assertEqual(judge("<=", 115.1, 5, **kw), "inconclusive")
        self.assertEqual(judge("<=", 125, 5, **kw), "inconclusive")
        self.assertEqual(judge("<=", 125.1, 5, **kw), "fail")
        self.assertEqual(judge("<=", 120, 0, **kw), "pass")
        self.assertEqual(judge("<=", 120.01, 0, **kw), "fail")

    def test_greater_equal_and_band_and_exact(self):
        self.assertEqual(judge(">=", 7, 1, limit=5, lo=None, hi=None), "pass")
        self.assertEqual(judge(">=", 5.5, 1, limit=5, lo=None, hi=None), "inconclusive")
        self.assertEqual(judge(">=", 3.9, 1, limit=5, lo=None, hi=None), "fail")
        band = dict(limit=None, lo=3.135, hi=3.465)
        self.assertEqual(judge("band", 3.30, 0.01, **band), "pass")
        self.assertEqual(judge("band", 3.14, 0.01, **band), "inconclusive")
        self.assertEqual(judge("band", 3.12, 0.01, **band), "fail")
        self.assertEqual(judge("band", 3.47, 0.01, **band), "inconclusive")
        self.assertEqual(judge("band", 3.48, 0.01, **band), "fail")
        self.assertEqual(judge("exact", 0, 0, limit=0, lo=None, hi=None), "pass")
        self.assertEqual(judge("exact", 1, 0, limit=0, lo=None, hi=None), "fail")
        self.assertEqual(judge("exact", 0.5, 1, limit=0, lo=None, hi=None), "inconclusive")


class ClassifyTests(unittest.TestCase):
    def test_nominal_pass(self):
        verdict = classify(CONTRACT, requested(), evidence())
        self.assertEqual((verdict.outcome, verdict.reason_code), (PASS, ALL_REQUIREMENTS_MET))
        self.assertEqual(set(verdict.margins), {"latency", "heartbeat", "reset", "dut_3v3_band"})
        self.assertEqual(verdict.robustness, 1.0)
        self.assertTrue(verdict.trains_planner)

    def test_latency_failure_beyond_guard_band(self):
        verdict = classify(CONTRACT, requested(), evidence(oledLatencyMs=151.0))
        self.assertEqual((verdict.outcome, verdict.reason_code), (DUT_FAILURE, REQUIREMENT_VIOLATED))
        self.assertEqual(verdict.violated, ("latency",))
        self.assertLess(verdict.robustness, 0)
        self.assertAlmostEqual(verdict.margins["latency"], (120 - 151) / (120 - 31))

    def test_latency_in_guard_band_is_inconclusive_not_failure(self):
        for latency in (116.0, 120.0, 124.9):
            verdict = classify(CONTRACT, requested(), evidence(oledLatencyMs=latency))
            self.assertEqual((verdict.outcome, verdict.reason_code), (INVALID_EXPERIMENT, INCONCLUSIVE), latency)
            self.assertEqual(verdict.inconclusive, ("latency",))
            self.assertIsNone(verdict.robustness)
            self.assertFalse(verdict.trains_planner)

    def test_pass_and_failure_robustness_signs_agree_with_the_verdict(self):
        for latency in range(0, 300, 3):
            verdict = classify(CONTRACT, requested(), evidence(oledLatencyMs=float(latency)))
            if verdict.outcome == PASS:
                self.assertGreater(verdict.robustness, 0)
            elif verdict.outcome == DUT_FAILURE:
                self.assertLess(verdict.robustness, 0)

    def test_reset_is_a_failure(self):
        verdict = classify(CONTRACT, requested(), evidence(resetCount=1.0))
        self.assertEqual((verdict.outcome, verdict.violated), (DUT_FAILURE, ("reset",)))
        self.assertEqual(verdict.robustness, -1.0)

    def test_latency_is_not_exercised_when_idle(self):
        verdict = classify(CONTRACT, requested(workload="idle"), Evidence({
            "maxHeartbeatGapMs": 200.0, "resetCount": 0.0, "measuredOledRailV": 3.25, "measuredDut3v3MinV": 3.3}))
        self.assertEqual(verdict.outcome, PASS)
        self.assertNotIn("latency", verdict.margins)
        # Even a huge latency reading is ignored when the workload never exercised the OLED.
        verdict = classify(CONTRACT, requested(workload="idle"), evidence(oledLatencyMs=900.0))
        self.assertEqual(verdict.outcome, PASS)

    def test_missing_required_observation_is_invalid_never_pass_or_failure(self):
        for missing in ("oledLatencyMs", "maxHeartbeatGapMs", "resetCount", "measuredDut3v3MinV"):
            for present_as_none in (False, True):
                values = dict(evidence().observations)
                if present_as_none:
                    values[missing] = None
                else:
                    del values[missing]
                verdict = classify(CONTRACT, requested(), Evidence(values))
                self.assertEqual((verdict.outcome, verdict.reason_code), (INVALID_EXPERIMENT, MISSING_OBSERVATION),
                                 (missing, present_as_none))

    def test_non_finite_observation_is_untrustworthy(self):
        for bad in (float("nan"), float("inf")):
            verdict = classify(CONTRACT, requested(), evidence(oledLatencyMs=bad))
            self.assertEqual((verdict.outcome, verdict.reason_code), (INVALID_EXPERIMENT, UNTRUSTWORTHY_OBSERVATION))

    def test_rail_not_reaching_requested_voltage_is_invalid(self):
        verdict = classify(CONTRACT, requested(), evidence(measuredOledRailV=3.20))
        self.assertEqual((verdict.outcome, verdict.reason_code), (INVALID_EXPERIMENT, CONDITIONS_NOT_APPLIED))
        verdict = classify(CONTRACT, requested(), evidence(measuredOledRailV=3.2799))
        self.assertEqual(verdict.outcome, PASS)       # within the 0.03 V tolerance
        verdict = classify(CONTRACT, requested(), evidence(measuredOledRailV=3.2801))
        self.assertEqual(verdict.reason_code, CONDITIONS_NOT_APPLIED)

    def test_conditions_not_applied_beats_a_failing_requirement(self):
        verdict = classify(CONTRACT, requested(), evidence(measuredOledRailV=3.0, oledLatencyMs=500.0))
        self.assertEqual(verdict.outcome, INVALID_EXPERIMENT)

    def test_safety_trip_beats_everything(self):
        verdict = classify(CONTRACT, requested(), Evidence({}, safety_trip="over-current ch2",
                                                           instrument_errors=("usb timeout",)))
        self.assertEqual(verdict.outcome, SAFETY_ABORT)
        self.assertFalse(verdict.trains_planner)

    def test_instrument_error_is_invalid(self):
        verdict = classify(CONTRACT, requested(), Evidence(dict(evidence().observations),
                                                           instrument_errors=("scope disconnected",)))
        self.assertEqual((verdict.outcome, verdict.reason_code), (INVALID_EXPERIMENT, INSTRUMENT_ERROR))

    def test_failure_wins_over_an_inconclusive_requirement(self):
        verdict = classify(CONTRACT, requested(), evidence(oledLatencyMs=120.0, resetCount=2.0))
        self.assertEqual(verdict.outcome, DUT_FAILURE)
        self.assertEqual(verdict.violated, ("reset",))
        self.assertEqual(verdict.inconclusive, ("latency",))

    def test_band_requirement_on_the_dut_rail(self):
        self.assertEqual(classify(CONTRACT, requested(), evidence(measuredDut3v3MinV=3.0)).violated,
                         ("dut_3v3_band",))

    def test_requested_conditions_are_validated(self):
        with self.assertRaises(InvalidRequest):
            classify(CONTRACT, {"oledRailV": 3.3}, evidence())
        with self.assertRaises(InvalidRequest):
            classify(CONTRACT, requested(oledRailV=float("nan")), evidence())

    def test_oracle_needs_the_oracle_sections(self):
        bare = parse_contract({k: v for k, v in oled_example_contract().items()
                               if k not in ("observations", "requirements", "validity", "safety", "scoring")})
        with self.assertRaises(InvalidRequest):
            classify(bare, requested(), evidence())

    def test_no_exercised_requirement_is_not_a_pass(self):
        contract = oled_example_contract()
        contract["requirements"] = [contract["requirements"][0]]        # latency only
        model = parse_contract(contract, require_oracle=True)
        verdict = classify(model, requested(workload="idle"), evidence())
        self.assertEqual((verdict.outcome, verdict.reason_code), (INVALID_EXPERIMENT, INCONCLUSIVE))

    def test_is_pure(self):
        before = copy.deepcopy(requested())
        ev = evidence()
        classify(CONTRACT, requested(), ev)
        self.assertEqual(requested(), before)
        self.assertEqual(classify(CONTRACT, requested(), ev), classify(CONTRACT, requested(), ev))


if __name__ == "__main__":
    unittest.main()
