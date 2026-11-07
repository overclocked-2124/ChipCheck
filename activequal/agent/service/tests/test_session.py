import unittest

from activequal.agent.service.plan import PlanConfig, plan_config
from activequal.agent.service.session import FAIL, PASS, REJECTED, verification_session
from activequal.model.contract import parse_contract
from activequal.model.errors import InvalidRequest
from activequal.model.examples import oled_example_contract

MODEL = parse_contract(oled_example_contract(), require_oracle=True)
TRIGGER = {"oledRailV": 3.27, "sensorRailV": 3.33, "redLed": True, "greenLed": False, "workload": "oled_refresh",
           "flashOffsetMs": 0, "dwellMs": 700}


def truth(c):
    """The failure needs red on, green off, the OLED workload and a rail in 3.22..3.28 V."""
    return c["redLed"] and not c["greenLed"] and c["workload"] == "oled_refresh" and 3.22 <= c["oledRailV"] <= 3.28


def drive(trigger=TRIGGER, plan=None, budget=24, oracle=truth, rejected=lambda c: False, flaky=None):
    plan = plan or PlanConfig(50, budget)
    session = verification_session(MODEL, trigger, plan, budget)
    log, replay = [], 0
    try:
        request = next(session)
        while True:
            if rejected(request.conditions):
                outcome = REJECTED
            elif request.role == "confirm" and flaky is not None:
                outcome = flaky[replay]
                replay += 1
            else:
                outcome = FAIL if oracle(request.conditions) else PASS
            log.append((request, outcome))
            request = session.send(outcome)
    except StopIteration as done:
        return log, done.value


class ConfirmTests(unittest.TestCase):
    def test_two_failures_confirm_immediately(self):
        log, summary = drive()
        self.assertEqual([r.role for r, _ in log[:2]], ["confirm", "confirm"])
        self.assertEqual((summary.status, summary.replays, summary.reproductions), ("confirmed", 2, 2))
        self.assertEqual(summary.reproduction_rate, 1.0)

    def test_two_passes_mark_it_transient_and_stop(self):
        log, summary = drive(flaky=[PASS, PASS, FAIL])
        self.assertEqual((summary.status, len(log)), ("transient", 2))
        self.assertEqual(summary.minimized, TRIGGER)

    def test_split_result_is_decided_by_the_third_replay(self):
        _, confirmed = drive(flaky=[FAIL, PASS, FAIL])
        self.assertEqual((confirmed.status, confirmed.replays, confirmed.reproductions), ("confirmed", 3, 2))
        _, transient = drive(flaky=[PASS, FAIL, PASS])
        self.assertEqual((transient.status, transient.replays, transient.reproductions), ("transient", 3, 1))

    def test_unusable_replays_count_toward_neither_verdict(self):
        log, summary = drive(flaky=["INVALID_EXPERIMENT", "INVALID_EXPERIMENT", "INVALID_EXPERIMENT"])
        self.assertEqual((summary.status, summary.replays, len(log)), ("inconclusive", 0, 3))

    def test_no_budget_means_unverified(self):
        log, summary = drive(budget=0)
        self.assertEqual((summary.status, len(log), summary.budget_exhausted), ("unverified", 0, True))


class MinimizeTests(unittest.TestCase):
    def test_minimizes_discrete_controls_then_probes_necessity_then_brackets(self):
        log, summary = drive()
        roles = [r.role for r, _ in log]
        self.assertEqual(roles[:2], ["confirm"] * 2)
        self.assertLess(roles.index("minimize"), roles.index("necessity_probe"))
        self.assertLess(roles.index("necessity_probe"), roles.index("bracket"))
        self.assertEqual(set(summary.removed), {"sensorRailV", "dwellMs"})     # irrelevant: failure persists at nominal
        self.assertEqual(set(summary.kept), {"oledRailV", "redLed", "workload"})
        self.assertEqual(summary.minimized["sensorRailV"], 3.30)
        self.assertEqual(summary.minimized["dwellMs"], 500)
        self.assertEqual(summary.minimized["redLed"], True)
        self.assertEqual(summary.necessity, {"greenLed": "necessary"})        # green off is needed: flipping it passes

    def test_minimization_never_changes_more_than_one_control_per_step(self):
        log, _ = drive()
        previous = TRIGGER
        for request, outcome in log:
            if request.role == "minimize":
                changed = [k for k in TRIGGER if request.conditions[k] != previous[k]]
                self.assertEqual(len(changed), 1)
                if outcome == FAIL:
                    previous = request.conditions

    def test_necessity_probe_reports_irrelevant_controls(self):
        def indifferent_to_green(c):
            return c["redLed"] and c["workload"] == "oled_refresh" and 3.22 <= c["oledRailV"] <= 3.28
        trigger = {**TRIGGER}
        _, summary = drive(trigger, oracle=indifferent_to_green)
        self.assertEqual(summary.necessity, {"greenLed": "not_necessary"})

    def test_probes_can_be_switched_off(self):
        log, summary = drive(plan=PlanConfig(50, 24, necessity_probes=False))
        self.assertNotIn("necessity_probe", [r.role for r, _ in log])
        self.assertEqual(summary.necessity, {})

    def test_activewhen_dependents_are_pinned(self):
        trigger = {**TRIGGER, "workload": "flash_write", "flashOffsetMs": 12, "sensorRailV": 3.4}
        log, summary = drive(trigger, oracle=lambda c: c["workload"] == "flash_write" and c["oledRailV"] <= 3.3)
        for request, _ in log:
            if request.conditions["workload"] != "flash_write":
                self.assertEqual(request.conditions["flashOffsetMs"], 0)       # inactive control held at nominal
        self.assertIn("flashOffsetMs", summary.removed + summary.kept)


class BracketTests(unittest.TestCase):
    def test_voltage_interval_is_found_to_one_step(self):
        _, summary = drive()
        interval = summary.intervals["oledRailV"]
        self.assertEqual((interval["low"], interval["high"]), (3.22, 3.28))
        for side, first_pass in (("low", 3.21), ("high", 3.29)):
            self.assertEqual(interval["sides"][side]["firstPass"], first_pass)
            self.assertEqual(interval["sides"][side]["note"], "resolved")
            self.assertAlmostEqual(interval["sides"][side]["resolution"], 0.01, places=9)

    def test_irrelevant_moved_controls_cost_two_end_probes_and_are_open(self):
        log, summary = drive()
        sensor = summary.intervals["sensorRailV"]
        self.assertEqual((sensor["low"], sensor["high"]), (3.0, 3.6))
        self.assertTrue(all(side["note"].startswith("open") for side in sensor["sides"].values()))
        self.assertEqual(sum(1 for r, _ in log if r.role == "bracket" and "sensorRailV" in r.reason), 2)

    def test_total_cost_fits_the_default_24_episode_pool(self):
        log, summary = drive()
        self.assertLessEqual(summary.episodes_used, 24)
        self.assertFalse(summary.budget_exhausted)

    def test_budget_exhaustion_reports_the_achieved_resolution(self):
        log, summary = drive(budget=10)
        self.assertTrue(summary.budget_exhausted)
        self.assertEqual(summary.episodes_used, 10)
        interval = summary.intervals["oledRailV"]
        self.assertTrue(any("budget" in side["note"] for side in interval["sides"].values()))
        self.assertLessEqual(interval["low"], 3.27)
        self.assertGreaterEqual(interval["high"], 3.27)

    def test_open_ended_failure_stops_at_the_range_limit(self):
        trigger = {**TRIGGER, "oledRailV": 3.55}
        _, summary = drive(trigger, oracle=lambda c: c["redLed"] and not c["greenLed"] and c["workload"] == "oled_refresh"
                           and c["oledRailV"] >= 3.4)
        interval = summary.intervals["oledRailV"]
        self.assertEqual(interval["high"], 3.6)
        self.assertTrue(interval["sides"]["high"]["note"].startswith("open"))
        self.assertEqual(interval["low"], 3.4)

    def test_refused_candidates_cost_nothing_and_end_that_side(self):
        log, summary = drive(rejected=lambda c: c["oledRailV"] > 3.29)
        self.assertGreater(len([1 for _, o in log if o == REJECTED]), 0)
        self.assertEqual(summary.episodes_used, len([1 for _, o in log if o != REJECTED]))

    def test_the_session_is_a_pure_function_of_its_results(self):
        first, a = drive()
        second, b = drive()
        self.assertEqual([(r.conditions, r.role) for r, _ in first], [(r.conditions, r.role) for r, _ in second])
        self.assertEqual(a, b)


class PlanTests(unittest.TestCase):
    def test_defaults_and_overrides(self):
        plan = plan_config("default_v1", 50, 24)
        self.assertEqual((plan.confirm_max_replays, plan.confirm_if_fails, plan.transient_if_passes, plan.init_enabled,
                          plan.on_confirmed, plan.necessity_probes), (3, 2, 2, False, "stop", True))
        custom = plan_config({"init": {"enabled": True}, "confirm": {"maxReplays": 5, "confirmIfFails": 3},
                              "minimize": {"necessityProbes": False}, "onConfirmed": "continue",
                              "stop": {"consecutiveInvalid": 4}}, 50, 24)
        self.assertEqual((custom.init_enabled, custom.transient_if_passes, custom.necessity_probes, custom.on_confirmed,
                          custom.consecutive_invalid), (True, 3, False, "continue", 4))

    def test_coverage_phase_size(self):
        plan = plan_config({"init": {"enabled": True}}, 50, 24)
        self.assertEqual(plan.init_episodes(8), 10)          # 20% of 50
        self.assertEqual(plan.init_episodes(12), 12)         # the array is larger than 20%
        self.assertEqual(plan.init_episodes(40), 18)         # capped at 35% (17.5 rounds up)
        self.assertEqual(plan_config("x", 50, 24).init_episodes(8), 0)

    def test_invalid_plans_are_rejected(self):
        for bad in ({"explore": {"forcedEveryN": 5}}, {"onConfirmed": "maybe"}, {"confirm": {"maxReplays": 2, "confirmIfFails": 3}},
                    {"init": {"minFraction": 0.5, "maxFraction": 0.2}}, {"confirm": {"maxReplays": 0}}, [], {"stop": []}):
            with self.assertRaises(InvalidRequest, msg=repr(bad)):
                plan_config(bad, 50, 24)


if __name__ == "__main__":
    unittest.main()
