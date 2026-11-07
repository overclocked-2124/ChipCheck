from __future__ import annotations

import dataclasses
import subprocess
import sys
import time
import unittest
from pathlib import Path

from activequal.adapter import (ApprovedEpisode, BenchAdapter, FaultInjection, FaultKind, Phase,
                                SimulatedBenchAdapter, Trip)
from activequal.adapter.service.simulator import (FAIL_LINE_MS, PROFILE_NAMES, WORKLOADS, BenchLockedOut)
from activequal.adapter.service.types import RawBenchCapture

REPO = Path(__file__).resolve().parents[4]
TARGET = {"oledRailV": 3.25, "redLed": True, "greenLed": False, "workload": "oled_refresh"}


def episode(conditions=None, seed=1, attempt=1, name="ep-1", duration_ms=500) -> ApprovedEpisode:
    return ApprovedEpisode(name, attempt, "hash", "bench-A", dict(conditions or TARGET), duration_ms, seed)


def all_points():
    for i in range(61):
        for red in (False, True):
            for green in (False, True):
                for workload in WORKLOADS:
                    yield {"oledRailV": round(3.0 + i * 0.01, 2), "redLed": red, "greenLed": green,
                           "workload": workload}


def failing_points(profile: str) -> list[dict]:
    """Noise-free guard-banded failures: latency above 120 ms + U = 5 ms, or any reset."""
    adapter = SimulatedBenchAdapter(profile)
    result = []
    for point in all_points():
        expected = adapter.expected_observations(point)
        if expected.get("oledLatencyMs", 0.0) > FAIL_LINE_MS or expected["resetCount"] > 0:
            result.append(point)
    return result


class SurfaceTests(unittest.TestCase):
    def test_space_has_1220_points(self) -> None:
        self.assertEqual(len(list(all_points())), 1220)

    def test_failing_point_counts_match_hld_06(self) -> None:
        counts = {name: len(failing_points(name)) for name in PROFILE_NAMES}
        self.assertEqual(counts, {"B1a": 5, "B1b": 5, "B1w": 11, "B2": 8, "B3": 0})

    def test_failing_points_are_where_the_hld_says(self) -> None:
        for name, volts in (("B1a", range(23, 28)), ("B1b", range(23, 28)), ("B1w", range(20, 31))):
            points = failing_points(name)
            self.assertEqual({round((p["oledRailV"] - 3.0) * 100) for p in points}, set(volts), name)
            self.assertTrue(all(p["redLed"] and not p["greenLed"] and p["workload"] == "oled_refresh"
                                for p in points), name)
        b2 = failing_points("B2")
        self.assertEqual({round((p["oledRailV"] - 3.0) * 100) for p in b2}, {15, 16, 17, 18})
        self.assertTrue(all(p["redLed"] and p["workload"] == "sensor_read" for p in b2))
        self.assertEqual({p["greenLed"] for p in b2}, {True, False})

    def test_precursors(self) -> None:
        near = {**TARGET, "oledRailV": 3.30}          # outside the B1a island, inside the precursor
        wrong = {**near, "redLed": False}
        for profile, wrong_visible in (("B1a", True), ("B1b", False)):
            adapter = SimulatedBenchAdapter(profile)
            self.assertGreater(adapter.expected_observations(near)["oledLatencyMs"], 60.0)
            seen = adapter.expected_observations(wrong)["oledLatencyMs"]
            self.assertEqual(seen > 40.0, wrong_visible, profile)
        self.assertEqual(SimulatedBenchAdapter("B2").expected_observations(TARGET)["oledLatencyMs"], 31.0)
        self.assertEqual(SimulatedBenchAdapter("B3").expected_observations(TARGET)["oledLatencyMs"], 31.0)

    def test_short_dwell_does_not_trigger_the_fault(self) -> None:
        adapter = SimulatedBenchAdapter("B1w")
        self.assertGreater(adapter.expected_observations({**TARGET, "dwellMs": 300})["oledLatencyMs"], 120.0)
        self.assertEqual(adapter.expected_observations({**TARGET, "dwellMs": 200})["oledLatencyMs"], 31.0)

    def test_cliff_has_no_precursor(self) -> None:
        adapter = SimulatedBenchAdapter("B2")
        for volts in (3.10, 3.14, 3.19, 3.20):
            conditions = {"oledRailV": volts, "redLed": True, "greenLed": False, "workload": "sensor_read"}
            self.assertEqual(adapter.expected_observations(conditions), {"resetCount": 0.0})


class CaptureTests(unittest.TestCase):
    def test_conforms_to_protocol_and_is_fast(self) -> None:
        adapter: BenchAdapter = SimulatedBenchAdapter("B1w")
        self.assertTrue(adapter.health_check().ok)
        started = time.perf_counter()
        for seed in range(500):
            adapter.apply_and_measure(episode(seed=seed))
        self.assertLess((time.perf_counter() - started) / 500, 0.001)

    def test_normal_capture_shape(self) -> None:
        capture = SimulatedBenchAdapter("B3").apply_and_measure(episode())
        self.assertEqual(capture.phases_reached, ("PREFLIGHT", "CONFIGURING", "SETTLING", "EXECUTING",
                                                  "OBSERVING", "SHUTTING_DOWN"))
        self.assertTrue(capture.shutdown_confirmed and capture.rail_settled)
        self.assertIsNone(capture.trip)
        self.assertEqual(capture.missing_observations, ())
        self.assertAlmostEqual(capture.measured_rail_v["oledRailV"], 3.25, delta=0.015)
        self.assertEqual(set(capture.observations),
                         {"oledLatencyMs", "maxHeartbeatGapMs", "resetCount", "measuredDut3v3MinV"})

    def test_latency_only_observed_under_oled_refresh(self) -> None:
        capture = SimulatedBenchAdapter("B3").apply_and_measure(episode({**TARGET, "workload": "idle"}))
        self.assertNotIn("oledLatencyMs", capture.observations)
        self.assertEqual(capture.missing_observations, ())

    def test_latency_noise_sigma(self) -> None:
        adapter = SimulatedBenchAdapter("B3", noise_seed=5)
        values = [adapter.apply_and_measure(episode(seed=s)).observations["oledLatencyMs"] for s in range(2000)]
        mean = sum(values) / len(values)
        sd = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
        self.assertAlmostEqual(mean, 31.0, delta=0.3)
        self.assertAlmostEqual(sd, 2.5, delta=0.2)

    def test_determinism(self) -> None:
        first = SimulatedBenchAdapter("B1a", noise_seed=9).apply_and_measure(episode(seed=4))
        second = SimulatedBenchAdapter("B1a", noise_seed=9).apply_and_measure(episode(seed=4))
        self.assertEqual(first, second)
        self.assertNotEqual(first, SimulatedBenchAdapter("B1a", noise_seed=10).apply_and_measure(episode(seed=4)))
        self.assertNotEqual(first, SimulatedBenchAdapter("B1a", noise_seed=9).apply_and_measure(episode(seed=5)))
        self.assertNotEqual(first.observations, SimulatedBenchAdapter("B1a", noise_seed=9)
                            .apply_and_measure(episode(seed=4, attempt=2)).observations)

    def test_capture_carries_no_fault_data(self) -> None:
        names = {f.name for f in dataclasses.fields(RawBenchCapture)}
        self.assertFalse({n for n in names if "fault" in n or "truth" in n or "marker" in n})
        capture = SimulatedBenchAdapter("B2").apply_and_measure(
            episode({"oledRailV": 3.16, "redLed": True, "greenLed": False, "workload": "sensor_read"}))
        self.assertEqual(capture.observations["resetCount"], 1.0)       # visible only as a measurement
        self.assertNotIn("fault", repr(capture).lower())


class FaultTests(unittest.TestCase):
    def run_fault(self, kind: FaultKind, phase: Phase | None = None) -> tuple[SimulatedBenchAdapter, RawBenchCapture]:
        adapter = SimulatedBenchAdapter("B3", fault=FaultInjection(kind, phase))
        return adapter, adapter.apply_and_measure(episode())

    def test_rail_settling_timeout(self) -> None:
        _, c = self.run_fault(FaultKind.RAIL_SETTLING_TIMEOUT)
        self.assertEqual(c.phases_reached, ("PREFLIGHT", "CONFIGURING", "SETTLING", "SHUTTING_DOWN"))
        self.assertFalse(c.rail_settled)
        self.assertLess(c.measured_rail_v["oledRailV"], 3.25 - 0.1)
        self.assertTrue(c.shutdown_confirmed)
        self.assertIsNone(c.trip)
        self.assertEqual(c.observations, {})
        self.assertIn("oledLatencyMs", c.missing_observations)
        self.assertTrue(any("timeout" in e.note for e in c.events))

    def test_missing_oled_observation(self) -> None:
        _, c = self.run_fault(FaultKind.MISSING_OLED_OBSERVATION)
        self.assertNotIn("oledLatencyMs", c.observations)
        self.assertEqual(c.missing_observations, ("oledLatencyMs",))
        self.assertTrue(c.instrument_errors)
        self.assertTrue(c.rail_settled and c.shutdown_confirmed)
        self.assertIn("resetCount", c.observations)

    def test_dut_heartbeat_loss(self) -> None:
        _, c = self.run_fault(FaultKind.DUT_HEARTBEAT_LOSS)
        self.assertTrue(c.heartbeat_lost)
        self.assertEqual(c.observations["maxHeartbeatGapMs"], 500.0)
        self.assertIn("oledLatencyMs", c.missing_observations)
        self.assertTrue(c.shutdown_confirmed)
        self.assertIsNone(c.trip)

    def test_disconnect_before_output_enable(self) -> None:
        _, c = self.run_fault(FaultKind.INSTRUMENT_DISCONNECT_BEFORE_OUTPUT)
        self.assertEqual(c.phases_reached, ("PREFLIGHT", "CONFIGURING", "SHUTTING_DOWN"))
        self.assertTrue(c.instrument_errors)
        self.assertEqual((c.measured_rail_v, c.observations), ({}, {}))
        self.assertTrue(c.shutdown_confirmed)      # outputs were never enabled
        self.assertIsNone(c.trip)
        self.assertFalse(c.rail_settled)

    def test_disconnect_after_output_enable(self) -> None:
        adapter, c = self.run_fault(FaultKind.INSTRUMENT_DISCONNECT_AFTER_OUTPUT)
        self.assertEqual(c.phases_reached[-2:], ("SETTLING", "EMERGENCY_CUTOFF"))
        self.assertEqual(c.trip, Trip.INSTRUMENT_UNCERTAIN_OUTPUT)
        self.assertTrue(c.cutoff_engaged)
        self.assertFalse(c.shutdown_confirmed)
        self.assertTrue(c.instrument_errors)
        self.assertEqual(c.observations, {})
        self.assertFalse(adapter.health_check().ok)

    def test_controller_watchdog_expiry(self) -> None:
        _, c = self.run_fault(FaultKind.CONTROLLER_WATCHDOG_EXPIRY)
        self.assertEqual(c.trip, Trip.MCU_WATCHDOG)
        self.assertEqual(c.phases_reached[-2:], ("EXECUTING", "EMERGENCY_CUTOFF"))
        self.assertTrue(c.cutoff_engaged)
        self.assertFalse(c.shutdown_confirmed)
        self.assertEqual(c.observations, {})
        self.assertIn("resetCount", c.missing_observations)

    def test_estop_in_every_phase(self) -> None:
        order = ("PREFLIGHT", "CONFIGURING", "SETTLING", "EXECUTING", "OBSERVING")
        for phase in (Phase.PREFLIGHT, Phase.CONFIGURING, Phase.SETTLING, Phase.EXECUTING, Phase.OBSERVING):
            adapter, c = self.run_fault(FaultKind.ESTOP, phase)
            with self.subTest(phase=phase.value):
                self.assertEqual(c.phases_reached, order[:order.index(phase.value) + 1] + ("EMERGENCY_CUTOFF",))
                self.assertEqual(c.trip, Trip.ESTOP)
                self.assertTrue(c.cutoff_engaged)
                self.assertFalse(c.shutdown_confirmed)
                self.assertEqual(c.observations, {})
                self.assertIn("oledLatencyMs", c.missing_observations)
                energised = phase in (Phase.SETTLING, Phase.EXECUTING, Phase.OBSERVING)
                self.assertEqual(bool(c.measured_rail_v), energised)
                self.assertEqual(c.rail_settled, phase in (Phase.EXECUTING, Phase.OBSERVING))
                self.assertFalse(adapter.health_check().ok)

    def test_failed_shutdown_escalates_to_cutoff(self) -> None:
        _, c = self.run_fault(FaultKind.SHUTDOWN_FAILURE)
        self.assertEqual(c.phases_reached[-2:], ("SHUTTING_DOWN", "EMERGENCY_CUTOFF"))
        self.assertEqual(c.trip, Trip.SHUTDOWN_FAILED)
        self.assertTrue(c.cutoff_engaged)
        self.assertFalse(c.shutdown_confirmed)
        self.assertIn("oledLatencyMs", c.observations)      # measurements are preserved (HLD 03 §13)

    def test_lockout_blocks_until_manual_reset(self) -> None:
        adapter, _ = self.run_fault(FaultKind.ESTOP, Phase.SETTLING)
        health = adapter.health_check()
        self.assertTrue(health.locked_out and not health.ok)
        with self.assertRaises(BenchLockedOut):
            adapter.apply_and_measure(episode())
        adapter.reset_lockout()
        adapter.fault = FaultInjection()
        self.assertTrue(adapter.health_check().ok)
        self.assertIsNone(adapter.apply_and_measure(episode()).trip)

    def test_emergency_shutdown_latches_lockout(self) -> None:
        adapter = SimulatedBenchAdapter("B3")
        adapter.emergency_shutdown()
        self.assertTrue(adapter.health_check().locked_out)

    def test_fault_can_target_one_episode(self) -> None:
        adapter = SimulatedBenchAdapter(
            "B3", fault=FaultInjection(FaultKind.RAIL_SETTLING_TIMEOUT, episode_ids=frozenset({"bad"})))
        self.assertTrue(adapter.apply_and_measure(episode(name="good")).rail_settled)
        self.assertFalse(adapter.apply_and_measure(episode(name="bad")).rail_settled)

    def test_fault_validation(self) -> None:
        with self.assertRaises(ValueError):
            FaultInjection(FaultKind.ESTOP)
        with self.assertRaises(ValueError):
            FaultInjection(FaultKind.ESTOP, Phase.SHUTTING_DOWN)
        with self.assertRaises(ValueError):
            FaultInjection(FaultKind.RAIL_SETTLING_TIMEOUT, Phase.SETTLING)

    def test_faults_never_return_a_clean_capture(self) -> None:
        for kind in FaultKind:
            if kind in (FaultKind.NONE, FaultKind.ESTOP):
                continue
            _, c = self.run_fault(kind)
            clean = (c.trip is None and c.shutdown_confirmed and c.rail_settled and not c.missing_observations
                     and not c.instrument_errors and not c.heartbeat_lost)
            self.assertFalse(clean, kind)


class BoundaryTests(unittest.TestCase):
    def test_importing_adapter_does_not_load_optuna(self) -> None:
        code = (f"import sys; sys.path.insert(0, {str(REPO)!r}); import activequal.adapter; "
                "sys.exit(1 if any(m == 'optuna' or m.startswith('optuna.') for m in sys.modules) else 0)")
        result = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
