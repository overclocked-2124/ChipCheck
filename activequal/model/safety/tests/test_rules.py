"""Decision coverage of every safety rule: valid baseline plus one defect (HLD 10 §4)."""

import copy
import dataclasses
import unittest

from activequal.model.contract import ContractModel, parse_contract
from activequal.model.examples import oled_example_contract
from activequal.model.safety import SHUTDOWN_ALLOWANCE_S, SafetyDecision, Violation, check_candidate
from activequal.model.safety import rules

CAPS = frozenset({"supply.ch2", "supply.ch3", "dut", "mcu"})


def build(mutate=None):
    raw = oled_example_contract()
    if mutate:
        mutate(raw)
    return parse_contract(raw, require_oracle=True)


def replace_control(contract, name, **changes):
    controls = dict(contract.controls)
    controls[name] = dataclasses.replace(controls[name], **changes)
    return dataclasses.replace(contract, controls=controls)


def with_safety(contract, **changes):
    return dataclasses.replace(contract, safety=dataclasses.replace(contract.safety, **changes))


def with_channel_max(contract, target, max_v):
    channels = {**contract.safety.channels, target: {**contract.safety.channels[target], "maxV": max_v}}
    return with_safety(contract, channels=channels)


CONTRACT = build()


def baseline(**overrides):
    values = {"oledRailV": 3.30, "sensorRailV": 3.30, "redLed": False, "greenLed": False, "workload": "idle",
              "flashOffsetMs": 0, "dwellMs": 500}
    values.update(overrides)
    return values


class RuleTestCase(unittest.TestCase):
    def codes(self, conditions, contract=CONTRACT, **kwargs):
        return check_candidate(contract, conditions, **kwargs).codes

    def assertRejected(self, code, conditions, contract=CONTRACT, **kwargs):
        decision = check_candidate(contract, conditions, **kwargs)
        self.assertFalse(decision.approved, conditions)
        self.assertIn(code, decision.codes)
        return decision

    def assertApproved(self, conditions, contract=CONTRACT, **kwargs):
        decision = check_candidate(contract, conditions, **kwargs)
        self.assertTrue(decision.approved, decision.violations)


class DecisionTests(RuleTestCase):
    def test_approved_is_derived_from_violations(self):
        self.assertTrue(SafetyDecision().approved)
        self.assertTrue(SafetyDecision([]).approved)
        decision = SafetyDecision([Violation("WRONG_TYPE", "x", "m")])
        self.assertFalse(decision.approved)
        self.assertIsInstance(decision.violations, tuple)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            decision.violations = ()
        with self.assertRaises(TypeError):
            SafetyDecision(True, ())

    def test_all_reported_codes_are_stable_strings(self):
        for code in rules.CODES:
            self.assertEqual(getattr(rules, code), code)
        self.assertEqual(len(rules.CODES), 15)

    def test_deterministic_and_does_not_mutate_inputs(self):
        conditions = baseline(oledRailV=9.0, workload="x")
        snapshot = copy.deepcopy(conditions)
        first = check_candidate(CONTRACT, conditions)
        self.assertEqual(first, check_candidate(CONTRACT, conditions))
        self.assertEqual(conditions, snapshot)
        self.assertEqual(SHUTDOWN_ALLOWANCE_S, 0.5)


class StructureTests(RuleTestCase):
    def test_baseline_and_with_all_options_approved(self):
        self.assertApproved(baseline())
        self.assertApproved(baseline(), fixture_capabilities=CAPS, contract_hash="a", expected_hash="a",
                            previous=baseline(oledRailV=3.0))

    def test_invalid_inputs_fail_closed(self):
        self.assertRejected("UNEVALUABLE", None)
        self.assertRejected("UNEVALUABLE", [1, 2])
        self.assertRejected("UNEVALUABLE", baseline(), contract=None)
        self.assertRejected("UNEVALUABLE", baseline(), contract={"controls": {}})
        self.assertRejected("UNEVALUABLE", baseline(), contract=dataclasses.replace(CONTRACT, safety=None))

    def test_unknown_and_missing_controls(self):
        decision = self.assertRejected("UNKNOWN_CONTROL", baseline(extra=1))
        self.assertEqual({v.control for v in decision.violations}, {"extra"})
        self.assertRejected("UNKNOWN_CONTROL", {**baseline(), 7: 1})
        decision = self.assertRejected("MISSING_CONTROL", {k: v for k, v in baseline().items() if k != "redLed"})
        self.assertEqual(decision.violations[0].control, "redLed")
        self.assertRejected("MISSING_CONTROL", {})

    def test_all_violations_are_collected(self):
        decision = check_candidate(CONTRACT, baseline(oledRailV=9.0, workload="bogus", extra=1))
        self.assertTrue({"VALUE_OUT_OF_RANGE", "NOT_IN_VALUES", "UNKNOWN_CONTROL", "CHANNEL_VOLTAGE_LIMIT"}
                        <= decision.codes)


class NumericTests(RuleTestCase):
    def test_wrong_types(self):
        nan, inf = float("nan"), float("inf")
        for bad in (True, False, "3.3", None, nan, inf, -inf, [3.3], {"v": 3.3}, b"3.3", 3.3 + 0j):
            with self.subTest(bad=bad):
                self.assertRejected("WRONG_TYPE", baseline(oledRailV=bad))
                self.assertRejected("WRONG_TYPE", baseline(dwellMs=bad))
                self.assertRejected("WRONG_TYPE", baseline(flashOffsetMs=bad))

    def test_range_is_inclusive(self):
        self.assertApproved(baseline(oledRailV=3.0, sensorRailV=3.0))
        self.assertApproved(baseline(oledRailV=3.6, sensorRailV=3.54))
        self.assertApproved(baseline(dwellMs=200))
        self.assertApproved(baseline(dwellMs=2000))
        for bad in (2.99, 3.61, -3.3, 10 ** 400, -10 ** 400, 10 ** 5000):
            self.assertRejected("VALUE_OUT_OF_RANGE", baseline(oledRailV=bad))
        self.assertRejected("VALUE_OUT_OF_RANGE", baseline(dwellMs=100))
        self.assertRejected("VALUE_OUT_OF_RANGE", baseline(dwellMs=2100))

    def test_step_grid_uses_decimal_not_float_modulo(self):
        for good in (3.01, 3.07, 3.29, 3.31, 3.58):
            self.assertApproved(baseline(oledRailV=good))
        for bad in (3.305, 3.3000000000000003, 3.3100000000000005, 3.299999999999999, 3.0000001):
            self.assertRejected("OFF_STEP_GRID", baseline(oledRailV=bad))
        self.assertRejected("OFF_STEP_GRID", baseline(dwellMs=250))
        self.assertRejected("OFF_STEP_GRID", baseline(dwellMs=250.5))
        self.assertApproved(baseline(dwellMs=300.0))
        self.assertApproved(baseline(dwellMs=300))

    def test_integer_kind_requires_whole_values(self):
        contract = replace_control(CONTRACT, "dwellMs", minimum=200.5, maximum=2000.5, step=0.5, nominal=500.5)
        self.assertRejected("OFF_STEP_GRID", baseline(dwellMs=300.5), contract=contract)
        self.assertApproved(baseline(dwellMs=300), contract=replace_control(
            CONTRACT, "dwellMs", minimum=200, maximum=2000, step=50))

    def test_unevaluable_numeric_specs(self):
        self.assertRejected("UNEVALUABLE", baseline(), contract=replace_control(CONTRACT, "dwellMs", minimum=None))
        self.assertRejected("UNEVALUABLE", baseline(), contract=replace_control(CONTRACT, "dwellMs", step=0))
        self.assertRejected("UNEVALUABLE", baseline(), contract=replace_control(CONTRACT, "redLed", kind="weird"))


class EnumerationTests(RuleTestCase):
    def test_boolean(self):
        for bad in (1, 0, "true", None, 1.0):
            self.assertRejected("WRONG_TYPE", baseline(redLed=bad))
        self.assertApproved(baseline(redLed=True, greenLed=True))

    def test_categorical(self):
        for bad in (5, None, True, ["idle"], 1.5):
            self.assertRejected("WRONG_TYPE", baseline(workload=bad))
        for bad in ("IDLE", "bogus", "", " idle"):
            self.assertRejected("NOT_IN_VALUES", baseline(workload=bad))
        for good in ("idle", "oled_refresh", "sensor_read"):
            self.assertApproved(baseline(workload=good))
        self.assertRejected("NOT_IN_VALUES", baseline(), contract=replace_control(CONTRACT, "workload", values=None))


class ActivationTests(RuleTestCase):
    def test_inactive_control_must_be_nominal(self):
        self.assertRejected("INACTIVE_CONTROL_NOT_NOMINAL", baseline(flashOffsetMs=5))
        self.assertRejected("INACTIVE_CONTROL_NOT_NOMINAL", baseline(flashOffsetMs=5, workload="sensor_read"))
        self.assertApproved(baseline(flashOffsetMs=0, workload="oled_refresh"))

    def test_active_control_may_vary(self):
        self.assertApproved(baseline(flashOffsetMs=5, workload="flash_write"))
        self.assertApproved(baseline(flashOffsetMs=20, workload="flash_write", sensorRailV=3.54))

    def test_nominal_comparison_for_boolean_and_categorical(self):
        gated = replace_control(replace_control(CONTRACT, "greenLed", active_when={"control": "redLed", "eq": True}),
                                "workload", active_when={"control": "redLed", "eq": True})
        self.assertRejected("INACTIVE_CONTROL_NOT_NOMINAL", baseline(greenLed=True), contract=gated)
        self.assertRejected("INACTIVE_CONTROL_NOT_NOMINAL", baseline(workload="sensor_read"), contract=gated)
        self.assertApproved(baseline(redLed=True, greenLed=True, workload="sensor_read"), contract=gated)

    def test_unevaluable_activation_is_rejected(self):
        gated = replace_control(CONTRACT, "greenLed", active_when={"control": "workload", "gt": 3})
        self.assertRejected("UNEVALUABLE", baseline(), contract=gated)             # unorderable
        by_bad = replace_control(CONTRACT, "greenLed", active_when={"control": "workload", "eq": "idle"})
        self.assertRejected("UNEVALUABLE", baseline(workload=5), contract=by_bad)  # referenced value wrong type
        decision = self.assertRejected("MISSING_CONTROL", {k: v for k, v in baseline().items() if k != "workload"},
                                       contract=by_bad)
        self.assertIn("UNEVALUABLE", decision.codes)
        self.assertRejected("UNEVALUABLE", baseline(), contract=replace_control(CONTRACT, "greenLed", active_when={}))

    def test_wrong_type_of_inactive_control_is_still_one_rejection(self):
        self.assertRejected("WRONG_TYPE", baseline(flashOffsetMs="x"))


class ForbiddenTests(RuleTestCase):
    def test_forbidden_combination(self):
        self.assertRejected("FORBIDDEN_COMBINATION", baseline(workload="flash_write", sensorRailV=3.55))
        self.assertRejected("FORBIDDEN_COMBINATION", baseline(workload="flash_write", sensorRailV=3.6))
        self.assertApproved(baseline(workload="flash_write", sensorRailV=3.54))
        self.assertApproved(baseline(workload="idle", sensorRailV=3.6))

    def test_unorderable_counts_as_forbidden(self):
        rule = {"all": [{"control": "workload", "gt": 3}]}
        contract = dataclasses.replace(CONTRACT, forbidden=[rule])
        self.assertRejected("FORBIDDEN_COMBINATION", baseline(), contract=contract)

    def test_rule_on_unusable_value_or_malformed_rule_is_unevaluable(self):
        self.assertRejected("UNEVALUABLE", baseline(workload=5, sensorRailV=3.6))
        self.assertRejected("UNEVALUABLE", baseline(sensorRailV=None))
        contract = dataclasses.replace(CONTRACT, forbidden=[{}])
        self.assertRejected("UNEVALUABLE", baseline(), contract=contract)
        contract = dataclasses.replace(CONTRACT, forbidden=[{"all": [{"control": "nope", "eq": 1}]}])
        self.assertRejected("UNEVALUABLE", baseline(), contract=contract)


class ChannelTests(RuleTestCase):
    def test_voltage_must_not_exceed_channel_maxv(self):
        limited = build(lambda raw: raw["safety"]["channels"]["supply.ch2"].update(maxV=3.4))
        self.assertApproved(baseline(oledRailV=3.4), contract=limited)
        self.assertRejected("CHANNEL_VOLTAGE_LIMIT", baseline(oledRailV=3.41), contract=limited)
        self.assertApproved(baseline(sensorRailV=3.6), contract=limited)   # other channel unaffected

    def test_voltage_control_without_declared_channel_is_rejected(self):
        unbound = replace_control(CONTRACT, "oledRailV", bind=None)
        self.assertRejected("CHANNEL_CAPABILITY_MISSING", baseline(), contract=unbound)
        other = replace_control(CONTRACT, "oledRailV", bind=("supply.ch9", "setVoltage"))
        self.assertRejected("CHANNEL_CAPABILITY_MISSING", baseline(), contract=other)

    def test_non_volt_numeric_controls_are_not_voltage_checked(self):
        mislabelled = with_safety(CONTRACT, channels={"supply.ch2": {"maxA": 0.2, "maxV": 1.0},
                                                      "supply.ch3": {"maxA": 0.2, "maxV": 3.6}})
        self.assertRejected("CHANNEL_VOLTAGE_LIMIT", baseline(), contract=mislabelled)
        decision = check_candidate(mislabelled, baseline(dwellMs=2000))
        self.assertEqual({v.control for v in decision.violations if v.code == "CHANNEL_VOLTAGE_LIMIT"},
                         {"oledRailV"})

    def test_fixture_capabilities(self):
        self.assertApproved(baseline(), fixture_capabilities=CAPS)
        self.assertApproved(baseline(), fixture_capabilities=set(CAPS))
        decision = self.assertRejected("CHANNEL_CAPABILITY_MISSING", baseline(),
                                       fixture_capabilities=frozenset({"supply.ch2", "dut", "mcu"}))
        self.assertEqual([v.control for v in decision.violations], ["sensorRailV"])
        self.assertRejected("CHANNEL_CAPABILITY_MISSING", baseline(), fixture_capabilities=frozenset())
        self.assertRejected("UNEVALUABLE", baseline(), fixture_capabilities="supply.ch2")


class TimeTests(RuleTestCase):
    def test_boundary_is_inclusive(self):
        edge = with_safety(CONTRACT, max_episode_s=9.7)   # 3.6/0.5 + 2.0 + 0.5
        self.assertApproved(baseline(oledRailV=3.6, dwellMs=2000), contract=edge)
        tight = with_safety(CONTRACT, max_episode_s=9.69)
        self.assertRejected("EPISODE_TIME_BUDGET", baseline(oledRailV=3.6, dwellMs=2000), contract=tight)

    def test_ramp_alone_too_long(self):
        contract = with_safety(CONTRACT, max_episode_s=7.3)
        decision = self.assertRejected("SLEW_OR_RAMP_TOO_LONG", baseline(oledRailV=3.6), contract=contract)
        self.assertEqual([v.control for v in decision.violations if v.code == "SLEW_OR_RAMP_TOO_LONG"],
                         ["oledRailV"])
        self.assertApproved(baseline(oledRailV=3.3, sensorRailV=3.3, dwellMs=200), contract=contract)

    def test_ramp_plus_dwell_over_budget_but_ramp_fits(self):
        contract = with_safety(CONTRACT, max_episode_s=8.0)
        decision = self.assertRejected("EPISODE_TIME_BUDGET", baseline(oledRailV=3.6, dwellMs=1000),
                                       contract=contract)
        self.assertNotIn("SLEW_OR_RAMP_TOO_LONG", decision.codes)
        self.assertApproved(baseline(oledRailV=3.6, dwellMs=200), contract=contract)

    def test_duration_control_longer_than_episode(self):
        contract = with_safety(CONTRACT, max_episode_s=1.5)
        self.assertRejected("DURATION_EXCEEDS_MAX", baseline(dwellMs=1100), contract=contract)
        decision = check_candidate(contract, baseline(dwellMs=200))
        self.assertNotIn("DURATION_EXCEEDS_MAX", decision.codes)

    def test_duration_in_seconds_and_missing_dwell(self):
        seconds = replace_control(CONTRACT, "dwellMs", unit="s", minimum=0.2, maximum=20.0, step=0.2, nominal=0.4)
        self.assertRejected("DURATION_EXCEEDS_MAX", baseline(dwellMs=9.8), contract=seconds)
        self.assertRejected("EPISODE_TIME_BUDGET", baseline(dwellMs=3.0), contract=seconds)
        self.assertApproved(baseline(dwellMs=1.0), contract=seconds)
        controls = {k: v for k, v in CONTRACT.controls.items() if k != "dwellMs"}
        no_dwell = dataclasses.replace(CONTRACT, controls=controls)
        values = baseline()
        del values["dwellMs"]
        self.assertApproved(values, contract=no_dwell)

    def test_non_duration_ms_control_is_not_a_duration(self):
        contract = with_safety(CONTRACT, max_episode_s=1.0)
        self.assertNotIn("DURATION_EXCEEDS_MAX", self.codes(baseline(flashOffsetMs=0, dwellMs=200), contract=contract))
        other_unit = replace_control(CONTRACT, "dwellMs", unit="min")   # cannot be converted: fail closed
        self.assertRejected("UNEVALUABLE", baseline(), contract=other_unit)

    def test_any_duration_control_counts_toward_the_episode_time(self):
        renamed = replace_control(CONTRACT, "dwellMs", unit="s")
        controls = {("holdS" if k == "dwellMs" else k): v for k, v in renamed.controls.items()}
        contract = with_safety(dataclasses.replace(renamed, controls=controls), max_episode_s=8.0)
        values = baseline()
        values["holdS"] = values.pop("dwellMs")
        values["holdS"] = 7.9
        self.assertRejected("EPISODE_TIME_BUDGET", values, contract=contract)

    def test_unitless_control_bound_to_a_channel_is_still_voltage_limited(self):
        no_unit = replace_control(CONTRACT, "oledRailV", unit=None)
        self.assertRejected("CHANNEL_VOLTAGE_LIMIT", baseline(oledRailV=3.6),
                            contract=with_channel_max(no_unit, "supply.ch2", 3.4))

    def test_unevaluable_time(self):
        no_shutdown = replace_control(CONTRACT, "oledRailV", shutdown=None)
        self.assertRejected("UNEVALUABLE", baseline(), contract=no_shutdown)
        bad_slew = replace_control(CONTRACT, "oledRailV", slew_per_s_max=-1.0)
        self.assertRejected("UNEVALUABLE", baseline(), contract=bad_slew)
        self.assertRejected("UNEVALUABLE", baseline(oledRailV="x"))
        self.assertRejected("UNEVALUABLE", baseline(dwellMs=None))
        self.assertRejected("UNEVALUABLE", baseline(dwellMs=float("nan")))

    def test_previous_step_must_respect_slew(self):
        # shutdown 3.3 and 0.1 V/s: ramp <= 3 s, window 3.2 s, so at most 0.32 V per step.
        slow = replace_control(replace_control(CONTRACT, "oledRailV", shutdown=3.3, slew_per_s_max=0.1),
                               "sensorRailV", shutdown=3.3, slew_per_s_max=0.1)
        current = baseline(oledRailV=3.3, dwellMs=200)
        self.assertApproved(current, contract=slow, previous=baseline(oledRailV=3.3))
        self.assertApproved(baseline(oledRailV=3.6, dwellMs=200), contract=slow, previous=baseline(oledRailV=3.3))
        self.assertRejected("SLEW_OR_RAMP_TOO_LONG", baseline(oledRailV=3.6, dwellMs=200), contract=slow,
                            previous=baseline(oledRailV=3.0))
        self.assertRejected("UNEVALUABLE", current, contract=slow, previous=baseline(oledRailV="x"))
        self.assertRejected("UNEVALUABLE", current, contract=slow, previous={"dwellMs": 500})
        self.assertRejected("UNEVALUABLE", current, previous=["not", "a", "dict"])


class StaleTests(RuleTestCase):
    def test_hashes(self):
        self.assertApproved(baseline(), contract_hash="abc", expected_hash="abc")
        self.assertRejected("STALE_CONTRACT", baseline(), contract_hash="abc", expected_hash="abd")
        self.assertRejected("STALE_CONTRACT", baseline(), contract_hash="abc")
        self.assertRejected("STALE_CONTRACT", baseline(), expected_hash="abc")
        self.assertRejected("STALE_CONTRACT", baseline(), contract_hash=1, expected_hash=1)
        self.assertApproved(baseline())


class FailClosedTests(RuleTestCase):
    def test_exception_inside_a_rule_is_a_rejection(self):
        class Exploding(dict):
            def __getitem__(self, key):
                raise RuntimeError("boom")

        decision = self.assertRejected("UNEVALUABLE", Exploding(baseline()))
        self.assertFalse(decision.approved)

    def test_exception_outside_rules_never_approves_or_raises(self):
        class Broken(dict):
            def __iter__(self):
                raise RuntimeError("boom")

        decision = self.assertRejected("UNEVALUABLE", Broken(baseline()))
        self.assertEqual(len(decision.violations), 1)

    def test_weird_keys_and_values_do_not_raise(self):
        class Nasty:
            def __repr__(self):
                raise RuntimeError("no repr")

        for conditions in (baseline(oledRailV=Nasty()), {Nasty(): 1, **baseline()}, {None: 1}, {(1, 2): 3}):
            self.assertFalse(check_candidate(CONTRACT, conditions).approved)


if __name__ == "__main__":
    unittest.main()
