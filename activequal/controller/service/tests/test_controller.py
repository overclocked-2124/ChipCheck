import time
import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from activequal.adapter.service.simulator import FaultInjection, FaultKind, SimulatedBenchAdapter
from activequal.adapter.service.types import Phase
from activequal.controller.service import controller as ctl
from activequal.controller.service.client import InProcessClient
from activequal.controller.service.controller import Controller
from activequal.controller.service.spool import Spool
from activequal.service.errors import BackendError
from activequal.service.tests.support import CANDIDATE, DANA, GOOD_HEALTH, SAM, World


class Env:
    def __init__(self, profile="B3", fault=None, discovery=6, **kw):
        self.world = World(discovery=discovery)
        self.dir = tempfile.TemporaryDirectory()
        self.adapter = SimulatedBenchAdapter(profile, noise_seed=1, fault=fault, **kw)
        self.client = InProcessClient(self.world.backend, "bench-A")
        self.spool = Spool(Path(self.dir.name) / "spool")
        self.controller = Controller(self.client, self.adapter, self.spool, "bench-A", heartbeat_interval_s=0.05)

    def close(self):
        self.world.close()
        self.dir.cleanup()


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.envs = []

    def tearDown(self):
        for env in self.envs:
            env.close()

    def env(self, *a, **kw):
        env = Env(*a, **kw)
        self.envs.append(env)
        return env

    def test_nothing_to_do_returns_none(self):
        env = self.env()
        self.assertIsNone(env.controller.run_once())

    def test_normal_pass_runs_through_the_whole_loop(self):
        env = self.env("B3")
        env.world.submit(0)
        report = env.controller.run_once()
        self.assertEqual((report.status, report.verdict["outcome"]), (ctl.SUBMITTED, "PASS"))
        episode = env.world.backend.get_episode(report.episode_id)
        self.assertEqual(episode["state"], "FINALIZED")
        self.assertAlmostEqual(episode["measured"]["measuredOledRailV"]["value"], 3.25, delta=0.02)
        self.assertEqual(len(env.spool), 0)
        states = [e["newState"] for e in env.world.backend.list_events(env.world.campaign_id) if e["entity"] == "episode"]
        self.assertEqual(states, ["AVAILABLE", "LEASED", "PREFLIGHT", "CONFIGURING", "SETTLING", "EXECUTING",
                                 "OBSERVING", "SHUTTING_DOWN", "SUBMITTING", "FINALIZED"])

    def test_seeded_fault_is_found_as_a_dut_failure(self):
        env = self.env("B1w")
        env.world.submit(0, {**CANDIDATE, "oledRailV": 3.25})
        report = env.controller.run_once()
        self.assertEqual(report.verdict["outcome"], "DUT_FAILURE")
        self.assertEqual(report.verdict["requirements"]["latency"], "FAIL")

    def test_fault_cases_map_to_the_expected_outcomes(self):
        cases = [
            (FaultKind.RAIL_SETTLING_TIMEOUT, None, "INVALID_EXPERIMENT", ctl.SUBMITTED),
            (FaultKind.MISSING_OLED_OBSERVATION, None, "INVALID_EXPERIMENT", ctl.SUBMITTED),
            (FaultKind.INSTRUMENT_DISCONNECT_BEFORE_OUTPUT, None, "INVALID_EXPERIMENT", ctl.SUBMITTED),
            (FaultKind.INSTRUMENT_DISCONNECT_AFTER_OUTPUT, None, "SAFETY_ABORT", ctl.CUTOFF),
            (FaultKind.CONTROLLER_WATCHDOG_EXPIRY, None, "SAFETY_ABORT", ctl.CUTOFF),
            (FaultKind.SHUTDOWN_FAILURE, None, "SAFETY_ABORT", ctl.CUTOFF),
        ] + [(FaultKind.ESTOP, phase, "SAFETY_ABORT", ctl.CUTOFF) for phase in
             (Phase.PREFLIGHT, Phase.CONFIGURING, Phase.SETTLING, Phase.EXECUTING, Phase.OBSERVING)]
        for kind, phase, outcome, status in cases:
            with self.subTest(kind=kind.value, phase=phase):
                env = self.env("B3", fault=FaultInjection(kind, phase) if phase else FaultInjection(kind))
                env.world.submit(0)
                report = env.controller.run_once()
                self.assertEqual((report.status, report.verdict["outcome"]), (status, outcome))
                self.assertEqual(env.world.backend.get_episode(report.episode_id)["state"], "FINALIZED")
                if outcome == "SAFETY_ABORT":
                    self.assertEqual(env.world.view()["state"], "LOCKED_OUT")
                    self.assertFalse(env.adapter.health_check().ok)

    def test_heartbeat_loss_is_a_dut_failure_when_nothing_else_is_missing(self):
        env = self.env("B3", fault=FaultInjection(FaultKind.DUT_HEARTBEAT_LOSS))
        env.world.submit(0, {**CANDIDATE, "workload": "sensor_read", "dwellMs": 2000})
        report = env.controller.run_once()
        self.assertEqual(report.verdict["outcome"], "DUT_FAILURE")
        self.assertEqual(report.verdict["requirements"]["heartbeat"], "FAIL")

    def test_heartbeat_loss_with_a_required_latency_missing_is_still_a_dut_failure(self):
        # HLD 03 §15.1 step 3a: a valid heartbeat violation stands even though OLED latency is missing.
        env = self.env("B3", fault=FaultInjection(FaultKind.DUT_HEARTBEAT_LOSS))
        env.world.submit(0, {**CANDIDATE, "dwellMs": 2000})
        report = env.controller.run_once()
        self.assertEqual((report.verdict["outcome"], report.verdict["reasonCode"]),
                         ("DUT_FAILURE", "REQUIREMENT_VIOLATED"))
        self.assertIn("missing", report.verdict["reason"])

    def test_after_a_cutoff_the_bench_claims_nothing_until_reset(self):
        env = self.env("B3", fault=FaultInjection(FaultKind.ESTOP, Phase.EXECUTING, episode_ids=None))
        env.world.submit(0)
        env.controller.run_once()
        env.world.backend.clear_lockout(env.world.campaign_id, env.world.view()["version"],
                                        DANA,
                                        physical_inspection=True, note="inspected")
        report = env.controller.run_once()
        self.assertEqual(report.status, ctl.BENCH_UNHEALTHY)          # the interlock is still latched
        env.adapter.reset_lockout()
        self.assertIsNone(env.controller.run_once())                   # healthy again; nothing running

    def test_unreachable_control_plane_spools_the_evidence_then_uploads_it(self):
        env = self.env("B3")
        env.world.submit(0)
        real = env.client.submit_result
        down = {"on": True}

        def flaky(payload):
            if down["on"]:
                raise ConnectionError("control plane down")
            return real(payload)
        env.client.submit_result = flaky
        report = env.controller.run_once()
        self.assertEqual(report.status, ctl.EVIDENCE_PENDING)
        self.assertEqual(len(env.spool), 1)
        self.assertEqual(env.world.backend.get_episode(report.episode_id)["state"], "SHUTTING_DOWN")
        down["on"] = False
        self.assertIsNone(env.controller.run_once())                   # flushes the spool first
        self.assertEqual(len(env.spool), 0)
        self.assertEqual(env.world.backend.get_episode(report.episode_id)["outcome"], "PASS")

    def test_flush_is_idempotent_when_backend_already_has_the_result(self):
        env = self.env("B3")
        env.world.submit(0)
        report = env.controller.run_once()
        self.assertEqual(report.status, ctl.SUBMITTED)
        saved = env.world.backend.db.one("SELECT payload_json FROM results")["payload_json"]
        env.spool.save(json.loads(saved))
        self.assertEqual(env.controller.flush_spool(), [])
        self.assertEqual(len(env.spool), 0)

    def test_adapter_crash_cuts_power_and_reports_a_trip(self):
        env = self.env("B3")
        env.world.submit(0)

        def boom(episode):
            raise RuntimeError("usb unplugged")
        env.adapter.apply_and_measure = boom
        report = env.controller.run_once()
        self.assertEqual((report.status, report.verdict["outcome"]), (ctl.CUTOFF, "SAFETY_ABORT"))
        self.assertIn("usb unplugged", report.verdict["reason"])
        self.assertEqual(env.world.view()["state"], "LOCKED_OUT")
        self.assertFalse(env.adapter.health_check().ok)

    def test_host_check_turns_an_over_limit_reading_into_a_safety_abort(self):
        env = self.env("B3")
        env.world.submit(0)
        real = env.adapter.apply_and_measure

        def over_current(episode):
            capture = real(episode)
            return dataclasses.replace(capture, measured_current_a={**capture.measured_current_a, "oledRailA": 0.35})
        env.adapter.apply_and_measure = over_current
        report = env.controller.run_once()
        self.assertEqual((report.status, report.verdict["outcome"]), (ctl.CUTOFF, "SAFETY_ABORT"))
        self.assertIn("host check: current on supply.ch2", report.verdict["reason"])
        self.assertEqual(env.world.view()["state"], "LOCKED_OUT")

    def test_an_episode_that_overruns_its_time_limit_is_cut_off(self):
        env = self.env("B3")
        env.world.submit(0)
        real_claim, real_run = env.client.claim, env.adapter.apply_and_measure

        def short_claim(instance):
            claim = real_claim(instance)
            return None if claim is None else {**claim, "maxEpisodeS": 0.1}

        def slow(episode):
            time.sleep(1.0)
            return real_run(episode)
        env.client.claim, env.adapter.apply_and_measure = short_claim, slow
        report = env.controller.run_once()
        self.assertEqual(report.verdict["outcome"], "SAFETY_ABORT")
        self.assertIn("exceeded", report.verdict["reason"])

    def test_preflight_rejects_a_claim_the_safety_rules_do_not_accept(self):
        env = self.env("B3")
        env.world.submit(0)
        real = env.client.claim

        def tampered(instance):
            claim = real(instance)
            claim["requested"] = {**claim["requested"], "oledRailV": 3.9}      # a bad claim reaching the bench
            return claim
        env.client.claim = tampered
        report = env.controller.run_once()
        self.assertEqual(report.status, ctl.PREFLIGHT_FAILED)
        self.assertTrue(any("VALUE_OUT_OF_RANGE" in d for d in report.detail))
        self.assertEqual(env.adapter.health_check().ok, True)         # nothing was energized, no lockout

    def test_preflight_rejects_a_contract_that_does_not_match_its_hash(self):
        env = self.env("B3")
        env.world.submit(0)
        real = env.client.claim

        def tampered(instance):
            claim = real(instance)
            claim["contract"]["safety"]["maxEpisodeS"] = 1000
            return claim
        env.client.claim = tampered
        report = env.controller.run_once()
        self.assertEqual(report.status, ctl.PREFLIGHT_FAILED)
        self.assertTrue(any("hash" in d for d in report.detail))

    def test_firmware_mismatch_fails_preflight(self):
        env = self.env("B3", dut_firmware_sha256="f" * 64)
        env.world.submit(0)
        env.world.backend.record_bench_health("bench-A", dict(GOOD_HEALTH))
        report = env.controller.run_once()
        self.assertIn(report.status, (ctl.PREFLIGHT_FAILED, ctl.BENCH_UNHEALTHY))

    def test_abort_requested_while_running_is_acknowledged(self):
        env = self.env("B3")
        env.world.submit(0)
        backend, world = env.world.backend, env.world
        real = env.adapter.apply_and_measure

        def slow_then_abort(episode):
            backend.abort_campaign(world.campaign_id, world.view()["version"],
                                   SAM)
            return real(episode)
        env.adapter.apply_and_measure = slow_then_abort
        report = env.controller.run_once()
        self.assertEqual(report.status, ctl.SUBMITTED)
        self.assertEqual(world.view()["state"], "ABORTED")

    def test_a_planner_loop_of_several_episodes(self):
        env = self.env("B1w", discovery=4)
        voltages = [3.00, 3.25, 3.40, 3.55]
        outcomes = []
        for sequence, volts in enumerate(voltages):
            env.world.submit(sequence, {**CANDIDATE, "oledRailV": volts})
            outcomes.append(env.controller.run_once().verdict["outcome"])
        self.assertEqual(outcomes, ["PASS", "DUT_FAILURE", "PASS", "PASS"])
        self.assertEqual(env.world.view()["budget"]["discoveryUsed"], 4)
        self.assertIsNone(env.controller.run_once())


class SpoolTests(unittest.TestCase):
    def test_atomic_save_list_remove(self):
        with tempfile.TemporaryDirectory() as folder:
            spool = Spool(folder)
            payload = {"episodeId": "e-1", "attempt": 1, "x": 1}
            spool.save(payload)
            spool.save({**payload, "x": 2})        # same key replaces, never duplicates
            self.assertEqual(len(spool), 1)
            self.assertEqual(list(spool.pending())[0]["x"], 2)
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])
            spool.remove(payload)
            self.assertEqual(len(spool), 0)
            spool.remove(payload)                  # removing twice is fine

    def test_unsafe_ids_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                Spool(folder).save({"episodeId": "../../etc/x", "attempt": 1})



class HealthReportTests(unittest.TestCase):
    def test_outputs_in_shutdown_comes_from_the_outputs_not_the_lockout(self):
        from activequal.adapter.service.types import BenchHealth
        self.assertFalse(ctl.health_report(BenchHealth(ok=False, outputs_off=False))["outputsInShutdown"])
        self.assertTrue(ctl.health_report(BenchHealth(ok=True))["outputsInShutdown"])


if __name__ == "__main__":
    unittest.main()
