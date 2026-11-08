import re
import unittest

from activequal.adapter.service.simulator import FaultInjection, FaultKind
from activequal.agent.service.agent import Agent, AgentError
from activequal.agent.service.tests.support import Rig
from activequal.decision.service.decision import propose
from activequal.model.examples import oled_example_contract
from activequal.service.tests.support import SAM


class AgentCampaignTests(unittest.TestCase):
    def setUp(self):
        self.rigs = []

    def tearDown(self):
        for rig in self.rigs:
            rig.close()

    def rig(self, *a, **kw):
        rig = Rig(*a, **kw)
        self.rigs.append(rig)
        return rig

    def test_fault_campaign_finds_confirms_minimizes_and_brackets(self):
        rig = self.rig("B1w", discovery=50, verification=24)
        steps = rig.run()
        view = rig.backend.get_campaign(rig.world.campaign_id)
        self.assertEqual(view["state"], "COMPLETED")
        self.assertEqual(steps[-1].kind, "completed")
        self.assertIn("confirmed and minimized", steps[-1].detail)
        (cx,) = rig.backend.counterexamples(rig.world.campaign_id)
        self.assertEqual((cx["reproductions"], cx["attempts"]), (2, 2))
        conditions = cx["minimized"]["conditions"]
        self.assertTrue(conditions["redLed"] and not conditions["greenLed"] and conditions["workload"] == "oled_refresh")
        self.assertEqual(cx["minimized"]["necessity"].get("greenLed"), "necessary")
        self.assertNotIn("oledRailV", cx["minimized"]["kept"])   # its nominal-value replay was inconclusive, not a pass
        voltage = cx["intervals"]["intervals"]["oledRailV"]
        self.assertTrue(voltage["low"] <= 3.25 <= voltage["high"])
        self.assertTrue(3.17 <= voltage["low"] <= 3.23 and 3.27 <= voltage["high"] <= 3.33, voltage)   # seeded 3.20..3.30
        self.assertLessEqual(view["budget"]["verificationUsed"], 24)
        self.assertLessEqual(view["budget"]["discoveryUsed"], 50)

    def test_roles_are_separated_in_the_records(self):
        rig = self.rig("B1w")
        rig.run()
        history = rig.backend.episode_history(rig.world.campaign_id)
        roles = {h["role"] for h in history}
        self.assertTrue({"discovery", "confirm", "minimize", "necessity_probe", "bracket"} <= roles)
        trigger = next(h for h in history if h["role"] == "discovery" and h["outcome"] == "DUT_FAILURE")
        self.assertTrue(all(h["linkedEpisodeId"] == trigger["episodeId"] for h in history if h["role"] != "discovery"))
        self.assertEqual([h["role"] for h in history if h["role"] == "discovery"][-1], "discovery")

    def test_clean_device_uses_the_whole_discovery_budget_and_reports_no_failure(self):
        rig = self.rig("B3", discovery=20, verification=24)
        rig.run()
        view = rig.backend.get_campaign(rig.world.campaign_id)
        self.assertEqual(view["state"], "COMPLETED")
        self.assertEqual(view["budget"]["discoveryUsed"], 20)
        self.assertEqual(view["budget"]["verificationUsed"], 0)
        self.assertEqual(rig.backend.counterexamples(rig.world.campaign_id), [])
        self.assertIn("0 confirmed", rig.steps[-1].detail)
        self.assertNotIn("DUT_FAILURE", view["episodesByOutcome"])

    def test_no_point_is_ever_executed_twice_in_discovery(self):
        rig = self.rig("B3", discovery=30)
        rig.run()
        seen = [tuple(sorted(h["conditions"].items())) for h in rig.backend.episode_history(rig.world.campaign_id)]
        self.assertEqual(len(seen), len(set(seen)))

    def test_every_planner_runs_through_the_full_stack(self):
        for planner in ("random", "fixed_corner", "coverage", "tpe"):      # grid needs a small space
            with self.subTest(planner=planner):
                rig = self.rig("B3", discovery=6, planner=planner)
                rig.run()
                self.assertEqual(rig.backend.get_campaign(rig.world.campaign_id)["budget"]["discoveryUsed"], 6)

    def test_restarting_the_agent_between_every_step_changes_nothing(self):
        steady = self.rig("B1w", discovery=50, noise_seed=11)
        steady.run()
        restarted = self.rig("B1w", discovery=50, noise_seed=11)
        for _ in range(400):
            restarted.agent = Agent(restarted.backend, restarted.world.campaign_id, propose)     # fresh process each step
            result = restarted.agent.step()
            if result.kind in ("completed", "idle"):
                break
            restarted.controller.run_once()

        def trace(rig):
            return [(h["role"], h["outcome"], sorted(h["conditions"].items())) for h in
                    rig.backend.episode_history(rig.world.campaign_id)]
        self.assertEqual(trace(steady), trace(restarted))
        self.assertEqual(restarted.backend.counterexamples(restarted.world.campaign_id)[0]["intervals"],
                         steady.backend.counterexamples(steady.world.campaign_id)[0]["intervals"])

    def test_same_seed_gives_the_same_campaign(self):
        a, b = self.rig("B1w", noise_seed=5), self.rig("B1w", noise_seed=5)
        a.run()
        b.run()
        key = lambda r: [(h["role"], h["outcome"], sorted(h["conditions"].items())) for h in r.backend.episode_history(r.world.campaign_id)]
        self.assertEqual(key(a), key(b))

    def test_waits_while_an_episode_is_running_and_idles_when_not_running(self):
        rig = self.rig("B3", discovery=3)
        first = rig.agent.step()
        self.assertEqual(first.kind, "submitted")
        self.assertEqual(rig.agent.step().kind, "waiting")
        rig.controller.run_once()
        rig.backend.pause_campaign(rig.world.campaign_id, rig.backend.get_campaign(rig.world.campaign_id)["version"],
                                   SAM)
        self.assertEqual(rig.agent.step().kind, "idle")

    def test_continue_mode_keeps_hunting_outside_the_confirmed_region(self):
        rig = self.rig("B1w", discovery=30, verification=24, plan={"onConfirmed": "continue"})
        rig.run()
        view = rig.backend.get_campaign(rig.world.campaign_id)
        self.assertEqual(view["state"], "COMPLETED")
        self.assertEqual(view["budget"]["discoveryUsed"], 30)
        cxs = rig.backend.counterexamples(rig.world.campaign_id)
        self.assertGreaterEqual(len(cxs), 1)          # continue mode may confirm further, distinct regions
        cx = cxs[0]
        voltage = cx["intervals"]["intervals"]["oledRailV"]
        history = rig.backend.episode_history(rig.world.campaign_id)
        ids = [h["episodeId"] for h in history]
        trigger_index = ids.index(cx["originalEpisodeId"])
        end = ids.index(cxs[1]["originalEpisodeId"]) if len(cxs) > 1 else len(history)
        after = [h for h in history[trigger_index + 1:end] if h["role"] == "discovery"]
        self.assertTrue(after)
        for h in after:
            c = h["conditions"]
            inside = (c["redLed"] and not c["greenLed"] and c["workload"] == "oled_refresh"
                      and voltage["low"] <= c["oledRailV"] <= voltage["high"])
            self.assertFalse(inside, c)

    def test_coverage_phase_runs_first_when_enabled(self):
        rig = self.rig("B3", discovery=20, plan={"init": {"enabled": True}})
        rig.run()
        rows = rig.world.db.query("SELECT planner_reason, reason_code FROM candidates ORDER BY planner_sequence")
        init = [r for r in rows if r["planner_reason"].startswith("Coverage baseline")]
        self.assertEqual(len(init), 7)        # the larger of the pairwise array and 20%, capped at 35% of 20
        self.assertTrue(all(r["planner_reason"].startswith("Coverage baseline") for r in rows[:len(init)]))
        self.assertTrue(all(r["reason_code"] == "BASELINE" for r in init))

    def test_instrument_failures_stop_the_campaign_instead_of_burning_the_budget(self):
        rig = self.rig("B3", discovery=20, fault=FaultInjection(FaultKind.MISSING_OLED_OBSERVATION))
        rig.run()
        view = rig.backend.get_campaign(rig.world.campaign_id)
        self.assertEqual(view["budget"]["discoveryUsed"], 3)
        self.assertIn("invalid", rig.steps[-1].detail)

    def test_repeated_rejections_end_the_campaign_with_a_planner_failure(self):
        contract = oled_example_contract()
        contract["safety"]["maxEpisodeS"] = 4          # the rails cannot ramp that fast: every candidate is unsafe
        rig = self.rig("B3", discovery=20, contract=contract)
        rig.run()
        view = rig.backend.get_campaign(rig.world.campaign_id)
        self.assertEqual((view["state"], view["budget"]["discoveryUsed"], view["candidatesRejected"]), ("COMPLETED", 0, 5))
        self.assertIn("planner failure", rig.steps[-1].detail)

    def test_manual_planner_runs_operator_candidates_then_stops(self):
        base = {"sensorRailV": 3.30, "redLed": True, "greenLed": False, "workload": "oled_refresh", "flashOffsetMs": 0,
                "dwellMs": 500}
        candidates = [{**base, "oledRailV": 3.25}, {**base, "oledRailV": 3.45}]
        rig = self.rig("B1w", discovery=5, planner="manual", planner_config={"candidates": candidates})
        rig.run()
        history = rig.backend.episode_history(rig.world.campaign_id)
        self.assertEqual([h["conditions"]["oledRailV"] for h in history if h["role"] == "discovery"], [3.25, 3.45][:1])
        self.assertIn("first failure", rig.steps[-1].detail)

    def test_manual_planner_without_candidates_is_an_error_not_a_silent_stop(self):
        rig = self.rig("B3", discovery=3, planner="manual")
        with self.assertRaises(AgentError):
            rig.agent.step()

    def test_decision_never_receives_anything_but_the_contract_and_measured_history(self):
        seen = []

        def spy(request):
            seen.append(request)
            return propose(request)
        rig = self.rig("B1w", discovery=15)
        rig.agent = Agent(rig.backend, rig.world.campaign_id, spy)
        rig.run()
        banned = (r"\bfault", "island", "groundTruth", "profile", "B1w", "hidden", "precursor", "seeded")
        for request in seen:
            self.assertEqual(set(request) - {"contract", "method", "seed", "count", "history", "warmupTrials", "candidates"}, set())
            text = repr(request)
            for pattern in banned:
                self.assertIsNone(re.search(pattern, text), pattern)


if __name__ == "__main__":
    unittest.main()
