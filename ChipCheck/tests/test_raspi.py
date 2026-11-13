"""Tests for the Raspberry Pi pin interaction workflow."""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest

from chipcheck.campaign import (
    CampaignResult,
    _localize_pin_failure_regions,
    run_campaign,
)
from chipcheck.contract import load_contract
from chipcheck.executor.raspi_simulator import PinScenario, RaspiPinSimulator
from chipcheck.models import ExperimentConfig, OracleOutcome
from chipcheck.oracle import evaluate
from chipcheck.storage import CampaignStorage


CONTRACT_PATH = os.path.join(os.path.dirname(__file__), "..", "contracts", "raspi_pins.yaml")


class TestRaspiPinScenarios(unittest.TestCase):
    def run_pin(self, simulator: RaspiPinSimulator, led1: float,
                led2: float, led3: float) -> int:
        result = simulator.execute(ExperimentConfig(1, parameters={
            "led1_voltage": led1,
            "led2_voltage": led2,
            "led3_voltage": led3,
        }))
        return result.results["buzzer_working"]

    def test_r1_example_interaction(self):
        sim = RaspiPinSimulator("R1")
        self.assertEqual(self.run_pin(sim, 1.65, 2.2, 1.9), 0)
        self.assertEqual(self.run_pin(sim, 1.65, 1.5, 1.9), 1)

    def test_ten_points_at_and_around_localized_r1_ranges(self):
        sim = RaspiPinSimulator("R1")
        step = 3.3 / 255
        codes_and_expected = [
            ((85, 163, 132), 0),    # low corner, inside
            ((170, 177, 162), 0),   # high corner, inside
            ((128, 170, 147), 0),   # interior
            ((84, 170, 147), 1),    # LED 1 one code below
            ((171, 170, 147), 1),   # LED 1 one code above
            ((128, 162, 147), 1),   # LED 2 one code below
            ((128, 178, 147), 1),   # LED 2 one code above
            ((128, 170, 131), 1),   # LED 3 one code below
            ((128, 170, 163), 1),   # LED 3 one code above
            ((85, 177, 132), 0),    # mixed inclusive boundary point
        ]
        for codes, expected in codes_and_expected:
            with self.subTest(codes=codes):
                voltages = [code * step for code in codes]
                self.assertEqual(self.run_pin(sim, *voltages), expected)

    def test_localizer_recovers_ten_distinct_failure_boxes(self):
        contract = load_contract(CONTRACT_PATH)
        step = 3.3 / 255
        cases = [
            ((20, 80), (90, 150), (160, 220)),
            ((5, 45), (75, 125), (180, 240)),
            ((30, 100), (20, 70), (120, 200)),
            ((100, 180), (40, 110), (10, 90)),
            ((60, 140), (130, 210), (80, 150)),
            ((15, 95), (160, 230), (30, 100)),
            ((110, 200), (5, 65), (140, 220)),
            ((40, 120), (80, 170), (190, 250)),
            ((70, 160), (100, 180), (20, 110)),
            ((125, 210), (30, 95), (100, 190)),
        ]
        names = ["led1_voltage", "led2_voltage", "led3_voltage"]
        storage = CampaignStorage(":memory:")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                for case_index, code_ranges in enumerate(cases, start=1):
                    failure_region = {
                        name: (low * step, high * step)
                        for name, (low, high) in zip(names, code_ranges)
                    }
                    scenario = PinScenario(f"BOX{case_index}", "Test box", failure_region)
                    simulator = RaspiPinSimulator(scenario)
                    anchor_codes = [(low + high) // 2 for low, high in code_ranges]
                    anchor = ExperimentConfig(
                        case_index,
                        parameters={name: code * step for name, code in zip(names, anchor_codes)},
                    )
                    anchor_verdict = evaluate(simulator.execute(anchor), contract, config=anchor)
                    self.assertEqual(anchor_verdict.outcome, OracleOutcome.DUT_FAILURE)

                    campaign_id = f"box{case_index}"
                    storage.create_campaign(campaign_id, contract.contract_id, contract.version,
                                            "tpe", scenario.name, 42, 1)
                    result = CampaignResult()
                    _localize_pin_failure_regions(
                        contract=contract,
                        executor=simulator,
                        storage=storage,
                        campaign_id=campaign_id,
                        failure_points=[(anchor, anchor_verdict)],
                        result=result,
                        start_exp_id=case_index + 1,
                        start_trial=1,
                        planner_type="tpe",
                        benchmark=scenario.name,
                        seed=42,
                        binary_single_region=True,
                    )

                    self.assertEqual(len(result.localized_regions), 1)
                    recovered = result.localized_regions[0]
                    for name, expected_codes in zip(names, code_ranges):
                        recovered_codes = tuple(round(v / step) for v in recovered[name])
                        self.assertEqual(recovered_codes, expected_codes,
                                         msg=f"case {case_index}, {name}")
        finally:
            storage.close()

    def test_r4_is_no_fault(self):
        sim = RaspiPinSimulator("R4")
        self.assertEqual(self.run_pin(sim, 1.65, 2.2, 1.9), 1)
        self.assertEqual(self.run_pin(sim, 0.0, 3.3, 1.1), 1)

    def test_r5_detects_separate_led1_windows(self):
        sim = RaspiPinSimulator("R5")
        self.assertEqual(self.run_pin(sim, 1.2, 1.9, 1.9), 0)
        self.assertEqual(self.run_pin(sim, 1.7, 1.9, 1.9), 1)
        self.assertEqual(self.run_pin(sim, 2.2, 1.9, 1.9), 0)

    def test_localization_keeps_two_disjoint_windows_separate(self):
        contract = load_contract(CONTRACT_PATH)
        simulator = RaspiPinSimulator("R5")
        anchors = [
            ExperimentConfig(i, parameters={
                "led1_voltage": led1,
                "led2_voltage": 1.9023529411764706,
                "led3_voltage": 1.9023529411764706,
            })
            for i, led1 in enumerate((1.1647058823529413, 2.2), start=1)
        ]
        failures = []
        for config in anchors:
            execution = simulator.execute(config)
            verdict = evaluate(execution, contract, config=config)
            self.assertEqual(verdict.outcome, OracleOutcome.DUT_FAILURE)
            failures.append((config, verdict))

        storage = CampaignStorage(":memory:")
        storage.create_campaign("localize", contract.contract_id, contract.version,
                                "tpe", "R5", 42, 2)
        result = CampaignResult()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                _localize_pin_failure_regions(
                    contract=contract,
                    executor=simulator,
                    storage=storage,
                    campaign_id="localize",
                    failure_points=failures,
                    result=result,
                    start_exp_id=3,
                    start_trial=2,
                    planner_type="tpe",
                    benchmark="R5",
                    seed=42,
                )
        finally:
            storage.close()

        self.assertEqual(len(result.localized_regions), 2)
        first = result.localized_regions[0]["led1_voltage"]
        second = result.localized_regions[1]["led1_voltage"]
        self.assertLess(first[1], second[0])

    def test_console_campaign_prints_each_test_without_artifacts(self):
        contract = load_contract(CONTRACT_PATH)
        with tempfile.TemporaryDirectory() as output_dir:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = run_campaign(
                    contract=contract,
                    planner_type="tpe",
                    benchmark="R2",
                    budget=4,
                    seed=42,
                    output_dir=output_dir,
                    console_only=True,
                )

            lines = [line for line in stdout.getvalue().splitlines() if line.startswith("[TEST ")]
            boundary_lines = [line for line in stdout.getvalue().splitlines() if line.startswith("[BOUNDARY ")]
            self.assertEqual(len(lines), 4)
            self.assertGreater(len(boundary_lines), 0)
            self.assertIn("BUZZER FAILED", lines[0])
            self.assertGreater(result.experiments_executed, 4)
            self.assertEqual(len(result.localized_regions), 1)
            region = result.localized_regions[0]
            self.assertAlmostEqual(region["led1_voltage"][0], 0.8023529412, places=6)
            self.assertAlmostEqual(region["led1_voltage"][1], 2.4976470588, places=6)
            self.assertAlmostEqual(region["led2_voltage"][0], 1.0094117647, places=6)
            self.assertAlmostEqual(region["led2_voltage"][1], 2.7952941176, places=6)
            self.assertAlmostEqual(region["led3_voltage"][0], 0.5047058824, places=6)
            self.assertAlmostEqual(region["led3_voltage"][1], 2.4976470588, places=6)
            self.assertEqual(os.listdir(output_dir), [])

    def test_single_region_mode_stops_and_binary_localizes(self):
        contract = load_contract(CONTRACT_PATH)
        with tempfile.TemporaryDirectory() as output_dir:
            with contextlib.redirect_stdout(io.StringIO()):
                result = run_campaign(
                    contract=contract,
                    planner_type="tpe",
                    benchmark="R2",
                    budget=40,
                    seed=42,
                    output_dir=output_dir,
                    console_only=True,
                    single_region_search=True,
                )

        self.assertEqual(len(result.discovery_failures), 1)
        self.assertEqual(len(result.localized_regions), 1)
        self.assertLess(result.experiments_executed, 70)
        self.assertLessEqual(result.boundary_experiments, 48)

    def test_skip_localization_limits_bringup_to_discovery_budget(self):
        contract = load_contract(CONTRACT_PATH)
        with tempfile.TemporaryDirectory() as output_dir:
            with contextlib.redirect_stdout(io.StringIO()):
                result = run_campaign(
                    contract=contract,
                    planner_type="tpe",
                    benchmark="R2",
                    budget=4,
                    seed=42,
                    output_dir=output_dir,
                    console_only=True,
                    localize_pin_ranges=False,
                )

        self.assertEqual(result.experiments_executed, 4)
        self.assertEqual(result.localized_regions, [])
        self.assertEqual(result.boundary_experiments, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
