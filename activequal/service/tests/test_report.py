"""Report content tests: a fault campaign, a clean campaign, hand-built edge campaigns and a planner-comparison batch."""

import hashlib
import json
import re
import time
import unittest

from activequal.agent.service.tests.support import Rig
from activequal.service import report as rep
from activequal.service import stats
from activequal.service.tests.support import World

FORBIDDEN_PHRASES = ("certified", "certification", "guarantee", "conclusively correct", "is safe", "98%",
                     "untested region")
FAIL_CONDITIONS = {"oledRailV": 3.25, "sensorRailV": 3.30, "redLed": True, "greenLed": False,
                   "workload": "oled_refresh", "flashOffsetMs": 0, "dwellMs": 500}


def fault_rig(seed: int | None = None, profile: str = "B1w", planner: str = "tpe", noise_seed: int = 3,
              discovery: int = 30, verification: int = 12) -> Rig:
    rig = Rig(profile, discovery=discovery, verification=verification, planner=planner, noise_seed=noise_seed)
    if seed is not None:
        with rig.world.db.transaction() as conn:
            conn.execute("UPDATE campaigns SET seed = ? WHERE id = ?", (seed, rig.world.campaign_id))
    rig.run()
    return rig


def clean_rig() -> Rig:
    rig = Rig("B3", discovery=8, verification=4, planner="random")
    rig.run()
    return rig


def safety_rig() -> Rig:
    """The instrument drops out after the outputs were enabled: the Controller cuts off and the campaign locks out."""
    from activequal.adapter.service.simulator import FaultInjection, FaultKind
    rig = Rig("B3", discovery=6, verification=2, planner="random",
              fault=FaultInjection(FaultKind.INSTRUMENT_DISCONNECT_AFTER_OUTPUT))
    rig.run()
    return rig


def trace_world() -> tuple[World, dict]:
    """A hand-built finished campaign: a pass carrying a raw trace, a failure with a recorded counterexample,
    and an inconclusive episode. Returns the world and the ids."""
    world = World(discovery=4, verification=3)
    backend = world.backend
    data = b"time_ms,volts\n0,3.30\n1,3.29\n"
    digest = hashlib.sha256(data).hexdigest()
    backend.put_trace(digest, data, "text/csv", "bench-A")
    ids = {"trace": digest}
    first = {**FAIL_CONDITIONS, "oledRailV": 3.30}
    ids["pass"] = world.run_episode(0, first, traces=[{"sha256": digest}])["episodeId"]
    ids["fail"] = world.run_episode(1, FAIL_CONDITIONS, measured={"oledLatencyMs": 151.0})["episodeId"]
    ids["inconclusive"] = world.run_episode(2, {**FAIL_CONDITIONS, "oledRailV": 3.20},
                                            measured={"oledLatencyMs": 122.0})["episodeId"]
    world.submit(3, {**FAIL_CONDITIONS, "redLed": False}, role="confirm", linked_episode_id=ids["fail"],
                 repeat_reason="replay")
    claim = world.claim()
    world.walk(claim, "PREFLIGHT", "CONFIGURING", "SETTLING", "EXECUTING", "OBSERVING", "SHUTTING_DOWN")
    ids["replay"] = backend.submit_result(world.payload(claim), "bench-A")["episodeId"]
    backend.record_counterexample(world.campaign_id, ids["fail"],
                                  {"conditions": FAIL_CONDITIONS, "removed": ["dwellMs"], "kept": ["redLed"],
                                   "necessity": {"greenLed": "necessary"}},
                                  {"intervals": {"oledRailV": {"low": 3.2, "high": 3.3, "step": 0.01, "sides": {
                                      "low": {"lastFail": 3.2, "firstPass": 3.19, "resolution": 0.01, "note": "resolved"},
                                      "high": {"lastFail": 3.3, "firstPass": None, "resolution": None,
                                               "note": "unresolved: verification budget used up"}}}},
                                   "budgetExhausted": True},
                                  9, 10, origin="seeded")
    backend.complete_campaign(world.campaign_id, "test campaign finished")
    return world, ids


class FaultCampaign(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rig = fault_rig()
        cls.cid = cls.rig.world.campaign_id
        cls.report = rep.build_report(cls.rig.backend, cls.cid)
        cls.markdown = rep.render_markdown(cls.report)

    @classmethod
    def tearDownClass(cls):
        cls.rig.close()

    def test_headline_and_kind(self):
        self.assertEqual(self.report["result"]["kind"], rep.KIND_COUNTEREXAMPLE)
        self.assertTrue(self.report["result"]["headline"].startswith("Counterexample found: requirement latency failed"))
        self.assertFalse(self.report["partial"])
        self.assertNotIn(rep.NO_FAILURE_SENTENCE, self.markdown)

    def test_json_serializable_and_canonical(self):
        text = rep.to_json(self.report)
        self.assertEqual(json.loads(text), self.report)
        self.assertEqual(rep.to_json(json.loads(text)), text)       # sorted keys: re-serializing is a fixed point
        self.assertEqual(rep.to_json(rep.build_report(self.rig.backend, self.cid)), text)   # deterministic

    def test_identity(self):
        ident = self.report["identity"]
        view = self.rig.backend.get_campaign(self.cid)
        self.assertEqual(ident["contractHash"], view["contractHash"])
        self.assertEqual(ident["planner"]["method"], "tpe")
        self.assertEqual(ident["planner"]["seed"], 42)
        self.assertEqual(ident["planner"]["plan"], view["plan"])
        self.assertEqual(ident["softwareVersion"], "git:test")
        self.assertEqual(ident["fixtureId"], "bench-A")
        self.assertTrue(ident["calibrationId"])
        self.assertEqual(len(ident["dutFirmwareSha256"]), 64)
        self.assertEqual(len(ident["approvals"]), 2)
        for needle in (ident["contractHash"], ident["calibrationId"], "tpe", "seed 42", "git:test"):
            self.assertIn(needle, self.markdown)

    def test_budgets_and_outcomes_drop_nothing(self):
        backend, cid = self.rig.backend, self.cid
        view = backend.get_campaign(cid)
        b, o = self.report["budget"], self.report["outcomes"]
        self.assertEqual(b["discovery"]["used"], view["budget"]["discoveryUsed"])
        self.assertEqual(b["verification"]["used"], view["budget"]["verificationUsed"])
        self.assertEqual(b["discovery"]["allowed"], 30)
        self.assertEqual(o["total"], b["discovery"]["used"] + b["verification"]["used"])
        self.assertEqual(sum(o["counts"].values()), o["total"])
        self.assertEqual(o["counts"], dict(sorted(view["episodesByOutcome"].items())))
        self.assertEqual(sum(sum(c.values()) for c in o["byPool"].values()), o["total"])
        self.assertEqual(sum(o["byRole"].values()), o["total"])
        self.assertEqual(o["candidatesRejected"]["count"], view["candidatesRejected"])
        self.assertEqual(len(self.report["episodes"]), o["total"])
        for key in ("invalid", "inconclusive", "safetyAborts"):
            self.assertIn(key, o)

    def test_episodes_to_first_failure_is_discovery_only(self):
        history = [h for h in self.rig.backend.episode_history(self.cid) if h["role"] == "discovery"]
        cx = self.rig.backend.counterexamples(self.cid)[0]
        index = [h["episodeId"] for h in history].index(cx["originalEpisodeId"]) + 1
        m = self.report["metrics"]
        self.assertEqual(m["episodesToFirstConfirmedFailure"], index)
        self.assertIsNone(m["censoredAtBudget"])
        self.assertEqual(m["discoveryEpisodesUsed"], len(history))
        self.assertGreater(m["verificationEpisodesUsed"], 0)
        self.assertEqual(m["totalEpisodesUsed"], len(history) + m["verificationEpisodesUsed"])
        self.assertIn(f"Episodes to first confirmed failure (discovery pool only): {index}", self.markdown)
        self.assertIn("Total episodes used (all pools, reported separately)", self.markdown)

    def test_stop_reason_from_last_campaign_events(self):
        stop = self.report["stop"]
        self.assertEqual(stop["state"], "COMPLETED")
        completed = [e for e in self.rig.backend.list_events(self.cid) if e["newState"] == "COMPLETED"][-1]
        self.assertEqual((stop["reason"], stop["eventId"]), (completed["reason"], completed["id"]))
        self.assertIn(stop["reason"], self.markdown)

    def test_requirement_margins(self):
        by_id = {r["id"]: r for r in self.report["requirements"]}
        self.assertEqual(set(by_id), {"latency", "heartbeat", "reset", "dut_3v3_band"})
        latency = by_id["latency"]
        self.assertGreater(latency["fail"], 0)
        self.assertLess(latency["minMargin"], 0)
        self.assertEqual(latency["evaluated"], latency["pass"] + latency["fail"] + latency["inconclusive"])
        worst = self.rig.backend.get_episode(latency["minMarginEpisodeId"])
        self.assertEqual(worst["verdict"]["margins"]["latency"], latency["minMargin"])

    def test_counterexample_content_matches_stored_records(self):
        backend = self.rig.backend
        stored = backend.counterexamples(self.cid)
        self.assertEqual(len(self.report["counterexamples"]), len(stored))
        for cx, row in zip(self.report["counterexamples"], stored):
            self.assertEqual(cx["id"], row["id"])
            self.assertEqual(cx["originalEpisodeId"], row["originalEpisodeId"])
            self.assertEqual(cx["origin"], row["origin"])
            self.assertIn("unknown", cx["originLabel"])
            repro = cx["reproduction"]
            self.assertEqual((repro["numerator"], repro["denominator"]), (row["reproductions"], row["attempts"]))
            self.assertEqual(repro["wilson95"], list(stats.wilson_interval(row["reproductions"], row["attempts"])))
            self.assertEqual(cx["minimized"]["conditions"], row["minimized"]["conditions"])
            self.assertEqual(cx["minimized"]["removed"], row["minimized"]["removed"])
            self.assertEqual(cx["minimized"]["kept"], row["minimized"]["kept"])
            self.assertEqual(cx["minimized"]["necessity"], row["minimized"]["necessity"])
            self.assertEqual(set(cx["intervals"]), set(row["intervals"]["intervals"]))
            for name, interval in cx["intervals"].items():
                for side, detail in interval["sides"].items():
                    self.assertEqual(detail["note"], row["intervals"]["intervals"][name]["sides"][side]["note"])
                    self.assertIn("resolution", detail)
            original = backend.get_episode(row["originalEpisodeId"])
            self.assertEqual(cx["original"]["requested"], original["requested"])
            self.assertEqual({k: v["value"] for k, v in cx["original"]["measured"].items()},
                             {k: v["value"] for k, v in original["measured"].items()})
            self.assertEqual(cx["violated"][0]["requirement"], "latency")
            log = backend.session_log(self.cid, row["originalEpisodeId"])
            self.assertEqual(cx["episodeIds"], [row["originalEpisodeId"], *[e["episodeId"] for e in log if e["episodeId"]]])

    def test_markdown_cites_every_counterexample_episode(self):
        for cx in self.report["counterexamples"]:
            self.assertIn(cx["id"], self.markdown)
            self.assertIn(cx["originalEpisodeId"], self.markdown)
            for episode_id in cx["episodeIds"]:
                self.assertIn(episode_id, self.markdown)
            self.assertIn(f"{cx['reproduction']['numerator']}/{cx['reproduction']['denominator']}", self.markdown)
        for episode in self.report["episodes"]:
            self.assertIn(episode["episodeId"], self.markdown)

    def test_every_claim_links_to_episode_ids(self):
        known = {e["episodeId"] for e in self.report["episodes"]}
        self.assertTrue(self.report["claims"])
        for claim in self.report["claims"]:
            self.assertTrue(claim["episodeIds"] or claim.get("eventIds") or claim.get("candidateIds"), claim)
            self.assertTrue(set(claim["episodeIds"]) <= known, claim)
        self.assertIn(f"event: {self.report['stop']['eventId']}", self.markdown)
        for statement in self.report["result"]["statements"]:
            self.assertTrue(set(statement["episodeIds"]) <= known)

    def test_honest_language(self):
        lowered = self.markdown.lower()
        for phrase in FORBIDDEN_PHRASES:
            self.assertNotIn(phrase, lowered)
        self.assertIn("applies only to the conditions that were tested", self.markdown)
        self.assertIn("Requested conditions", self.markdown)
        self.assertIn("Measured values", self.markdown)

    def test_markdown_sections_present(self):
        for heading in ("## Result", "## Campaign identity", "## Budget and use", "## Outcomes", "## Stop reason",
                        "## Requirement margins", "## Counterexamples", "## Claims and the episodes behind them",
                        "## Episode index", "## Limitations"):
            self.assertIn(heading, self.markdown)


class CleanCampaign(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rig = clean_rig()
        cls.cid = cls.rig.world.campaign_id
        cls.report = rep.build_report(cls.rig.backend, cls.cid)
        cls.markdown = rep.render_markdown(cls.report)

    @classmethod
    def tearDownClass(cls):
        cls.rig.close()

    def test_exact_no_failure_sentence(self):
        self.assertEqual(rep.NO_FAILURE_SENTENCE, "No failure found within the tested conditions and budget.")
        self.assertEqual(self.report["result"]["kind"], rep.KIND_NO_COUNTEREXAMPLE)
        self.assertIn("No counterexample found within budget:", self.markdown)
        self.assertIn(rep.NO_FAILURE_SENTENCE, self.markdown)
        self.assertIn(rep.NO_FAILURE_SENTENCE, self.report["result"]["headline"])

    def test_no_counterexamples_and_censored(self):
        self.assertEqual(self.report["counterexamples"], [])
        m = self.report["metrics"]
        self.assertIsNone(m["episodesToFirstConfirmedFailure"])
        self.assertEqual(m["censoredAtBudget"], 8)
        self.assertEqual(m["verificationEpisodesUsed"], 0)
        self.assertEqual(self.report["outcomes"]["counts"].get("DUT_FAILURE", 0), 0)
        self.assertIn("None confirmed.", self.markdown)

    def test_honest_language(self):
        lowered = self.markdown.lower()
        for phrase in FORBIDDEN_PHRASES:
            self.assertNotIn(phrase, lowered)
        self.assertIn("applies only to the conditions that were tested", self.markdown)

    def test_stop_reason(self):
        self.assertIn("discovery budget of 8 episodes used", self.report["stop"]["reason"])


class SafetyAbortCampaign(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rig = safety_rig()
        cls.cid = cls.rig.world.campaign_id
        cls.report = rep.build_report(cls.rig.backend, cls.cid)
        cls.markdown = rep.render_markdown(cls.report)

    @classmethod
    def tearDownClass(cls):
        cls.rig.close()

    def test_safety_abort_is_reported_and_locks_out(self):
        r = self.report
        self.assertEqual(r["state"], "LOCKED_OUT")
        self.assertFalse(r["partial"])
        self.assertEqual(r["stop"]["state"], "LOCKED_OUT")
        self.assertGreaterEqual(r["outcomes"]["safetyAborts"], 1)
        self.assertEqual(r["result"]["kind"], rep.KIND_SAFETY_ABORT)
        self.assertTrue(r["result"]["headline"].startswith("Safety abort:"))
        self.assertNotIn(rep.NO_FAILURE_SENTENCE, self.markdown)
        self.assertNotIn("IN_FLIGHT", r["outcomes"]["counts"])      # the tripped episode is finalized, not left in flight
        self.assertTrue(r["lockouts"])
        self.assertIn("Lockout at", self.markdown)
        aborted = r["outcomes"]["episodeIds"]["SAFETY_ABORT"]
        for episode_id in aborted:
            self.assertIn(episode_id, self.markdown)
        self.assertEqual(r["metrics"]["episodesToFirstConfirmedFailure"], None)

    def test_early_stop_is_censored_at_the_episodes_actually_run(self):
        record = rep.campaign_record(self.report, "B3")
        used = self.report["budget"]["discovery"]["used"]
        self.assertLess(used, 6)
        self.assertEqual(record["budget"], used)
        self.assertTrue(record["stopped_early"])
        self.assertEqual(record["state"], "LOCKED_OUT")


class HandBuiltCampaign(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world, cls.ids = trace_world()
        cls.report = rep.build_report(cls.world.backend, cls.world.campaign_id)
        cls.markdown = rep.render_markdown(cls.report)

    @classmethod
    def tearDownClass(cls):
        cls.world.close()

    def test_seeded_label_and_reproduction_numbers(self):
        cx = self.report["counterexamples"][0]
        self.assertEqual(cx["origin"], "seeded")
        self.assertIn("seeded", cx["originLabel"])
        self.assertEqual((cx["reproduction"]["numerator"], cx["reproduction"]["denominator"]), (9, 10))
        self.assertEqual(cx["reproduction"]["wilson95"], list(stats.wilson_interval(9, 10)))
        self.assertTrue(cx["reproduction"]["meetsTenReplays"])
        self.assertIn("9/10", self.markdown)
        self.assertIn("origin seeded", self.markdown.replace("(the fault was injected on purpose)", "").replace("  ", " "))
        self.assertIn("none found", self.markdown)                  # the unresolved high side of the interval
        self.assertIn("unresolved: verification budget used up", self.markdown)
        self.assertEqual(cx["nearbyPassing"][0]["episodeId"], self.ids["replay"])

    def test_inconclusive_is_counted_not_dropped(self):
        o = self.report["outcomes"]
        self.assertEqual((o["invalid"], o["inconclusive"]), (1, 1))
        self.assertEqual(o["episodeIds"]["INVALID_EXPERIMENT"], [self.ids["inconclusive"]])
        self.assertEqual(o["counts"]["PASS"], 2)
        self.assertEqual(o["counts"]["DUT_FAILURE"], 1)
        self.assertEqual(self.report["metrics"]["episodesToFirstConfirmedFailure"], 2)
        self.assertEqual(self.report["metrics"]["verificationEpisodesUsed"], 1)
        self.assertEqual(self.report["metrics"]["totalEpisodesUsed"], 4)

    def test_requested_and_measured_are_separate_with_uncertainty(self):
        episode = self.report["counterexamples"][0]["original"]
        self.assertEqual(episode["requested"]["oledRailV"], 3.25)
        self.assertAlmostEqual(episode["measured"]["measuredOledRailV"]["value"], 3.248)
        self.assertIsNotNone(episode["measured"]["oledLatencyMs"]["uncertainty"])
        self.assertIn("+/- 5", self.markdown)

    def test_unconfirmed_failure_never_uses_the_no_failure_sentence(self):
        world = World(discovery=2, verification=0)
        try:
            world.run_episode(0, FAIL_CONDITIONS, measured={"oledLatencyMs": 151.0})
            world.backend.complete_campaign(world.campaign_id, "done")
            report = rep.build_report(world.backend, world.campaign_id)
            markdown = rep.render_markdown(report)
            self.assertEqual(report["result"]["kind"], rep.KIND_UNCONFIRMED)
            self.assertNotIn(rep.NO_FAILURE_SENTENCE, markdown)
            self.assertIn("Failure observed but not confirmed", markdown)
            self.assertEqual(report["metrics"]["firstObservedFailureIndex"], 1)
            self.assertIsNone(report["metrics"]["episodesToFirstConfirmedFailure"])
        finally:
            world.close()

    def test_all_inconclusive_campaign(self):
        world = World(discovery=3, verification=0)
        try:
            for i in range(3):
                world.run_episode(i, {**FAIL_CONDITIONS, "dwellMs": 500 + 100 * i}, measured={"oledLatencyMs": 122.0})
            world.backend.complete_campaign(world.campaign_id, "done")
            report = rep.build_report(world.backend, world.campaign_id)
            self.assertEqual(report["result"]["kind"], rep.KIND_INCONCLUSIVE)
            self.assertIn("Campaign inconclusive: 3/3 episodes invalid", report["result"]["headline"])
            self.assertNotIn(rep.NO_FAILURE_SENTENCE, rep.render_markdown(report))
        finally:
            world.close()

    def test_partial_report_for_unfinished_campaign(self):
        world = World(discovery=2, verification=0)
        try:
            world.run_episode(0, FAIL_CONDITIONS, measured={"oledLatencyMs": 100.0})
            report = rep.build_report(world.backend, world.campaign_id)
            self.assertTrue(report["partial"])
            self.assertIsNone(report["stop"])
            self.assertIn("PARTIAL REPORT", rep.render_markdown(report))
        finally:
            world.close()


class PlannerBatch(unittest.TestCase):
    def test_twelve_full_stack_campaigns_feed_compare_planners(self):
        started = time.monotonic()
        records, reports = [], []
        for i in range(6):
            for planner in ("random", "tpe"):
                rig = fault_rig(seed=100 + i, planner=planner, noise_seed=10 + i, discovery=15, verification=4)
                try:
                    report = rep.build_report(rig.backend, rig.world.campaign_id)
                    reports.append(report)
                    records.append(rep.campaign_record(report, "B1w"))
                finally:
                    rig.close()
        self.assertEqual(len(records), 12)
        for record, report in zip(records, reports):
            self.assertEqual(record["budget"], 15 if record["episodes_to_failure"] is not None
                             else max(1, min(15, report["budget"]["discovery"]["used"])))
            self.assertEqual(record["episodes_to_failure"], report["metrics"]["episodesToFirstConfirmedFailure"])
            if record["episodes_to_failure"] is not None:
                self.assertLessEqual(record["episodes_to_failure"], 15)
            self.assertLessEqual(report["budget"]["discovery"]["used"], 15)
        print("episodes_to_failure by campaign:", [(r["planner"], r["episodes_to_failure"]) for r in records])
        self.assertTrue(any(r["episodes_to_failure"] is not None for r in records), "no campaign confirmed a failure")
        out = stats.compare_planners(records, checkpoints=(10, 15))
        groups = out["profiles"]["B1w"]["planners"]
        self.assertEqual({g: groups[g]["campaigns"] for g in groups}, {"random": 6, "tpe": 6})
        for planner, group in groups.items():
            found = sum(1 for r in records if r["planner"] == planner and r["episodes_to_failure"] is not None)
            self.assertEqual(group["kaplanMeier"]["events"], found)
            self.assertEqual(group["discoveryRates"]["15"]["numerator"], found)
            self.assertEqual(group["discoveryRates"]["15"]["denominator"], 6)
        test = out["profiles"]["B1w"]["logRank"][0]
        self.assertEqual((test["a"], test["b"]), ("random", "tpe"))
        self.assertTrue(0.0 <= test["p"] <= 1.0)
        json.dumps(out)
        self.assertLess(time.monotonic() - started, 30)


if __name__ == "__main__":
    unittest.main()
