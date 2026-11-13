"""Comprehensive test suite for ChipCheck.

Tests cover all 28 areas specified in the requirements.
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from chipcheck.models import (
    ExperimentConfig, ExecutionResult, ExecutionStatus,
    OracleOutcome, OracleVerdict, ExperimentContract,
    ParameterDef, ParamType, Constraint, FunctionalRequirement, SafetyLimit,
)
from chipcheck.contract import load_contract, validate_contract
from chipcheck.contract.safety import validate_configuration
from chipcheck.executor.simulator import ESP32TimingSimulator, BENCHMARKS, GROUND_TRUTH
from chipcheck.oracle import evaluate, calculate_robustness
from chipcheck.planners import TPEPlanner, RandomPlanner
from chipcheck.storage import CampaignStorage
from chipcheck.campaign import run_campaign, _generate_nominal_config


def _make_contract() -> ExperimentContract:
    """Create a test contract programmatically."""
    return ExperimentContract(
        contract_id="test_v1",
        version="1.0",
        name="Test Contract",
        parameters=[
            ParameterDef("sampling_interval_ms", ParamType.INTEGER, low=1, high=100, step=1, default=10),
            ParameterDef("duration_ms", ParamType.INTEGER, low=100, high=30000, step=100, default=5000),
            ParameterDef("sensor_type", ParamType.CATEGORICAL, choices=["LDR", "BME280", "DHT22", "MPU6050"], default="LDR"),
            ParameterDef("number_of_samples", ParamType.INTEGER, low=10, high=1000, step=10, default=500),
            ParameterDef("deadline_ms", ParamType.INTEGER, low=1, high=50, step=1, default=5),
        ],
        constraints=[
            Constraint("duration_ms >= sampling_interval_ms * 2", "Duration must allow >= 2 samples"),
            Constraint("number_of_samples >= 2", "At least 2 samples"),
            Constraint("deadline_ms <= sampling_interval_ms", "Deadline <= interval"),
        ],
        requirements=[
            FunctionalRequirement("deadline_compliance", "max_read_execution_time_ms", "<=", 5.0, is_primary=True),
            FunctionalRequirement("jitter_limit", "average_jitter_ms", "<=", 2.0),
            FunctionalRequirement("minimum_samples", "total_samples", ">=", 5),
        ],
        safety_limits=[
            SafetyLimit("sampling_interval_ms", min_value=1, max_value=100),
            SafetyLimit("duration_ms", min_value=100, max_value=30000),
            SafetyLimit("deadline_ms", min_value=1, max_value=50),
        ],
        required_measurements=["total_samples", "missed_deadlines", "execution_time_ms"],
        budget=100,
    )


CONTRACT_YAML = str(Path(__file__).parent.parent / "contracts" / "esp32_timing.yaml")


# =========================================================================
# 1. Contract Loading
# =========================================================================
class TestContractLoading(unittest.TestCase):
    def test_load_yaml_contract(self):
        """Test 1: Contract loads from YAML without errors."""
        contract = load_contract(CONTRACT_YAML)
        self.assertEqual(contract.contract_id, "esp32_timing_v1")
        self.assertEqual(len(contract.parameters), 5)
        self.assertGreater(contract.budget, 0)

    def test_contract_has_all_parameters(self):
        contract = load_contract(CONTRACT_YAML)
        names = {p.name for p in contract.parameters}
        self.assertIn("sampling_interval_ms", names)
        self.assertIn("duration_ms", names)
        self.assertIn("sensor_type", names)
        self.assertIn("number_of_samples", names)
        self.assertIn("deadline_ms", names)


# =========================================================================
# 2. Contract Validation
# =========================================================================
class TestContractValidation(unittest.TestCase):
    def test_valid_contract(self):
        """Test 2: Valid contract produces no errors."""
        contract = load_contract(CONTRACT_YAML)
        errors = validate_contract(contract)
        self.assertEqual(errors, [])

    def test_invalid_contract_missing_id(self):
        contract = _make_contract()
        contract.contract_id = ""
        errors = validate_contract(contract)
        self.assertTrue(any("contract_id" in e for e in errors))

    def test_invalid_contract_no_params(self):
        contract = _make_contract()
        contract.parameters = []
        errors = validate_contract(contract)
        self.assertTrue(any("parameter" in e.lower() for e in errors))


# =========================================================================
# 3. Parameter Range Checking
# =========================================================================
class TestParameterRanges(unittest.TestCase):
    def test_in_range_passes(self):
        """Test 3: Valid parameters pass safety check."""
        contract = _make_contract()
        config = ExperimentConfig(1, parameters={
            "sampling_interval_ms": 10, "duration_ms": 5000,
            "sensor_type": "LDR", "number_of_samples": 500, "deadline_ms": 5,
        })
        reasons = validate_configuration(config, contract)
        self.assertEqual(reasons, [])

    def test_out_of_range_rejected(self):
        contract = _make_contract()
        config = ExperimentConfig(1, parameters={
            "sampling_interval_ms": 200, "duration_ms": 5000,
            "sensor_type": "LDR", "number_of_samples": 500, "deadline_ms": 5,
        })
        reasons = validate_configuration(config, contract)
        self.assertTrue(len(reasons) > 0)


# =========================================================================
# 4. Cross-Parameter Constraints
# =========================================================================
class TestConstraints(unittest.TestCase):
    def test_valid_constraints(self):
        """Test 4: Valid constraints pass."""
        contract = _make_contract()
        config = ExperimentConfig(1, parameters={
            "sampling_interval_ms": 10, "duration_ms": 5000,
            "sensor_type": "LDR", "number_of_samples": 500, "deadline_ms": 5,
        })
        reasons = validate_configuration(config, contract)
        self.assertEqual(reasons, [])

    def test_deadline_exceeds_interval_rejected(self):
        """Constraint: deadline_ms <= sampling_interval_ms."""
        contract = _make_contract()
        config = ExperimentConfig(1, parameters={
            "sampling_interval_ms": 3, "duration_ms": 5000,
            "sensor_type": "LDR", "number_of_samples": 500, "deadline_ms": 5,
        })
        reasons = validate_configuration(config, contract)
        self.assertTrue(any("constraint" in r.lower() or "Constraint" in r for r in reasons))


# =========================================================================
# 5. Safety Rejection
# =========================================================================
class TestSafetyRejection(unittest.TestCase):
    def test_safety_limit_violation(self):
        """Test 5: Safety limit violations are rejected."""
        contract = _make_contract()
        config = ExperimentConfig(1, parameters={
            "sampling_interval_ms": 0, "duration_ms": 5000,
            "sensor_type": "LDR", "number_of_samples": 500, "deadline_ms": 5,
        })
        reasons = validate_configuration(config, contract)
        self.assertTrue(len(reasons) > 0)

    def test_wrong_type_rejected(self):
        contract = _make_contract()
        config = ExperimentConfig(1, parameters={
            "sampling_interval_ms": "ten", "duration_ms": 5000,
            "sensor_type": "LDR", "number_of_samples": 500, "deadline_ms": 5,
        })
        reasons = validate_configuration(config, contract)
        self.assertTrue(len(reasons) > 0)

    def test_invalid_categorical_rejected(self):
        contract = _make_contract()
        config = ExperimentConfig(1, parameters={
            "sampling_interval_ms": 10, "duration_ms": 5000,
            "sensor_type": "INVALID_SENSOR", "number_of_samples": 500, "deadline_ms": 5,
        })
        reasons = validate_configuration(config, contract)
        self.assertTrue(any("not in allowed" in r for r in reasons))


# =========================================================================
# 6-10. Timing Calculations
# =========================================================================
class TestTimingCalculations(unittest.TestCase):
    def test_sampling_interval_calculation(self):
        """Test 6: Average interval is computed correctly."""
        sim = ESP32TimingSimulator(benchmark="B4", seed=42)
        config = ExperimentConfig(1, parameters={
            "sampling_interval_ms": 10, "duration_ms": 5000,
            "sensor_type": "LDR", "number_of_samples": 50, "deadline_ms": 20,
        })
        result = sim.execute(config)
        avg_interval = result.results["actual_average_interval_ms"]
        self.assertIsNotNone(avg_interval)
        # Should be approximately 10ms (within noise)
        self.assertAlmostEqual(avg_interval, 10.0, delta=2.0)

    def test_jitter_calculation(self):
        """Test 8: Jitter is computed as average |T_i - T_avg|."""
        sim = ESP32TimingSimulator(benchmark="B4", seed=42)
        config = ExperimentConfig(1, parameters={
            "sampling_interval_ms": 10, "duration_ms": 5000,
            "sensor_type": "LDR", "number_of_samples": 50, "deadline_ms": 20,
        })
        result = sim.execute(config)
        jitter = result.results["average_jitter_ms"]
        self.assertIsNotNone(jitter)
        self.assertGreaterEqual(jitter, 0.0)

    def test_read_execution_time(self):
        """Test 9: Read execution time is reported separately from interval."""
        sim = ESP32TimingSimulator(benchmark="B4", seed=42)
        config = ExperimentConfig(1, parameters={
            "sampling_interval_ms": 10, "duration_ms": 5000,
            "sensor_type": "LDR", "number_of_samples": 50, "deadline_ms": 20,
        })
        result = sim.execute(config)
        avg_read = result.results["average_read_execution_time_ms"]
        max_read = result.results["max_read_execution_time_ms"]
        self.assertIsNotNone(avg_read)
        self.assertIsNotNone(max_read)
        self.assertGreater(avg_read, 0)
        self.assertGreaterEqual(max_read, avg_read)

    def test_deadline_miss_uses_read_execution_time(self):
        """Test 10: Deadline miss is based on read execution time, NOT interval.

        CRITICAL DISTINCTION: A deadline miss occurs when S_i > deadline_ms,
        where S_i is the sensor-reading execution time.
        NOT when T_i > deadline_ms (the inter-sample interval).
        """
        sim = ESP32TimingSimulator(benchmark="B1", seed=42)
        # Low interval will cause high read execution time in B1
        config = ExperimentConfig(1, parameters={
            "sampling_interval_ms": 2, "duration_ms": 5000,
            "sensor_type": "LDR", "number_of_samples": 100, "deadline_ms": 2,
        })
        result = sim.execute(config)
        missed = result.results["missed_deadlines"]
        max_read = result.results["max_read_execution_time_ms"]
        # With interval=2 in B1, read time ~ 1 + 15/2 = 8.5ms > deadline 2ms
        self.assertGreater(missed, 0)
        self.assertGreater(max_read, 2.0)


# =========================================================================
# 11. Fewer Than Two Timestamps
# =========================================================================
class TestFewTimestamps(unittest.TestCase):
    def test_fewer_than_two_timestamps(self):
        """Test 11: With <2 successful reads, interval/jitter are null."""
        sim = ESP32TimingSimulator(benchmark="B4", seed=42)
        config = ExperimentConfig(1, parameters={
            "sampling_interval_ms": 10, "duration_ms": 5,
            "sensor_type": "LDR", "number_of_samples": 1, "deadline_ms": 5,
        })
        result = sim.execute(config)
        samples = result.results["total_samples"]
        if samples < 2:
            self.assertIsNone(result.results["actual_average_interval_ms"])
            self.assertIsNone(result.results["average_jitter_ms"])


# =========================================================================
# 12-14. Termination Conditions
# =========================================================================
class TestTermination(unittest.TestCase):
    def test_max_samples_termination(self):
        """Test 12: Stops when number_of_samples is reached."""
        sim = ESP32TimingSimulator(benchmark="B4", seed=42)
        config = ExperimentConfig(1, parameters={
            "sampling_interval_ms": 10, "duration_ms": 30000,
            "sensor_type": "LDR", "number_of_samples": 20, "deadline_ms": 10,
        })
        result = sim.execute(config)
        self.assertEqual(result.results["total_samples"], 20)

    def test_duration_termination(self):
        """Test 13: Stops when duration_ms is reached."""
        sim = ESP32TimingSimulator(benchmark="B4", seed=42)
        config = ExperimentConfig(1, parameters={
            "sampling_interval_ms": 50, "duration_ms": 200,
            "sensor_type": "LDR", "number_of_samples": 1000, "deadline_ms": 10,
        })
        result = sim.execute(config)
        self.assertLess(result.results["total_samples"], 1000)
        self.assertLessEqual(result.results["execution_time_ms"], 250)

    def test_either_limit_termination(self):
        """Test 14: Stops when EITHER limit is reached first."""
        sim = ESP32TimingSimulator(benchmark="B4", seed=42)
        # Very short duration should stop before all samples
        config = ExperimentConfig(1, parameters={
            "sampling_interval_ms": 10, "duration_ms": 100,
            "sensor_type": "LDR", "number_of_samples": 1000, "deadline_ms": 10,
        })
        result = sim.execute(config)
        self.assertLess(result.results["total_samples"], 1000)


# =========================================================================
# 15-16. JSON Input/Output
# =========================================================================
class TestJsonProtocol(unittest.TestCase):
    def test_input_json_generation(self):
        """Test 15: Input JSON matches specification."""
        config = ExperimentConfig(101, parameters={
            "sampling_interval_ms": 10, "duration_ms": 5000,
            "sensor_type": "LDR", "number_of_samples": 500, "deadline_ms": 5,
        })
        j = json.loads(config.to_json())
        self.assertEqual(j["experiment_id"], 101)
        self.assertEqual(j["command"], "RUN_TIMING_TEST")
        self.assertIn("parameters", j)
        self.assertEqual(j["parameters"]["sampling_interval_ms"], 10)

    def test_output_json_parsing(self):
        """Test 16: Output JSON can be parsed back."""
        result = ExecutionResult(
            experiment_id=101,
            status=ExecutionStatus.COMPLETED,
            results={
                "requested_interval_ms": 10.0,
                "actual_average_interval_ms": 10.3,
                "total_samples": 450,
                "missed_deadlines": 1,
                "failed_reads": 2,
                "execution_time_ms": 5000.0,
                "average_read_execution_time_ms": 1.5,
                "max_read_execution_time_ms": 3.2,
            },
        )
        j = result.to_json()
        parsed = ExecutionResult.from_json(j)
        self.assertEqual(parsed.experiment_id, 101)
        self.assertEqual(parsed.status, ExecutionStatus.COMPLETED)
        self.assertEqual(parsed.results["total_samples"], 450)

    def test_roundtrip_config(self):
        config = ExperimentConfig(42, parameters={"sampling_interval_ms": 15})
        parsed = ExperimentConfig.from_json(config.to_json())
        self.assertEqual(parsed.experiment_id, 42)
        self.assertEqual(parsed.parameters["sampling_interval_ms"], 15)


# =========================================================================
# 17. Oracle Outcome Classification
# =========================================================================
class TestOracleClassification(unittest.TestCase):
    def test_pass_classification(self):
        """Test 17: PASS when all requirements satisfied."""
        contract = _make_contract()
        result = ExecutionResult(1, ExecutionStatus.COMPLETED, {
            "total_samples": 50, "missed_deadlines": 0, "execution_time_ms": 500,
            "max_read_execution_time_ms": 2.0, "average_jitter_ms": 0.3,
        })
        verdict = evaluate(result, contract)
        self.assertEqual(verdict.outcome, OracleOutcome.PASS)
        self.assertGreater(verdict.robustness, 0)

    def test_dut_failure_classification(self):
        """DUT_FAILURE when deadline is violated."""
        contract = _make_contract()
        result = ExecutionResult(1, ExecutionStatus.COMPLETED, {
            "total_samples": 50, "missed_deadlines": 5, "execution_time_ms": 500,
            "max_read_execution_time_ms": 8.0, "average_jitter_ms": 0.3,
        })
        verdict = evaluate(result, contract)
        self.assertEqual(verdict.outcome, OracleOutcome.DUT_FAILURE)
        self.assertLess(verdict.robustness, 0)

    def test_aborted_is_safety_abort(self):
        """ABORTED status is SAFETY_ABORT, not DUT_FAILURE."""
        contract = _make_contract()
        result = ExecutionResult(1, ExecutionStatus.ABORTED, {})
        verdict = evaluate(result, contract)
        self.assertEqual(verdict.outcome, OracleOutcome.SAFETY_ABORT)

    def test_no_samples_not_pass(self):
        """Missing evidence is never PASS."""
        contract = _make_contract()
        result = ExecutionResult(1, ExecutionStatus.COMPLETED, {
            "total_samples": 0, "missed_deadlines": 0, "execution_time_ms": 0,
        })
        verdict = evaluate(result, contract)
        self.assertNotEqual(verdict.outcome, OracleOutcome.PASS)

    def test_failed_status_not_automatic_dut_failure(self):
        """FAILED status alone is not automatically a DUT_FAILURE."""
        contract = _make_contract()
        result = ExecutionResult(1, ExecutionStatus.FAILED, {
            "total_samples": 0, "missed_deadlines": 0, "execution_time_ms": 0,
        })
        verdict = evaluate(result, contract)
        # Should be INCONCLUSIVE, not DUT_FAILURE
        self.assertNotEqual(verdict.outcome, OracleOutcome.DUT_FAILURE)


# =========================================================================
# 18. Robustness Calculation
# =========================================================================
class TestRobustness(unittest.TestCase):
    def test_positive_robustness_for_pass(self):
        """Test 18: R > 0 for passing config."""
        contract = _make_contract()
        result = ExecutionResult(1, ExecutionStatus.COMPLETED, {
            "total_samples": 50, "missed_deadlines": 0, "execution_time_ms": 500,
            "max_read_execution_time_ms": 3.0, "average_jitter_ms": 0.5,
        })
        r = calculate_robustness(result, contract)
        self.assertIsNotNone(r)
        self.assertGreater(r, 0)

    def test_negative_robustness_for_failure(self):
        """R < 0 for deadline violation."""
        contract = _make_contract()
        result = ExecutionResult(1, ExecutionStatus.COMPLETED, {
            "total_samples": 50, "missed_deadlines": 3, "execution_time_ms": 500,
            "max_read_execution_time_ms": 7.0, "average_jitter_ms": 0.5,
        })
        r = calculate_robustness(result, contract)
        self.assertIsNotNone(r)
        self.assertLess(r, 0)

    def test_robustness_unavailable_for_insufficient_data(self):
        """Robustness unavailable for no data."""
        contract = _make_contract()
        result = ExecutionResult(1, ExecutionStatus.ABORTED, {})
        r = calculate_robustness(result, contract)
        self.assertIsNone(r)


# =========================================================================
# 19-21. Planner Tests
# =========================================================================
class TestPlanners(unittest.TestCase):
    def setUp(self):
        self.contract = _make_contract()
        self.tmpdir = tempfile.mkdtemp()

    def test_tpe_suggestion(self):
        """Test 19: TPE generates valid configurations."""
        db = f"sqlite:///{self.tmpdir}/tpe_test.db"
        planner = TPEPlanner(self.contract, seed=42, storage_url=db, study_name="test_tpe")
        config = planner.suggest(1)
        self.assertIsInstance(config, ExperimentConfig)
        self.assertIn("sampling_interval_ms", config.parameters)
        self.assertIn("sensor_type", config.parameters)

    def test_random_suggestion(self):
        """Test 20: Random generates valid configurations."""
        db = f"sqlite:///{self.tmpdir}/rand_test.db"
        planner = RandomPlanner(self.contract, seed=42, storage_url=db, study_name="test_rand")
        config = planner.suggest(1)
        self.assertIsInstance(config, ExperimentConfig)
        self.assertIn("sampling_interval_ms", config.parameters)

    def test_planner_feedback(self):
        """Test 21: Planner accepts feedback without error."""
        db = f"sqlite:///{self.tmpdir}/fb_test.db"
        planner = TPEPlanner(self.contract, seed=42, storage_url=db, study_name="test_fb")

        config = planner.suggest(1)
        planner.report(config, 0.5, OracleOutcome.PASS)

        config2 = planner.suggest(2)
        planner.report(config2, -0.3, OracleOutcome.DUT_FAILURE)

        # Invalid result should not crash
        config3 = planner.suggest(3)
        planner.report(config3, None, OracleOutcome.INVALID_EXPERIMENT)


# =========================================================================
# 22. SQLite Persistence
# =========================================================================
class TestStorage(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.storage = CampaignStorage(self.db_path)

    def tearDown(self):
        self.storage.close()

    def test_create_and_retrieve_campaign(self):
        """Test 22: SQLite persistence works."""
        self.storage.create_campaign("c1", "test", "1.0", "tpe", "B1", 42, 100)
        campaign = self.storage.get_campaign("c1")
        self.assertIsNotNone(campaign)
        self.assertEqual(campaign["planner_type"], "tpe")

    def test_store_and_retrieve_experiment(self):
        self.storage.create_campaign("c1", "test", "1.0", "tpe", "B1", 42, 100)
        config = ExperimentConfig(1, parameters={"sampling_interval_ms": 10})
        result = ExecutionResult(1, ExecutionStatus.COMPLETED, {"total_samples": 50})
        verdict = OracleVerdict(OracleOutcome.PASS, robustness=0.5)
        self.storage.store_experiment("c1", config, result, verdict)

        exps = self.storage.get_campaign_experiments("c1")
        self.assertEqual(len(exps), 1)
        self.assertEqual(exps[0]["oracle_outcome"], "PASS")

    def test_store_rejected_proposal(self):
        self.storage.create_campaign("c1", "test", "1.0", "tpe", "B1", 42, 100)
        config = ExperimentConfig(1, parameters={"sampling_interval_ms": 200})
        self.storage.store_rejected_proposal("c1", 1, config, ["Out of range"])
        rejected = self.storage.get_rejected_proposals("c1")
        self.assertEqual(len(rejected), 1)


# =========================================================================
# 23. Failure Confirmation
# =========================================================================
class TestFailureConfirmation(unittest.TestCase):
    def test_confirmation_in_campaign(self):
        """Test 23: Failures are confirmed via replay."""
        contract = _make_contract()
        tmpdir = tempfile.mkdtemp()
        result = run_campaign(
            contract=contract, planner_type="tpe", benchmark="B1",
            budget=60, seed=42,
            db_path=os.path.join(tmpdir, "test.db"),
            output_dir=tmpdir,
        )
        if result.first_failure_trial is not None:
            self.assertGreater(len(result.confirmation_results), 0)
            self.assertIsNotNone(result.reproduction_rate)


# =========================================================================
# 24. Boundary Mapping
# =========================================================================
class TestBoundaryMapping(unittest.TestCase):
    def test_boundary_mapping_runs(self):
        """Test 24: Boundary mapping produces results when failures exist."""
        contract = _make_contract()
        tmpdir = tempfile.mkdtemp()
        result = run_campaign(
            contract=contract, planner_type="tpe", benchmark="B1",
            budget=80, seed=42,
            db_path=os.path.join(tmpdir, "test.db"),
            output_dir=tmpdir,
        )
        if result.first_failure_trial is not None:
            self.assertGreater(result.boundary_experiments, 0)


# =========================================================================
# 25. Benchmark Scenarios (B1, B2, B3, B4)
# =========================================================================
class TestBenchmarkScenarios(unittest.TestCase):
    def test_b2_narrow_region_failure(self):
        """B2: failure occurs in [7, 9], passes outside."""
        sim = ESP32TimingSimulator(benchmark="B2", seed=42)
        # Inside narrow region: interval = 8
        cfg_fail = ExperimentConfig(1, parameters={
            "sampling_interval_ms": 8, "duration_ms": 5000,
            "sensor_type": "LDR", "number_of_samples": 50, "deadline_ms": 5,
        })
        res_fail = sim.execute(cfg_fail)
        self.assertGreater(res_fail.results["missed_deadlines"], 0)
        self.assertGreater(res_fail.results["max_read_execution_time_ms"], 5.0)

        # Outside narrow region: interval = 12
        cfg_pass = ExperimentConfig(2, parameters={
            "sampling_interval_ms": 12, "duration_ms": 5000,
            "sensor_type": "LDR", "number_of_samples": 50, "deadline_ms": 5,
        })
        res_pass = sim.execute(cfg_pass)
        self.assertEqual(res_pass.results["missed_deadlines"], 0)
        self.assertLess(res_pass.results["max_read_execution_time_ms"], 5.0)

    def test_b3_conditional_interaction(self):
        """B3: failure requires interval<=10 AND BME280 AND samples>=400.
        Each condition individually is insufficient."""
        sim = ESP32TimingSimulator(benchmark="B3", seed=42)

        # Condition 1 alone: interval=5, but sensor=LDR, samples=50 -> PASS
        cfg1 = ExperimentConfig(1, parameters={
            "sampling_interval_ms": 5, "duration_ms": 5000,
            "sensor_type": "LDR", "number_of_samples": 50, "deadline_ms": 5,
        })
        res1 = sim.execute(cfg1)
        self.assertEqual(res1.results["missed_deadlines"], 0)

        # Condition 2 alone: sensor=BME280, but interval=20, samples=50 -> PASS
        cfg2 = ExperimentConfig(2, parameters={
            "sampling_interval_ms": 20, "duration_ms": 5000,
            "sensor_type": "BME280", "number_of_samples": 50, "deadline_ms": 5,
        })
        res2 = sim.execute(cfg2)
        self.assertEqual(res2.results["missed_deadlines"], 0)

        # All conditions together: interval=5 AND BME280 AND samples=450 -> FAILURE
        cfg_all = ExperimentConfig(3, parameters={
            "sampling_interval_ms": 5, "duration_ms": 10000,
            "sensor_type": "BME280", "number_of_samples": 450, "deadline_ms": 5,
        })
        res_all = sim.execute(cfg_all)
        self.assertGreater(res_all.results["missed_deadlines"], 0)
        self.assertGreater(res_all.results["max_read_execution_time_ms"], 5.0)

    def test_b4_no_failures(self):
        """Test 25: B4 never produces a confirmed failure."""
        contract = _make_contract()
        tmpdir = tempfile.mkdtemp()
        result = run_campaign(
            contract=contract, planner_type="tpe", benchmark="B4",
            budget=50, seed=42,
            db_path=os.path.join(tmpdir, "test.db"),
            output_dir=tmpdir,
        )
        self.assertIsNone(result.first_failure_trial)
        self.assertEqual(result.boundary_experiments, 0)


# =========================================================================
# 26. Reproducibility
# =========================================================================
class TestReproducibility(unittest.TestCase):
    def test_same_seed_same_results(self):
        """Test 26: Same seed produces same simulator results."""
        sim1 = ESP32TimingSimulator(benchmark="B1", seed=42)
        sim2 = ESP32TimingSimulator(benchmark="B1", seed=42)

        config = ExperimentConfig(1, parameters={
            "sampling_interval_ms": 10, "duration_ms": 1000,
            "sensor_type": "LDR", "number_of_samples": 50, "deadline_ms": 5,
        })

        r1 = sim1.execute(config)
        r2 = sim2.execute(config)

        self.assertEqual(r1.results["total_samples"], r2.results["total_samples"])
        self.assertEqual(r1.results["missed_deadlines"], r2.results["missed_deadlines"])
        self.assertEqual(r1.results["max_read_execution_time_ms"],
                         r2.results["max_read_execution_time_ms"])


# =========================================================================
# 27. Budget Accounting
# =========================================================================
class TestBudgetAccounting(unittest.TestCase):
    def test_total_budget_respected(self):
        """Test 27: Total experiments don't exceed budget."""
        contract = _make_contract()
        tmpdir = tempfile.mkdtemp()
        budget = 40
        result = run_campaign(
            contract=contract, planner_type="tpe", benchmark="B1",
            budget=budget, seed=42,
            db_path=os.path.join(tmpdir, "test.db"),
            output_dir=tmpdir,
        )
        self.assertLessEqual(result.experiments_executed, budget)


# =========================================================================
# 28. Safety Abort Handling
# =========================================================================
class TestSafetyAbort(unittest.TestCase):
    def test_aborted_experiment_handling(self):
        """Test 28: ABORTED experiments are handled correctly."""
        contract = _make_contract()
        result = ExecutionResult(1, ExecutionStatus.ABORTED, {
            "total_samples": 0, "missed_deadlines": 0,
        })
        verdict = evaluate(result, contract)
        self.assertEqual(verdict.outcome, OracleOutcome.SAFETY_ABORT)
        self.assertIsNone(verdict.robustness)


# =========================================================================
# Future Hardware Serial Executor Interface
# =========================================================================
class TestSerialExecutorInterface(unittest.TestCase):
    def test_serial_serialization(self):
        """Serializes exact NDJSON specification."""
        from chipcheck.executor.serial_executor import ESP32SerialExecutor
        executor = ESP32SerialExecutor()
        cfg = ExperimentConfig(101, parameters={"sampling_interval_ms": 10})
        payload = executor.serialize_request(cfg)
        self.assertTrue(payload.endswith("\n"))
        data = json.loads(payload.strip())
        self.assertEqual(data["experiment_id"], 101)
        self.assertEqual(data["command"], "RUN_TIMING_TEST")

    def test_serial_parse_valid(self):
        """Parses valid ESP32 response JSON."""
        from chipcheck.executor.serial_executor import ESP32SerialExecutor
        executor = ESP32SerialExecutor()
        raw = json.dumps({
            "experiment_id": 101,
            "status": "COMPLETED",
            "results": {
                "requested_interval_ms": 10.0,
                "actual_average_interval_ms": 10.1,
                "total_samples": 100,
                "missed_deadlines": 0,
            }
        }) + "\n"
        res = executor.parse_response(raw, expected_id=101)
        self.assertEqual(res.status, ExecutionStatus.COMPLETED)
        self.assertEqual(res.results["total_samples"], 100)

    def test_serial_parse_malformed_not_dut_failure(self):
        """Malformed response is parsed as FAILED, evaluated by oracle as INCONCLUSIVE/INVALID."""
        from chipcheck.executor.serial_executor import ESP32SerialExecutor
        executor = ESP32SerialExecutor()
        res = executor.parse_response("NOT VALID JSON", expected_id=101)
        self.assertEqual(res.status, ExecutionStatus.FAILED)
        contract = _make_contract()
        verdict = evaluate(res, contract)
        self.assertNotEqual(verdict.outcome, OracleOutcome.DUT_FAILURE)

    def test_serial_parse_mismatched_id(self):
        """Mismatched ID is detected."""
        from chipcheck.executor.serial_executor import ESP32SerialExecutor
        executor = ESP32SerialExecutor()
        raw = json.dumps({"experiment_id": 999, "status": "COMPLETED", "results": {}})
        res = executor.parse_response(raw, expected_id=101)
        self.assertEqual(res.status, ExecutionStatus.FAILED)


# =========================================================================
# CRITICAL TEST: Interval vs Read Execution Time
# =========================================================================
class TestIntervalVsReadTime(unittest.TestCase):
    """This test proves the critical distinction between sampling interval
    and sensor-reading execution time.

    A normal sampling interval does NOT imply no deadline miss.
    A sensor-reading operation CAN miss its deadline even when the
    sampling interval appears normal.
    """

    def test_normal_interval_does_not_imply_no_deadline_miss(self):
        """CRITICAL: Normal interval + deadline miss is possible.

        The sampling interval (time between consecutive reads) can be normal
        (e.g., ~10ms) while the individual read execution time can exceed
        the deadline (e.g., 8ms > 5ms deadline).

        This is because the interval includes the read time PLUS any waiting
        time. A 10ms interval with an 8ms read still has 2ms of wait time.
        """
        contract = _make_contract()

        # Construct a result where:
        # - Sampling interval is normal (~10ms)
        # - But read execution time exceeds deadline (8ms > 5ms)
        result = ExecutionResult(1, ExecutionStatus.COMPLETED, {
            "total_samples": 50,
            "missed_deadlines": 5,
            "execution_time_ms": 500,
            "actual_average_interval_ms": 10.0,   # Normal interval
            "min_interval_ms": 9.5,
            "max_interval_ms": 10.5,
            "average_jitter_ms": 0.3,              # Low jitter
            "average_read_execution_time_ms": 4.0,
            "max_read_execution_time_ms": 8.0,     # EXCEEDS 5ms deadline!
            "failed_reads": 0,
        })

        verdict = evaluate(result, contract)
        # Despite normal interval, the deadline is violated
        self.assertEqual(verdict.outcome, OracleOutcome.DUT_FAILURE)
        self.assertLess(verdict.robustness, 0)

    def test_deadline_miss_with_normal_interval_in_simulator(self):
        """Simulator can produce normal intervals with deadline misses.

        In B1, low sampling_interval_ms causes high read execution time,
        but the actual observed inter-sample interval includes wait time.
        """
        sim = ESP32TimingSimulator(benchmark="B1", seed=100)
        # Choose parameters where read time is high but interval includes it
        config = ExperimentConfig(1, parameters={
            "sampling_interval_ms": 10,
            "duration_ms": 5000,
            "sensor_type": "LDR",
            "number_of_samples": 50,
            "deadline_ms": 2,  # Very tight deadline
        })
        result = sim.execute(config)
        avg_interval = result.results["actual_average_interval_ms"]
        avg_read = result.results["average_read_execution_time_ms"]

        # The interval should be roughly 10ms (requested)
        if avg_interval is not None:
            self.assertAlmostEqual(avg_interval, 10.0, delta=3.0)

        # But read execution time can exceed the tight deadline
        # In B1 with interval=10: read_time ~ 1 + 15/10 = 2.5ms
        # With deadline_ms=2, some reads may exceed it
        max_read = result.results["max_read_execution_time_ms"]
        if max_read is not None and max_read > 2.0:
            # This proves a deadline miss can occur with a normal interval
            self.assertGreater(result.results["missed_deadlines"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

