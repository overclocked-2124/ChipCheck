import copy
import hashlib
import sqlite3
import unittest
from datetime import timedelta

from activequal.model.examples import oled_example_contract
from activequal.service.backend import researcher, reviewer
from activequal.service.errors import BackendError
from activequal.service.ids import isoformat
from activequal.service.tests.support import ALEX, CANDIDATE, DANA, GOOD_HEALTH, SAM, World


class Case(unittest.TestCase):
    def tearDown(self):
        getattr(self, "world", None) and self.world.close()

    def make(self, **kw):
        self.world = World(**kw)
        return self.world

    def code(self, call, *args, **kw):
        with self.assertRaises(BackendError) as caught:
            call(*args, **kw)
        return caught.exception.code


class ContractTests(Case):
    def test_two_approvals_needed_for_a_first_version(self):
        w = self.make(arm=False)
        info = w.backend.get_contract(w.contract_key, 1)
        self.assertEqual((info["approvalsRequired"], info["approved"]), (2, True))

    def test_approval_needs_reviewer_and_is_idempotent(self):
        w = self.make(arm=False)
        self.assertEqual(self.code(w.backend.approve_contract, w.contract_key, 1, SAM), "PERMISSION_DENIED")
        again = w.backend.approve_contract(w.contract_key, 1, DANA)
        self.assertEqual(again["approvedBy"].count("dana"), 1)

    def test_one_reviewer_is_not_enough_and_campaign_cannot_validate(self):
        w = self.make(arm=False)
        contract = oled_example_contract()
        contract["setup"]["dut"] = "other-dut"
        created = w.backend.create_contract(contract, SAM)
        w.backend.approve_contract(created["contractId"], 1, DANA)
        self.assertFalse(w.backend.get_contract(created["contractId"], 1)["approved"])
        campaign = w.backend.create_campaign(created["contractId"], 1, "bench-A", "tpe", 1, 3, 2, SAM)
        view = w.backend.validate_campaign(campaign["id"], campaign["version"], SAM)
        self.assertEqual(view["state"], "DRAFT")
        self.assertIn("CONTRACT_NOT_APPROVED", [r["code"] for r in view["reasons"]])

    def test_same_content_returns_the_same_version(self):
        w = self.make(arm=False)
        again = w.backend.create_contract(oled_example_contract(), SAM)
        self.assertEqual((again["contractId"], again["version"]), (w.contract_key, 1))

    def test_limit_change_needs_two_approvals_other_change_one(self):
        w = self.make(arm=False)
        loosened = oled_example_contract()
        loosened["safety"]["channels"]["supply.ch2"]["maxA"] = 0.3
        v2 = w.backend.create_contract(loosened, SAM, w.contract_key)
        self.assertEqual((v2["version"], v2["approvalsRequired"]), (2, 2))
        renamed = copy.deepcopy(loosened)
        renamed["requirements"][0]["limit"] = 119
        v3 = w.backend.create_contract(renamed, SAM, w.contract_key)
        self.assertEqual((v3["version"], v3["approvalsRequired"]), (3, 1))

    def test_invalid_contract_is_rejected(self):
        w = self.make(arm=False)
        bad = oled_example_contract()
        del bad["safety"]
        self.assertEqual(self.code(w.backend.create_contract, bad, SAM), "INVALID_ARGUMENT")
        self.assertEqual(self.code(w.backend.create_contract, oled_example_contract(), SAM, "missing"), "NOT_FOUND")


class FixtureTests(Case):
    def test_token_authenticates_only_its_fixture(self):
        w = self.make(arm=False)
        self.assertEqual(w.backend.authenticate_bench(w.token), "bench-A")
        other = w.backend.register_fixture("bench-B", "A", ["dut"], DANA)
        self.assertEqual(w.backend.authenticate_bench(other["token"]), "bench-B")
        self.assertEqual(self.code(w.backend.authenticate_bench, "nope"), "UNAUTHENTICATED")
        self.assertEqual(self.code(w.backend.authenticate_bench, ""), "UNAUTHENTICATED")
        stored = w.db.one("SELECT token_sha256 FROM fixtures WHERE id = 'bench-A'")["token_sha256"]
        self.assertEqual(stored, hashlib.sha256(w.token.encode()).hexdigest())     # never stored in clear

    def test_rotation_invalidates_the_old_token(self):
        w = self.make(arm=False)
        new = w.backend.rotate_bench_token("bench-A", DANA)["token"]
        self.assertEqual(self.code(w.backend.authenticate_bench, w.token), "UNAUTHENTICATED")
        self.assertEqual(w.backend.authenticate_bench(new), "bench-A")

    def test_only_reviewers_register_and_duplicates_fail(self):
        w = self.make(arm=False)
        self.assertEqual(self.code(w.backend.register_fixture, "x", "A", ["dut"], SAM), "PERMISSION_DENIED")
        self.assertEqual(self.code(w.backend.register_fixture, "bench-A", "A", ["dut"], DANA), "FAILED_PRECONDITION")

    def test_calibration_validation(self):
        w = self.make(arm=False)
        good = {"supply.ch2": {"gain": 1, "offset": 0, "uncertainty": 0.01}}
        later = w.clock.now() + timedelta(days=1)
        self.assertEqual(self.code(w.backend.record_calibration, "bench-A", {}, "m", "o", later, SAM), "INVALID_ARGUMENT")
        self.assertEqual(self.code(w.backend.record_calibration, "bench-A", {"c": {"gain": 1}}, "m", "o", later, SAM),
                         "INVALID_ARGUMENT")
        self.assertEqual(self.code(w.backend.record_calibration, "bench-A", good, "m", "o",
                                   w.clock.now() - timedelta(days=1), SAM), "INVALID_ARGUMENT")


class LifecycleTests(Case):
    def test_happy_path_states_and_versions(self):
        w = self.make()
        self.assertEqual(w.view()["state"], "RUNNING")

    def test_stale_version_is_rejected(self):
        w = self.make(arm=False)
        self.assertEqual(self.code(w.backend.validate_campaign, w.campaign_id, w.version + 5, SAM), "STALE_VERSION")

    def test_illegal_actions_are_preconditions(self):
        w = self.make(arm=False)
        self.assertEqual(self.code(w.backend.arm_campaign, w.campaign_id, w.version, SAM), "FAILED_PRECONDITION")
        self.assertEqual(self.code(w.backend.start_campaign, w.campaign_id, w.version, SAM), "FAILED_PRECONDITION")
        self.assertEqual(self.code(w.backend.resume_campaign, w.campaign_id, w.version, SAM), "FAILED_PRECONDITION")

    def test_arming_checks_the_bench(self):
        w = self.make(arm=False)
        view = w.backend.validate_campaign(w.campaign_id, w.version, SAM)
        for patch, expected in (({"estopReleased": False}, "ESTOP_PRESSED"), ({"interlockHealthy": False}, "INTERLOCK_UNHEALTHY"),
                                ({"watchdogHealthy": False}, "WATCHDOG_UNHEALTHY"), ({"outputsInShutdown": False}, "OUTPUTS_ENERGIZED"),
                                ({"tripActive": True}, "TRIP_ACTIVE"), ({"dutFirmwareSha256": "f" * 64}, "DUT_FIRMWARE_MISMATCH"),
                                ({"mcuFirmwareSha256": "x"}, "MCU_FIRMWARE_MISMATCH")):
            w.backend.record_bench_health("bench-A", {**GOOD_HEALTH, **patch})
            with self.assertRaises(BackendError) as caught:
                w.backend.arm_campaign(w.campaign_id, view["version"], SAM)
            codes = [r["code"] for r in caught.exception.details["reasons"]]
            self.assertIn(expected, codes, patch)
        w.backend.record_bench_health("bench-A", dict(GOOD_HEALTH))
        self.assertEqual(w.backend.arm_campaign(w.campaign_id, view["version"], SAM)["state"], "ARMED")

    def test_arming_needs_a_current_calibration_and_fresh_health(self):
        w = self.make(arm=False)
        view = w.backend.validate_campaign(w.campaign_id, w.version, SAM)
        w.clock.advance(11)
        with self.assertRaises(BackendError) as caught:
            w.backend.arm_campaign(w.campaign_id, view["version"], SAM)
        self.assertIn("BENCH_HEALTH_STALE", [r["code"] for r in caught.exception.details["reasons"]])
        w.backend.record_bench_health("bench-A", dict(GOOD_HEALTH))
        w.clock.advance(31 * 86400)
        w.backend.record_bench_health("bench-A", dict(GOOD_HEALTH))
        with self.assertRaises(BackendError) as caught:
            w.backend.arm_campaign(w.campaign_id, view["version"], SAM)
        self.assertIn("CALIBRATION_EXPIRED", [r["code"] for r in caught.exception.details["reasons"]])

    def test_start_rechecks_firmware_and_calibration_against_the_armed_tuple(self):
        w = self.make(start=False)
        w.backend.record_bench_health("bench-A", {**GOOD_HEALTH, "mcuFirmwareSha256": "m" * 64})
        w.backend.record_calibration("bench-A", {"c": {"gain": 1, "offset": 0, "uncertainty": 0.01}}, "meter", "sam",
                                     w.clock.now() + timedelta(days=5), SAM)
        with self.assertRaises(BackendError) as caught:
            w.start()
        self.assertIn("CALIBRATION_CHANGED", [r["code"] for r in caught.exception.details["reasons"]])

    def test_validation_flags_capability_budget_and_planner_problems(self):
        w = self.make(arm=False)
        w.backend.register_fixture("bench-C", "A", ["dut"], DANA)
        campaign = w.backend.create_campaign(w.contract_key, 1, "bench-C", "nonsense", 1, 70, 70, SAM)
        view = w.backend.validate_campaign(campaign["id"], campaign["version"], SAM)
        codes = [r["code"] for r in view["reasons"]]
        for expected in ("FIXTURE_ID_MISMATCH", "CAPABILITY_MISSING", "BUDGET_EXCEEDS_CONTRACT", "PLANNER_UNKNOWN"):
            self.assertIn(expected, codes)
        self.assertEqual(view["state"], "DRAFT")

    def test_one_active_campaign_per_fixture(self):
        w = self.make()
        second = w.backend.create_campaign(w.contract_key, 1, "bench-A", "tpe", 2, 3, 2, SAM)
        view = w.backend.validate_campaign(second["id"], second["version"], SAM)
        self.assertEqual(self.code(w.backend.arm_campaign, second["id"], view["version"], SAM), "FAILED_PRECONDITION")

    def test_roles_are_enforced(self):
        w = self.make(arm=False)
        self.assertEqual(self.code(w.backend.create_campaign, w.contract_key, 1, "bench-A", "tpe", 1, 3, 2, DANA),
                         "PERMISSION_DENIED")
        self.assertEqual(self.code(w.backend.arm_campaign, w.campaign_id, w.version, DANA), "PERMISSION_DENIED")
        self.assertEqual(self.code(w.backend.clear_lockout, w.campaign_id, 1, SAM, physical_inspection=True, note="x"),
                         "PERMISSION_DENIED")

    def test_pause_resume_and_abort_with_no_active_episode(self):
        w = self.make()
        view = w.backend.pause_campaign(w.campaign_id, w.version, SAM)
        self.assertEqual(view["state"], "PAUSED")
        view = w.backend.resume_campaign(w.campaign_id, view["version"], SAM)
        self.assertEqual(view["state"], "RUNNING")
        view = w.backend.abort_campaign(w.campaign_id, view["version"], SAM)
        self.assertEqual(view["state"], "ABORTED")
        self.assertEqual(self.code(w.backend.resume_campaign, w.campaign_id, view["version"], SAM), "FAILED_PRECONDITION")

    def test_disarm_only_while_armed(self):
        w = self.make(start=False)
        self.assertEqual(w.backend.abort_campaign(w.campaign_id, w.version, SAM, disarm=True)["state"], "ABORTED")
        w2 = World()
        try:
            self.assertEqual(self.code(w2.backend.abort_campaign, w2.campaign_id, w2.version, SAM, disarm=True),
                             "FAILED_PRECONDITION")
        finally:
            w2.close()

    def test_every_transition_is_audited(self):
        w = self.make()
        events = w.backend.list_events(w.campaign_id)
        states = [e["newState"] for e in events if e["entity"] == "campaign"]
        self.assertEqual(states, ["DRAFT", "VALIDATING", "READY", "ARMED", "RUNNING"])
        self.assertTrue(all(e["actorId"] and e["reasonCode"] and e["reason"] for e in events))
        with self.assertRaises(sqlite3.DatabaseError):
            with w.db.transaction() as c:
                c.execute("DELETE FROM events")


class CandidateTests(Case):
    def test_valid_candidate_becomes_an_available_episode(self):
        w = self.make()
        result = w.submit()
        self.assertEqual(result["state"], "MATERIALIZED")
        self.assertEqual(w.backend.get_episode(result["episodeId"])["state"], "AVAILABLE")

    def test_unsafe_candidates_never_become_episodes(self):
        w = self.make()
        unsafe = [{**CANDIDATE, "oledRailV": 3.61}, {**CANDIDATE, "oledRailV": 3.255}, {**CANDIDATE, "workload": "wifi"},
                  {**CANDIDATE, "workload": "flash_write", "sensorRailV": 3.55, "flashOffsetMs": 3},
                  {**CANDIDATE, "flashOffsetMs": 5}, {k: v for k, v in CANDIDATE.items() if k != "dwellMs"},
                  {**CANDIDATE, "redLed": 1}, {**CANDIDATE, "dwellMs": 9900}]
        for index, conditions in enumerate(unsafe):
            result = w.submit(index, conditions)
            self.assertEqual(result["state"], "REJECTED", conditions)
            self.assertIsNone(result["episodeId"])
            self.assertTrue(result["violations"])
        self.assertEqual(w.view()["budget"]["discoveryUsed"], 0)       # rejection spends no physical budget
        self.assertEqual(w.view()["candidatesRejected"], len(unsafe))
        self.assertEqual(len(w.backend.rejected_conditions(w.campaign_id)), len(unsafe))
        self.assertIsNone(w.claim())

    def test_nan_and_non_json_candidates_are_refused_before_storage(self):
        w = self.make()
        self.assertEqual(self.code(w.submit, 0, {**CANDIDATE, "oledRailV": float("nan")}), "INVALID_ARGUMENT")
        self.assertEqual(self.code(w.submit, 0, {**CANDIDATE, "oledRailV": object()}), "INVALID_ARGUMENT")

    def test_idempotent_on_sequence_and_conflict_on_different_body(self):
        w = self.make()
        first = w.submit(7)
        again = w.submit(7)
        self.assertEqual((first["candidateId"], first["episodeId"]), (again["candidateId"], again["episodeId"]))
        self.assertEqual(w.view()["budget"]["discoveryUsed"], 1)
        self.assertEqual(self.code(w.submit, 7, {**CANDIDATE, "oledRailV": 3.26}), "IDEMPOTENCY_MISMATCH")

    def test_only_while_running(self):
        w = self.make(start=False)
        self.assertEqual(self.code(w.submit, 0), "FAILED_PRECONDITION")

    def test_discovery_budget_is_enforced(self):
        w = self.make(discovery=2)
        self.assertEqual(w.submit(0)["state"], "MATERIALIZED")
        self.assertEqual(w.submit(1, {**CANDIDATE, "oledRailV": 3.26})["state"], "MATERIALIZED")
        third = w.submit(2, {**CANDIDATE, "oledRailV": 3.27})
        self.assertEqual(third["state"], "REJECTED")
        self.assertEqual(third["violations"][0]["code"], "BUDGET_EXHAUSTED")

    def test_verification_candidates_need_links_and_use_their_own_pool(self):
        w = self.make(discovery=1, verification=1)
        discovery = w.submit(0)
        self.assertEqual(self.code(w.submit, 1, role="confirm"), "INVALID_ARGUMENT")
        self.assertEqual(self.code(w.submit, 1, role="confirm", linked_episode_id="nope", repeat_reason="replay"),
                         "INVALID_ARGUMENT")
        self.assertEqual(self.code(w.submit, 1, linked_episode_id=discovery["episodeId"], repeat_reason="x"),
                         "INVALID_ARGUMENT")
        replay = w.submit(1, role="confirm", linked_episode_id=discovery["episodeId"], repeat_reason="replay 1")
        self.assertEqual(replay["state"], "MATERIALIZED")
        self.assertEqual(w.backend.get_episode(replay["episodeId"])["linkedEpisodeId"], discovery["episodeId"])
        used = w.view()["budget"]
        self.assertEqual((used["discoveryUsed"], used["verificationUsed"]), (1, 1))
        self.assertEqual(w.submit(2, role="bracket", linked_episode_id=discovery["episodeId"],
                                  repeat_reason="more")["violations"][0]["code"], "BUDGET_EXHAUSTED")


class BenchTests(Case):
    def test_claim_is_exclusive_and_ordered(self):
        w = self.make()
        w.submit(0)
        w.submit(1, {**CANDIDATE, "oledRailV": 3.26})
        first = w.claim()
        self.assertEqual(first["requested"]["oledRailV"], 3.25)
        self.assertIsNone(w.claim(), "a second lease must not be issued while one is active")
        self.assertEqual(w.backend.get_episode(first["episodeId"])["state"], "LEASED")

    def test_no_claim_unless_running(self):
        w = self.make()
        w.submit(0)
        w.backend.pause_campaign(w.campaign_id, w.view()["version"], SAM)
        self.assertIsNone(w.claim())

    def test_phases_must_be_legal(self):
        w = self.make()
        w.submit(0)
        claim = w.claim()
        self.assertEqual(self.code(w.backend.heartbeat, claim["leaseId"], "bench-A", "EXECUTING"), "FAILED_PRECONDITION")
        self.assertEqual(self.code(w.backend.heartbeat, claim["leaseId"], "bench-A", "WARPING"), "INVALID_ARGUMENT")
        w.walk(claim, "PREFLIGHT", "CONFIGURING")
        self.assertEqual(w.backend.get_episode(claim["episodeId"])["state"], "CONFIGURING")

    def test_other_fixture_cannot_touch_a_lease(self):
        w = self.make()
        w.backend.register_fixture("bench-B", "A", ["dut"], DANA)
        w.submit(0)
        claim = w.claim()
        self.assertEqual(self.code(w.backend.heartbeat, claim["leaseId"], "bench-B"), "NOT_FOUND")
        self.assertEqual(self.code(w.backend.acknowledge_abort, claim["leaseId"], "bench-B"), "NOT_FOUND")

    def test_heartbeat_extends_but_never_beyond_the_episode_bound(self):
        w = self.make()
        w.submit(0)
        claim = w.claim()
        issued = w.clock.now()
        for _ in range(9):
            w.clock.advance(1)
            reply = w.backend.heartbeat(claim["leaseId"], "bench-A")
        # maxEpisodeS (10) + shutdown allowance (0.5) after issue is the hard stop, not now + 5 s.
        self.assertEqual(reply["leaseExpiresAt"], isoformat(issued + timedelta(seconds=10.5)))
        w.clock.advance(2)
        self.assertEqual(self.code(w.backend.heartbeat, claim["leaseId"], "bench-A"), "FAILED_PRECONDITION")

    def test_expired_lease_needs_reconciliation_and_blocks_new_work(self):
        w = self.make()
        w.submit(0)
        w.submit(1, {**CANDIDATE, "oledRailV": 3.26})
        claim = w.claim()
        w.walk(claim, "PREFLIGHT", "CONFIGURING")
        w.clock.advance(6)
        self.assertEqual(self.code(w.backend.heartbeat, claim["leaseId"], "bench-A"), "FAILED_PRECONDITION")
        row = w.db.one("SELECT state FROM leases WHERE id = ?", (claim["leaseId"],))
        self.assertEqual(row["state"], "NEEDS_RECONCILIATION")
        self.assertIsNone(w.claim(), "an unreconciled lease must block the next claim")
        self.assertEqual(w.backend.get_episode(claim["episodeId"])["state"], "CONFIGURING")   # not re-queued

    def test_reconciliation_finishes_the_episode_invalid_and_locks_out(self):
        w = self.make()
        w.submit(0)
        claim = w.claim()
        w.walk(claim, "PREFLIGHT", "CONFIGURING")
        w.clock.advance(6)
        self.assertEqual(w.backend.expire_leases(), [claim["leaseId"]])
        self.assertEqual(self.code(w.backend.reconcile_lease, claim["leaseId"], "not_executed", "x", SAM), "PERMISSION_DENIED")
        self.assertEqual(self.code(w.backend.reconcile_lease, claim["leaseId"], "retry", "x", DANA), "INVALID_ARGUMENT")
        w.backend.reconcile_lease(claim["leaseId"], "evidence_lost", "cable pulled", DANA)
        episode = w.backend.get_episode(claim["episodeId"])
        self.assertEqual((episode["state"], episode["outcome"]), ("FINALIZED", "INVALID_EXPERIMENT"))
        self.assertEqual(w.view()["state"], "LOCKED_OUT")

    def test_health_trip_locks_out_an_armed_campaign(self):
        w = self.make(start=False)
        w.backend.record_bench_health("bench-A", {**GOOD_HEALTH, "tripActive": True})
        self.assertEqual(w.view()["state"], "LOCKED_OUT")
        view = w.backend.clear_lockout(w.campaign_id, w.view()["version"], DANA, physical_inspection=True, note="checked")
        self.assertEqual(view["state"], "DRAFT")
        self.assertEqual(self.code(w.backend.clear_lockout, w.campaign_id, view["version"], DANA,
                                   physical_inspection=True, note="x"), "FAILED_PRECONDITION")

    def test_clear_lockout_needs_inspection_and_note(self):
        w = self.make(start=False)
        w.backend.record_bench_health("bench-A", {**GOOD_HEALTH, "estopReleased": False})
        version = w.view()["version"]
        self.assertEqual(self.code(w.backend.clear_lockout, w.campaign_id, version, DANA, physical_inspection=False, note="x"),
                         "INVALID_ARGUMENT")
        self.assertEqual(self.code(w.backend.clear_lockout, w.campaign_id, version, DANA, physical_inspection=True, note=" "),
                         "INVALID_ARGUMENT")

    def test_pause_waits_for_the_active_episode(self):
        w = self.make()
        w.submit(0)
        claim = w.claim()
        view = w.backend.pause_campaign(w.campaign_id, w.view()["version"], SAM)
        self.assertEqual(view["state"], "PAUSING")
        reply = w.backend.heartbeat(claim["leaseId"], "bench-A", "PREFLIGHT")
        self.assertTrue(reply["pause"] and not reply["abort"])
        w.walk(claim, "CONFIGURING", "SETTLING", "EXECUTING", "OBSERVING", "SHUTTING_DOWN")
        w.backend.submit_result(w.payload(claim), "bench-A")
        self.assertEqual(w.view()["state"], "PAUSED")

    def test_abort_waits_for_acknowledged_shutdown(self):
        w = self.make()
        w.submit(0)
        claim = w.claim()
        w.walk(claim, "PREFLIGHT", "CONFIGURING")
        view = w.backend.abort_campaign(w.campaign_id, w.view()["version"], SAM)
        self.assertEqual(view["state"], "ABORTING")
        self.assertTrue(w.backend.heartbeat(claim["leaseId"], "bench-A")["abort"])
        self.assertEqual(self.code(w.backend.acknowledge_abort, claim["leaseId"], "bench-A"), "FAILED_PRECONDITION")
        w.walk(claim, "SHUTTING_DOWN")
        self.assertEqual(w.backend.acknowledge_abort(claim["leaseId"], "bench-A")["campaignState"], "ABORTED")


class ResultTests(Case):
    def test_nominal_pass(self):
        w = self.make()
        verdict = w.run_episode()
        self.assertEqual((verdict["outcome"], verdict["state"]), ("PASS", "FINALIZED"))
        self.assertEqual(verdict["robustness"], 1.0)
        episode = w.backend.get_episode(verdict["episodeId"])
        self.assertEqual(episode["measured"]["oledLatencyMs"]["value"], 31.0)
        self.assertEqual(episode["measured"]["measuredOledRailV"]["requested"], 3.25)   # requested and measured apart
        self.assertEqual(episode["requested"]["oledRailV"], 3.25)

    def test_dut_failure_and_inconclusive_and_invalid(self):
        w = self.make(discovery=6)
        failure = w.run_episode(0, measured={"oledLatencyMs": 151.0})
        self.assertEqual((failure["outcome"], failure["requirements"]["latency"]), ("DUT_FAILURE", "FAIL"))
        self.assertLess(failure["robustness"], 0)
        inconclusive = w.run_episode(1, {**CANDIDATE, "oledRailV": 3.26}, measured={"oledLatencyMs": 121.0})
        self.assertEqual((inconclusive["outcome"], inconclusive["reasonCode"]), ("INVALID_EXPERIMENT", "INCONCLUSIVE"))
        self.assertIsNone(inconclusive["robustness"])
        wrong_rail = w.run_episode(2, {**CANDIDATE, "oledRailV": 3.27}, measured={"measuredOledRailV": 3.20})
        self.assertEqual(wrong_rail["reasonCode"], "CONDITIONS_NOT_APPLIED")
        unsettled = w.run_episode(3, {**CANDIDATE, "oledRailV": 3.28}, settled=False)
        self.assertEqual(unsettled["reasonCode"], "INSTRUMENT_ERROR")
        missing = w.run_episode(4, {**CANDIDATE, "oledRailV": 3.29}, measured={"oledLatencyMs": None})
        self.assertEqual(missing["reasonCode"], "MISSING_OBSERVATION")
        history = w.backend.episode_history(w.campaign_id)
        self.assertEqual([h["outcome"] for h in history], ["DUT_FAILURE", "INVALID_EXPERIMENT", "INVALID_EXPERIMENT",
                                                          "INVALID_EXPERIMENT", "INVALID_EXPERIMENT"])
        self.assertIsNotNone(history[0]["robustness"])
        self.assertTrue(all(h["robustness"] is None for h in history[1:]))      # invalid results never train planners

    def test_result_is_idempotent_and_conflicts_are_integrity_errors(self):
        w = self.make()
        w.submit(0)
        claim = w.claim()
        w.walk(claim, "PREFLIGHT", "CONFIGURING", "SETTLING", "EXECUTING", "OBSERVING", "SHUTTING_DOWN")
        payload = w.payload(claim)
        first = w.backend.submit_result(payload, "bench-A")
        self.assertEqual(w.backend.submit_result(payload, "bench-A"), first)
        different = w.payload(claim, measured={"oledLatencyMs": 150.0})
        self.assertEqual(self.code(w.backend.submit_result, different, "bench-A"), "INTEGRITY_ERROR")
        self.assertEqual(w.backend.get_episode(claim["episodeId"])["outcome"], "PASS")

    def test_tampered_payload_and_wrong_bindings_are_rejected(self):
        w = self.make()
        w.submit(0)
        claim = w.claim()
        w.walk(claim, "PREFLIGHT", "CONFIGURING", "SETTLING", "EXECUTING", "OBSERVING", "SHUTTING_DOWN")
        payload = w.payload(claim)
        tampered = copy.deepcopy(payload)
        tampered["measured"]["oledLatencyMs"]["value"] = 5.0
        self.assertEqual(self.code(w.backend.submit_result, tampered, "bench-A"), "INTEGRITY_ERROR")
        self.assertEqual(self.code(w.backend.submit_result, payload, "bench-B"), "PERMISSION_DENIED")
        from activequal.model.evidence import manifest_hash
        for key, value in (("contractHash", "f" * 64), ("requested", {**claim["requested"], "oledRailV": 3.30})):
            changed = {**payload, key: value}
            changed["manifestHash"] = manifest_hash(changed)
            self.assertEqual(self.code(w.backend.submit_result, changed, "bench-A"), "INTEGRITY_ERROR", key)
        self.assertEqual(w.backend.get_episode(claim["episodeId"])["state"], "SHUTTING_DOWN")

    def test_evidence_before_shutdown_is_refused(self):
        w = self.make()
        w.submit(0)
        claim = w.claim()
        w.walk(claim, "PREFLIGHT", "CONFIGURING", "SETTLING", "EXECUTING")
        self.assertEqual(self.code(w.backend.submit_result, w.payload(claim), "bench-A"), "FAILED_PRECONDITION")
        w.walk(claim, "OBSERVING", "SHUTTING_DOWN")
        self.assertEqual(self.code(w.backend.submit_result, w.payload(claim, shutdown=False), "bench-A"),
                         "FAILED_PRECONDITION")

    def test_safety_trip_finalizes_and_locks_out_the_campaign(self):
        w = self.make()
        w.submit(0)
        claim = w.claim()
        w.walk(claim, "PREFLIGHT", "CONFIGURING", "SETTLING", "EXECUTING", "EMERGENCY_CUTOFF", "LOCKOUT")
        verdict = w.backend.submit_result(w.payload(claim, trip="over-current ch2", shutdown=False, measured={"oledLatencyMs": None}),
                                          "bench-A")
        self.assertEqual((verdict["outcome"], verdict["state"]), ("SAFETY_ABORT", "FINALIZED"))
        self.assertEqual(w.view()["state"], "LOCKED_OUT")
        self.assertIsNone(w.claim())
        self.assertEqual(w.backend.episode_history(w.campaign_id)[0]["robustness"], None)

    def test_cutoff_without_a_named_trip_is_still_a_safety_abort(self):
        w = self.make()
        w.submit(0)
        claim = w.claim()
        w.walk(claim, "PREFLIGHT", "CONFIGURING", "SETTLING", "EXECUTING", "EMERGENCY_CUTOFF")
        verdict = w.backend.submit_result(w.payload(claim, shutdown=False), "bench-A")
        self.assertEqual((verdict["outcome"], verdict["state"]), ("SAFETY_ABORT", "FINALIZED"))
        self.assertEqual(w.view()["state"], "LOCKED_OUT")

    def test_trip_claimed_without_cutoff_phase_is_refused(self):
        w = self.make()
        w.submit(0)
        claim = w.claim()
        w.walk(claim, "PREFLIGHT", "CONFIGURING", "SETTLING", "EXECUTING", "OBSERVING", "SHUTTING_DOWN")
        self.assertEqual(self.code(w.backend.submit_result, w.payload(claim, trip="x"), "bench-A"), "FAILED_PRECONDITION")

    def test_traces_must_be_uploaded_first_and_are_content_addressed(self):
        w = self.make()
        data = b"trace-bytes" * 100
        digest = hashlib.sha256(data).hexdigest()
        w.submit(0)
        claim = w.claim()
        w.walk(claim, "PREFLIGHT", "CONFIGURING", "SETTLING", "EXECUTING", "OBSERVING", "SHUTTING_DOWN")
        payload = w.payload(claim, traces=[{"sha256": digest, "mediaType": "application/octet-stream", "bytes": len(data)}])
        self.assertEqual(self.code(w.backend.submit_result, payload, "bench-A"), "FAILED_PRECONDITION")
        self.assertEqual(self.code(w.backend.put_trace, digest, data + b"x", "application/octet-stream", "bench-A"),
                         "INTEGRITY_ERROR")
        self.assertEqual(self.code(w.backend.put_trace, "../../etc/passwd", data, "x/y", "bench-A"), "INVALID_ARGUMENT")
        w.backend.put_trace(digest, data, "application/octet-stream", "bench-A")
        w.backend.put_trace(digest, data, "application/octet-stream", "bench-A")        # idempotent
        stored = w.backend.trace_dir / digest[:2] / digest[2:4] / digest
        self.assertEqual(stored.read_bytes(), data)
        w.backend.submit_result(payload, "bench-A")
        self.assertEqual(w.db.one("SELECT episode_id FROM traces WHERE sha256 = ?", (digest,))["episode_id"], claim["episodeId"])

    def test_complete_campaign_requires_nothing_in_flight(self):
        w = self.make()
        w.submit(0)
        self.assertEqual(self.code(w.backend.complete_campaign, w.campaign_id, "done"), "FAILED_PRECONDITION")
        claim = w.claim()
        w.walk(claim, "PREFLIGHT", "CONFIGURING", "SETTLING", "EXECUTING", "OBSERVING", "SHUTTING_DOWN")
        w.backend.submit_result(w.payload(claim), "bench-A")
        self.assertEqual(w.backend.complete_campaign(w.campaign_id, "budget reached")["state"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
