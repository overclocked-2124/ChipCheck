from __future__ import annotations

import io
import json
import math
import os
import time
import unittest
from contextlib import redirect_stdout

from activequal.adapter.service.types import RawBenchCapture
from activequal.tools import benchmark
from activequal.tools.benchmark import judge, latency_margin, main, run_benchmark, run_campaign, wilson


def capture(**overrides) -> RawBenchCapture:
    fields = dict(episode_id="e", attempt=1, measured_rail_v={"oledRailV": 3.25}, measured_current_a={},
                  observations={"oledLatencyMs": 31.0, "maxHeartbeatGapMs": 200.0, "resetCount": 0.0,
                                "measuredDut3v3MinV": 3.3},
                  events=(), phases_reached=(), shutdown_confirmed=True, rail_settled=True)
    fields.update(overrides)
    return RawBenchCapture(**fields)


REQUESTED = {"oledRailV": 3.25, "redLed": True, "greenLed": False, "workload": "oled_refresh"}


def with_latency(value: float) -> RawBenchCapture:
    return capture(observations={"oledLatencyMs": value, "maxHeartbeatGapMs": 200.0, "resetCount": 0.0,
                                 "measuredDut3v3MinV": 3.3})


class ScoringTests(unittest.TestCase):
    def test_latency_margin_option_a(self) -> None:
        self.assertEqual(latency_margin(31.0), 1.0)
        self.assertEqual(latency_margin(10.0), 1.0)
        self.assertAlmostEqual(latency_margin(75.5), 0.5)
        self.assertEqual(latency_margin(120.0), 0.0)
        self.assertEqual(latency_margin(500.0), -1.0)

    def test_guard_banded_verdict(self) -> None:
        self.assertEqual(judge(with_latency(115.0), REQUESTED)[0], "PASS")
        self.assertEqual(judge(with_latency(120.0), REQUESTED)[0], "INVALID_EXPERIMENT")
        self.assertEqual(judge(with_latency(125.0), REQUESTED)[0], "INVALID_EXPERIMENT")
        outcome, robustness = judge(with_latency(125.1), REQUESTED)
        self.assertEqual(outcome, "DUT_FAILURE")
        self.assertLess(robustness, 0.0)

    def test_reset_is_exact(self) -> None:
        obs = {"maxHeartbeatGapMs": 1200.0, "resetCount": 1.0, "measuredDut3v3MinV": 3.3}
        self.assertEqual(judge(capture(observations=obs), {**REQUESTED, "workload": "sensor_read"}),
                         ("DUT_FAILURE", -1.0))

    def test_classification_order(self) -> None:
        self.assertEqual(judge(capture(trip="ESTOP"), REQUESTED), ("SAFETY_ABORT", None))
        self.assertEqual(judge(capture(rail_settled=False), REQUESTED)[0], "INVALID_EXPERIMENT")
        self.assertEqual(judge(capture(missing_observations=("oledLatencyMs",)), REQUESTED)[0], "INVALID_EXPERIMENT")
        self.assertEqual(judge(capture(measured_rail_v={}), REQUESTED)[0], "INVALID_EXPERIMENT")

    def test_wilson(self) -> None:
        low, high = wilson(18, 100)
        self.assertAlmostEqual(low, 0.1170, places=3)
        self.assertAlmostEqual(high, 0.2667, places=3)
        self.assertEqual(wilson(0, 0), (0.0, 1.0))


class CampaignTests(unittest.TestCase):
    def test_random_discovery_matches_exact_calculation_on_b2(self) -> None:
        """HLD 06 §3 finding 4: 8 failing points of 1,220, 30 draws without replacement."""
        exact = 1 - math.comb(1212, 30) / math.comb(1220, 30)
        self.assertAlmostEqual(exact, 0.181, places=3)
        campaigns = 1000
        started = time.monotonic()
        cell = run_benchmark(["random"], ["B2"], campaigns, 30, workers=min(8, os.cpu_count() or 1))["cells"][0]
        hits = cell["discovery"]["30"]["discovered"]
        band = 2.576 * math.sqrt(exact * (1 - exact) / campaigns)          # 99% binomial band
        self.assertLess(abs(hits / campaigns - exact), band, f"{hits}/{campaigns} vs exact {exact:.3f}")
        print(f"[B2 random 30ep: {hits}/{campaigns} = {hits / campaigns:.3f}, exact {exact:.3f}, "
              f"{time.monotonic() - started:.1f} s]")

    def test_clean_profile_never_reports_failure(self) -> None:
        for planner in ("random", "tpe"):
            for c in range(3):
                self.assertIsNone(run_campaign(planner, "B3", c, 30), planner)

    def test_campaign_is_reproducible_and_seeds_are_hashed(self) -> None:
        self.assertEqual(run_campaign("tpe", "B1w", 3, 30), run_campaign("tpe", "B1w", 3, 30))
        _, _, step_seed = benchmark._decision()
        seeds = [step_seed(42, c, "campaign:B1w") for c in range(5)]
        self.assertEqual(len(set(seeds)), 5)
        self.assertTrue(all(abs(a - b) > 1000 for a, b in zip(seeds, seeds[1:])))

    def test_tpe_finds_wide_island_often(self) -> None:
        report = run_benchmark(["tpe"], ["B1w"], 20, 50)
        cell = report["cells"][0]
        self.assertGreaterEqual(cell["discovery"]["50"]["rate"], 0.8)     # HLD 06: 99% over 500 campaigns

    def test_contract_is_the_1220_point_space(self) -> None:
        from activequal.decision.service.domain import domain_from_contract
        domain = domain_from_contract(benchmark.benchmark_contract(30))
        size = 1
        for values in domain.grid_values.values():
            size *= len(values)
        self.assertEqual(size, 1220)


class CliTests(unittest.TestCase):
    def test_json_output_and_default_planners(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["--planners", "random", "--profiles", "B2", "--campaigns", "3", "--budget", "5",
                                   "--json"]), 0)
        report = json.loads(out.getvalue())
        self.assertEqual(report["cells"][0]["planner"], "random")
        self.assertEqual(report["checkpoints"], [5])
        self.assertEqual(report["cells"][0]["campaigns"], 3)

    def test_planners_come_from_registry_without_gp_and_manual(self) -> None:
        _, registry, _ = benchmark._decision()
        out = io.StringIO()
        with redirect_stdout(out):
            main(["--profiles", "B3", "--campaigns", "1", "--budget", "2", "--json"])
        names = [cell["planner"] for cell in json.loads(out.getvalue())["cells"]]
        self.assertEqual(names, [n for n in registry if n not in ("gp", "manual")])

    def test_unknown_planner_is_rejected(self) -> None:
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()):
            main(["--planners", "nope"])


if __name__ == "__main__":
    unittest.main()
