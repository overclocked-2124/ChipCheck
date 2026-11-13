"""Campaign orchestrator for ChipCheck.

Performs the complete campaign workflow:
1. Contract loading and validation
2. Campaign initialization
3. Initial exploration
4. Adaptive or random discovery
5. Safety validation
6. Experiment execution
7. Result parsing and oracle evaluation
8. Robustness calculation
9. Storage
10. Failure confirmation
11. Boundary refinement
12. Final reporting

All physical-attempt-equivalent executions count against the budget.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

import optuna
from optuna.samplers import TPESampler

from chipcheck.models import (
    ExperimentContract, ExperimentConfig, ExecutionResult,
    OracleOutcome, OracleVerdict, ExecutionStatus,
)
from chipcheck.contract import load_contract, validate_contract
from chipcheck.contract.safety import validate_configuration
from chipcheck.planners import ExperimentPlanner, TPEPlanner, RandomPlanner
from chipcheck.executor import ExperimentExecutor
from chipcheck.executor.simulator import ESP32TimingSimulator
from chipcheck.executor.raspi_simulator import RaspiPinSimulator
from chipcheck.executor.serial_executor import ESP32SerialExecutor
from chipcheck.oracle import evaluate, calculate_robustness
from chipcheck.storage import CampaignStorage

logger = logging.getLogger(__name__)

optuna.logging.set_verbosity(optuna.logging.WARNING)


class CampaignResult:
    """Results from a campaign run."""

    def __init__(self):
        self.campaign_id: str = ""
        self.planner_type: str = ""
        self.benchmark: str = ""
        self.seed: int = 0
        self.budget: int = 0
        self.experiments_executed: int = 0
        self.valid_observations: int = 0
        self.invalid_attempts: int = 0
        self.inconclusive_attempts: int = 0
        self.rejected_proposals: int = 0
        self.first_failure_trial: Optional[int] = None
        self.experiments_to_first_failure: Optional[int] = None
        self.confirmed_failures: int = 0
        self.best_robustness: Optional[float] = None
        self.total_deadline_misses: int = 0
        self.total_failed_reads: int = 0
        self.reproduction_rate: Optional[float] = None
        self.boundary_experiments: int = 0
        self.boundary_best_abs_robustness: Optional[float] = None
        self.nearest_pass_robustness: Optional[float] = None
        self.nearest_fail_robustness: Optional[float] = None
        self.boundary_localization_error: Optional[float] = None
        self.discovered_boundaries: dict[str, tuple[float, float]] = {}
        self.localized_regions: list[dict[str, tuple[float, float]]] = []
        self.discovery_failures: list[dict] = []
        self.confirmation_results: list[dict] = []
        self.boundary_points: list[dict] = []
        self.status: str = "completed"

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _generate_nominal_config(contract: ExperimentContract, exp_id: int) -> ExperimentConfig:
    """Generate a nominal configuration using default/middle values."""
    params = {}
    for pdef in contract.parameters:
        if pdef.default is not None:
            value = pdef.default
            if pdef.param_type.value == "continuous" and pdef.step:
                value = pdef.low + round((value - pdef.low) / pdef.step) * pdef.step
            params[pdef.name] = value
        elif pdef.param_type.value == "continuous":
            params[pdef.name] = (pdef.low + pdef.high) / 2.0
        elif pdef.param_type.value == "integer":
            params[pdef.name] = int((pdef.low + pdef.high) / 2)
        elif pdef.param_type.value == "boolean":
            params[pdef.name] = False
        elif pdef.param_type.value == "categorical":
            params[pdef.name] = pdef.choices[0] if pdef.choices else None
    return ExperimentConfig(experiment_id=exp_id, parameters=params)


def _generate_initial_configs(
    contract: ExperimentContract,
    count: int,
    seed: int,
    start_id: int = 1,
) -> list[ExperimentConfig]:
    """Generate initial exploration configurations.

    Includes nominal + valid random configurations.
    """
    import random
    rng = random.Random(seed)
    configs = []

    # First: nominal configuration
    nominal = _generate_nominal_config(contract, start_id)
    configs.append(nominal)

    # Remaining: valid random configurations
    for i in range(1, count):
        params = {}
        for pdef in contract.parameters:
            if pdef.condition:
                parent = pdef.condition.get("parent")
                allowed = pdef.condition.get("values", [])
                pval = params.get(parent)
                if pval not in allowed:
                    if pdef.default is not None:
                        params[pdef.name] = pdef.default
                    continue

            if pdef.param_type.value == "continuous":
                if pdef.step:
                    count = int(round((pdef.high - pdef.low) / pdef.step))
                    params[pdef.name] = pdef.low + rng.randint(0, count) * pdef.step
                else:
                    params[pdef.name] = rng.uniform(pdef.low, pdef.high)
            elif pdef.param_type.value == "integer":
                step = int(pdef.step) if pdef.step else 1
                low_int = int(pdef.low)
                high_int = int(pdef.high)
                n_steps = (high_int - low_int) // step
                params[pdef.name] = low_int + rng.randint(0, n_steps) * step
            elif pdef.param_type.value == "boolean":
                params[pdef.name] = rng.choice([True, False])
            elif pdef.param_type.value == "categorical":
                params[pdef.name] = rng.choice(pdef.choices)

        configs.append(ExperimentConfig(
            experiment_id=start_id + i,
            parameters=params,
        ))

    return configs


def run_campaign(
    contract: ExperimentContract,
    planner_type: str = "tpe",
    benchmark: str = "B1",
    budget: int = 100,
    seed: int = 42,
    confirmation_replays: int = 5,
    boundary_budget_fraction: float = 0.15,
    exploration_fraction: float = 0.25,
    db_path: Optional[str] = None,
    output_dir: Optional[str] = None,
    hardware_port: Optional[str] = None,
    console_only: bool = False,
    single_region_search: bool = False,
    localize_pin_ranges: bool = True,
) -> CampaignResult:
    """Run a complete ChipCheck campaign.

    Args:
        contract: Experiment contract.
        planner_type: "tpe" or "random".
        benchmark: Benchmark scenario (B1-B4).
        budget: Total experiment budget (all phases count).
        seed: Random seed for reproducibility.
        confirmation_replays: Number of replays for failure confirmation.
        boundary_budget_fraction: Fraction of budget for boundary mapping.
        exploration_fraction: Fraction for initial exploration (~20-30%).
        db_path: SQLite database path.
        output_dir: Output directory for reports.
    """
    campaign_id = f"{planner_type}_{benchmark}_s{seed}_{uuid.uuid4().hex[:8]}"
    result = CampaignResult()
    result.campaign_id = campaign_id
    result.planner_type = planner_type
    result.benchmark = benchmark
    result.seed = seed
    result.budget = budget

    # Setup output
    if output_dir is None:
        output_dir = "output"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    if db_path is None:
        db_path = ":memory:" if console_only else str(Path(output_dir) / "chipcheck_results.db")

    optuna_db = "memory" if console_only else f"sqlite:///{Path(output_dir) / 'chipcheck_optuna.db'}"

    # Initialize storage
    storage = CampaignStorage(db_path)
    storage.create_campaign(
        campaign_id=campaign_id,
        contract_id=contract.contract_id,
        contract_version=contract.version,
        planner_type=planner_type,
        benchmark=benchmark,
        seed=seed,
        budget=budget,
    )

    # Initialize executor. Physical mode is an explicit serial transaction:
    # send one proposal, wait for its result, then request the next proposal.
    is_raspi_contract = contract.contract_id.startswith("raspi_")
    if hardware_port and not is_raspi_contract:
        raise ValueError("--hardware-port is currently supported only with the Raspberry Pi contract")
    if is_raspi_contract:
        if hardware_port:
            import serial
            device = serial.Serial(hardware_port, 115200, timeout=1)
            executor = ESP32SerialExecutor(
                port=hardware_port, baudrate=115200,
                timeout_seconds=35.0, serial_device=device,
            )
        else:
            executor = RaspiPinSimulator(scenario=benchmark, seed=seed)
    else:
        executor = ESP32TimingSimulator(benchmark=benchmark, seed=seed)

    # Initialize planner
    study_name = f"{planner_type}_{benchmark}_s{seed}_{campaign_id}"
    if planner_type == "tpe":
        planner = TPEPlanner(
            contract=contract, seed=seed,
            storage_url=optuna_db, study_name=study_name,
        )
    else:
        planner = RandomPlanner(
            contract=contract, seed=seed,
            storage_url=optuna_db, study_name=study_name,
        )

    # Budget accounting
    total_used = 0
    exp_id = 1
    trial_index = 0
    discovery_budget = budget
    # Binary pass/fail measurements have no margin to minimize, so the
    # continuous robustness boundary mapper is not meaningful for this domain.
    boundary_budget = (
        0 if "buzzer_working" in contract.required_measurements
        else int(budget * boundary_budget_fraction)
    )
    discovery_budget -= boundary_budget
    exploration_count = max(3, int(budget * exploration_fraction))

    # Track failures for confirmation and boundary
    discovered_failures: list[tuple[ExperimentConfig, OracleVerdict]] = []
    all_verdicts: list[tuple[ExperimentConfig, OracleVerdict]] = []

    # ------------------------------------------------------------------
    # Phase 1: Initial exploration
    # ------------------------------------------------------------------
    logger.info("=== Phase 1: Initial Exploration (%d configs) ===", exploration_count)
    initial_configs = _generate_initial_configs(contract, exploration_count, seed, start_id=exp_id)

    for config in initial_configs:
        if total_used >= discovery_budget:
            break

        # Safety validation
        reasons = validate_configuration(config, contract)
        if reasons:
            storage.store_rejected_proposal(campaign_id, config.experiment_id, config, reasons)
            result.rejected_proposals += 1
            exp_id += 1
            continue

        # Execute
        exec_result = _execute_config(executor, config, contract)
        total_used += 1

        # Oracle evaluation
        verdict = evaluate(exec_result, contract, config=config)
        if "buzzer_working" in contract.required_measurements:
            _print_pin_iteration(config, exec_result, verdict, phase="TEST")

        # Store
        storage.store_experiment(
            campaign_id, config, exec_result, verdict,
            phase="exploration", trial_index=trial_index,
            planner_type=planner_type, benchmark=benchmark, seed=seed,
        )

        # Report to planner
        planner.report(config, verdict.robustness, verdict.outcome)

        # Track
        _track_result(result, verdict, trial_index, config, exec_result)
        all_verdicts.append((config, verdict))
        stop_after_failure = False
        if verdict.outcome == OracleOutcome.DUT_FAILURE:
            discovered_failures.append((config, verdict))
            stop_after_failure = single_region_search

        trial_index += 1
        exp_id += 1
        if stop_after_failure:
            break

    # ------------------------------------------------------------------
    # Phase 2: Adaptive/Random Discovery
    # ------------------------------------------------------------------
    logger.info("=== Phase 2: Discovery (%s) ===", planner_type.upper())
    max_retries = 10  # max consecutive rejected proposals before giving up

    while total_used < discovery_budget and not (single_region_search and discovered_failures):
        config = planner.suggest(exp_id)

        # Safety validation
        reasons = validate_configuration(config, contract)
        retries = 0
        while reasons and retries < max_retries:
            storage.store_rejected_proposal(campaign_id, config.experiment_id, config, reasons)
            result.rejected_proposals += 1
            planner.report(config, None, OracleOutcome.INVALID_EXPERIMENT)
            exp_id += 1
            config = planner.suggest(exp_id)
            reasons = validate_configuration(config, contract)
            retries += 1

        if reasons:
            # Still invalid after retries - skip
            storage.store_rejected_proposal(campaign_id, config.experiment_id, config, reasons)
            result.rejected_proposals += 1
            planner.report(config, None, OracleOutcome.INVALID_EXPERIMENT)
            exp_id += 1
            continue

        # Execute
        exec_result = _execute_config(executor, config, contract)
        total_used += 1

        # Oracle evaluation
        verdict = evaluate(exec_result, contract, config=config)
        if "buzzer_working" in contract.required_measurements:
            _print_pin_iteration(config, exec_result, verdict, phase="TEST")

        # Store
        storage.store_experiment(
            campaign_id, config, exec_result, verdict,
            phase="discovery", trial_index=trial_index,
            planner_type=planner_type, benchmark=benchmark, seed=seed,
        )

        # Report to planner
        planner.report(config, verdict.robustness, verdict.outcome)

        # Track
        _track_result(result, verdict, trial_index, config, exec_result)
        all_verdicts.append((config, verdict))
        stop_after_failure = False
        if verdict.outcome == OracleOutcome.DUT_FAILURE:
            discovered_failures.append((config, verdict))
            stop_after_failure = single_region_search

        trial_index += 1
        exp_id += 1
        if stop_after_failure:
            break

    result.experiments_executed = total_used

    # ------------------------------------------------------------------
    # Phase 3: Failure Confirmation
    # ------------------------------------------------------------------
    if discovered_failures:
        logger.info("=== Phase 3: Failure Confirmation (%d failures) ===",
                     len(discovered_failures))
        # Confirm the first discovered failure
        fail_config, fail_verdict = discovered_failures[0]
        confirmation_count = 0
        failure_reproduced = 0

        for replay_idx in range(confirmation_replays):
            if total_used >= budget:
                break

            replay_config = ExperimentConfig(
                experiment_id=exp_id,
                command=fail_config.command,
                parameters=dict(fail_config.parameters),
            )

            exec_result = _execute_config(executor, replay_config, contract)
            total_used += 1

            verdict = evaluate(exec_result, contract, config=replay_config)
            if "buzzer_working" in contract.required_measurements:
                _print_pin_iteration(replay_config, exec_result, verdict, phase="REPLAY")

            storage.store_experiment(
                campaign_id, replay_config, exec_result, verdict,
                phase="confirmation", trial_index=trial_index,
                planner_type=planner_type, benchmark=benchmark, seed=seed,
            )
            storage.store_confirmation(
                campaign_id, fail_config.experiment_id,
                replay_config.experiment_id, replay_idx, verdict, exec_result,
            )

            confirmation_count += 1
            if verdict.outcome == OracleOutcome.DUT_FAILURE:
                failure_reproduced += 1

            result.confirmation_results.append({
                "replay_index": replay_idx,
                "outcome": verdict.outcome.value,
                "robustness": verdict.robustness,
            })

            trial_index += 1
            exp_id += 1

        if confirmation_count > 0:
            result.reproduction_rate = failure_reproduced / confirmation_count
            result.confirmed_failures = failure_reproduced

    # ------------------------------------------------------------------
    # Phase 4: Boundary Mapping
    # ------------------------------------------------------------------
    if discovered_failures and total_used < budget:
        logger.info("=== Phase 4: Boundary Mapping ===")
        remaining = min(boundary_budget, budget - total_used)

        if remaining > 0:
            _run_boundary_mapping(
                contract=contract,
                executor=executor,
                storage=storage,
                campaign_id=campaign_id,
                all_verdicts=all_verdicts,
                budget=remaining,
                seed=seed,
                planner_type=planner_type,
                benchmark=benchmark,
                result=result,
                start_exp_id=exp_id,
                start_trial=trial_index,
                optuna_db=optuna_db,
            )
            total_used += result.boundary_experiments
    elif not discovered_failures:
        logger.info("No failures discovered — skipping boundary mapping")

    # For binary Raspberry Pi outcomes there is no robustness gradient to
    # minimize. Walk adjacent 8-bit voltage codes around each discovered fail
    # point to find the exact failing interval on each pin.
    pin_localization_tests = 0
    if (localize_pin_ranges and "buzzer_working" in contract.required_measurements
            and discovered_failures):
        logger.info("=== Pin Range Localization ===")
        pin_localization_tests = _localize_pin_failure_regions(
            contract=contract,
            executor=executor,
            storage=storage,
            campaign_id=campaign_id,
            failure_points=discovered_failures,
            result=result,
            start_exp_id=exp_id,
            start_trial=trial_index,
            planner_type=planner_type,
            benchmark=benchmark,
            seed=seed,
            binary_single_region=single_region_search,
        )
        total_used += pin_localization_tests

    result.experiments_executed = total_used
    result.boundary_experiments += pin_localization_tests

    # Finalize
    storage.finish_campaign(campaign_id)
    storage.close()
    planner.close()
    if hardware_port:
        executor.close()

    logger.info("Campaign %s completed: %d experiments, %d failures found",
                campaign_id, total_used, len(discovered_failures))

    return result


def _execute_config(executor: ExperimentExecutor, config: ExperimentConfig,
                    contract: ExperimentContract) -> ExecutionResult:
    """Execute with a domain-specific command while retaining contract params."""
    if contract.contract_id.startswith("raspi_"):
        config.command = "RUN_PIN_TEST"
    return executor.execute(config)


def _print_pin_iteration(config: ExperimentConfig, execution: ExecutionResult,
                         verdict: OracleVerdict, phase: str) -> None:
    """Print only the current pin test and its observed result."""
    values = " ".join(
        f"{name}={float(value):.4f}V"
        for name, value in config.parameters.items()
    )
    buzzer = execution.results.get("buzzer_working")
    observation = (
        "BUZZER WORKING" if buzzer == 1 else
        "BUZZER FAILED" if buzzer == 0 else
        "NO BUZZER RESULT"
    )
    outcome = {
        OracleOutcome.PASS: "PASS",
        OracleOutcome.DUT_FAILURE: "FAIL",
        OracleOutcome.INVALID_EXPERIMENT: "INVALID",
        OracleOutcome.INCONCLUSIVE: "INCONCLUSIVE",
        OracleOutcome.SAFETY_ABORT: "ABORTED",
    }[verdict.outcome]
    print(f"[{phase} {config.experiment_id:04d}] {values} -> {outcome} ({observation})", flush=True)


def _localize_pin_failure_regions(
    contract: ExperimentContract,
    executor: ExperimentExecutor,
    storage: CampaignStorage,
    campaign_id: str,
    failure_points: list[tuple[ExperimentConfig, OracleVerdict]],
    result: CampaignResult,
    start_exp_id: int,
    start_trial: int,
    planner_type: str,
    benchmark: str,
    seed: int,
    binary_single_region: bool = False,
) -> int:
    """Find inclusive failing 8-bit code ranges around discovered failure points.

    For each anchor, hold the other pins fixed and walk one code at a time in
    both directions. The first passing code brackets that pin's fail boundary.
    This makes no monotonicity assumption across disconnected windows.
    """
    stepped_params = [
        p for p in contract.parameters
        if p.param_type.value == "continuous" and p.step is not None
    ]
    if not stepped_params or any(p.step <= 0 for p in stepped_params):
        logger.warning("Pin localization requires stepped continuous parameters")
        return 0

    probe_count = 0
    exp_id = start_exp_id
    trial_index = start_trial

    def run_probe(params: dict[str, Any]) -> OracleOutcome:
        nonlocal exp_id, trial_index, probe_count
        config = ExperimentConfig(experiment_id=exp_id, parameters=dict(params))
        if validate_configuration(config, contract):
            return OracleOutcome.INVALID_EXPERIMENT
        execution = _execute_config(executor, config, contract)
        verdict = evaluate(execution, contract, config=config)
        _print_pin_iteration(config, execution, verdict, phase="BOUNDARY")
        storage.store_experiment(
            campaign_id, config, execution, verdict,
            phase="boundary", trial_index=trial_index,
            planner_type=planner_type, benchmark=benchmark, seed=seed,
        )
        exp_id += 1
        trial_index += 1
        probe_count += 1
        return verdict.outcome

    def already_localized(anchor: dict[str, Any]) -> bool:
        for region in result.localized_regions:
            if all(
                region[p.name][0] <= float(anchor[p.name]) <= region[p.name][1]
                for p in stepped_params
            ):
                return True
        return False

    for anchor_config, _ in failure_points:
        anchor = dict(anchor_config.parameters)
        if already_localized(anchor):
            continue

        region: dict[str, tuple[float, float]] = {}
        complete = True
        for pdef in stepped_params:
            step = float(pdef.step)
            max_code = int(round((pdef.high - pdef.low) / step))
            anchor_code = int(round((float(anchor[pdef.name]) - pdef.low) / step))

            bounds = []
            for direction in (-1, 1):
                last_failing_code = anchor_code
                if binary_single_region:
                    pass_code = 0 if direction < 0 else max_code
                    probe_params = dict(anchor)
                    probe_params[pdef.name] = pdef.low + pass_code * step
                    endpoint_outcome = run_probe(probe_params)
                    if endpoint_outcome == OracleOutcome.DUT_FAILURE:
                        bounds.append(pdef.low + pass_code * step)
                        continue
                    if endpoint_outcome != OracleOutcome.PASS:
                        complete = False
                        break

                    while abs(last_failing_code - pass_code) > 1:
                        code = (last_failing_code + pass_code) // 2
                        probe_params = dict(anchor)
                        probe_params[pdef.name] = pdef.low + code * step
                        outcome = run_probe(probe_params)
                        if outcome == OracleOutcome.DUT_FAILURE:
                            last_failing_code = code
                        elif outcome == OracleOutcome.PASS:
                            pass_code = code
                        else:
                            complete = False
                            break
                    if not complete:
                        break
                    bounds.append(pdef.low + last_failing_code * step)
                else:
                    code = anchor_code + direction
                    while 0 <= code <= max_code:
                        probe_params = dict(anchor)
                        probe_params[pdef.name] = pdef.low + code * step
                        outcome = run_probe(probe_params)
                        if outcome == OracleOutcome.DUT_FAILURE:
                            last_failing_code = code
                            code += direction
                            continue
                        if outcome == OracleOutcome.PASS:
                            # The first passing code brackets this connected slice.
                            bounds.append(pdef.low + last_failing_code * step)
                            break
                        complete = False
                        break
                    else:
                        bounds.append(pdef.low + last_failing_code * step)

                if len(bounds) < (1 if direction == -1 else 2):
                    complete = False
                    break

            if not complete:
                break
            region[pdef.name] = (min(bounds), max(bounds))

        if complete and len(region) == len(stepped_params):
            result.localized_regions.append(region)
            region_id = len(result.localized_regions)
            formatted = ", ".join(
                f"{name}={bounds[0]:.4f}..{bounds[1]:.4f}V"
                for name, bounds in region.items()
            )
            print(f"[RANGE {region_id}] {formatted}", flush=True)

    return probe_count


def _track_result(
    result: CampaignResult,
    verdict: OracleVerdict,
    trial_index: int,
    config: ExperimentConfig,
    exec_result: ExecutionResult,
) -> None:
    """Track running statistics for the campaign result."""
    if verdict.outcome == OracleOutcome.PASS or verdict.outcome == OracleOutcome.DUT_FAILURE:
        result.valid_observations += 1
    elif verdict.outcome == OracleOutcome.INVALID_EXPERIMENT:
        result.invalid_attempts += 1
    elif verdict.outcome == OracleOutcome.INCONCLUSIVE:
        result.inconclusive_attempts += 1

    if verdict.robustness is not None:
        if result.best_robustness is None or verdict.robustness < result.best_robustness:
            result.best_robustness = verdict.robustness

    if verdict.outcome == OracleOutcome.DUT_FAILURE:
        if result.first_failure_trial is None:
            result.first_failure_trial = trial_index
            result.experiments_to_first_failure = trial_index + 1

        result.discovery_failures.append({
            "trial_index": trial_index,
            "experiment_id": config.experiment_id,
            "robustness": verdict.robustness,
            "params": config.parameters,
        })

    # Accumulate measurements
    r = exec_result.results
    result.total_deadline_misses += r.get("missed_deadlines", 0)
    result.total_failed_reads += r.get("failed_reads", 0)


def _run_boundary_mapping(
    contract: ExperimentContract,
    executor: ExperimentExecutor,
    storage: CampaignStorage,
    campaign_id: str,
    all_verdicts: list[tuple[ExperimentConfig, OracleVerdict]],
    budget: int,
    seed: int,
    planner_type: str,
    benchmark: str,
    result: CampaignResult,
    start_exp_id: int,
    start_trial: int,
    optuna_db: str,
) -> None:
    """Run boundary-mapping phase.

    Objective: minimize |R(x)| to find configurations at the pass/fail boundary.
    Seeds with known passing and failing observations.
    """
    boundary_study_name = f"boundary_{campaign_id}"
    try:
        optuna.delete_study(study_name=boundary_study_name, storage=optuna_db)
    except KeyError:
        pass

    sampler = TPESampler(seed=seed + 1000, n_startup_trials=5)
    boundary_study = optuna.create_study(
        study_name=boundary_study_name,
        direction="minimize",
        sampler=sampler,
        storage=optuna_db,
    )

    # Seed with existing observations
    for cfg, verd in all_verdicts:
        if verd.robustness is not None:
            try:
                dist_dict = {}
                for pdef in contract.parameters:
                    if pdef.name in cfg.parameters:
                        if pdef.param_type.value in ("continuous",):
                            dist_dict[pdef.name] = optuna.distributions.FloatDistribution(
                                pdef.low, pdef.high)
                        elif pdef.param_type.value == "integer":
                            step = int(pdef.step) if pdef.step else 1
                            dist_dict[pdef.name] = optuna.distributions.IntDistribution(
                                int(pdef.low), int(pdef.high), step=step)
                        elif pdef.param_type.value == "boolean":
                            dist_dict[pdef.name] = optuna.distributions.CategoricalDistribution(
                                [True, False])
                        elif pdef.param_type.value == "categorical":
                            dist_dict[pdef.name] = optuna.distributions.CategoricalDistribution(
                                pdef.choices)

                # Filter params to only those in distributions
                trial_params = {k: v for k, v in cfg.parameters.items() if k in dist_dict}
                boundary_study.add_trial(
                    optuna.trial.create_trial(
                        params=trial_params,
                        distributions=dist_dict,
                        values=[abs(verd.robustness)],
                    )
                )
            except Exception:
                pass  # Skip invalid seed trials

    exp_id = start_exp_id
    trial_idx = start_trial
    boundary_used = 0
    nearest_pass = None
    nearest_fail = None

    for _ in range(budget):
        trial = boundary_study.ask()
        params: dict[str, Any] = {}

        for pdef in contract.parameters:
            if pdef.condition:
                parent = pdef.condition.get("parent")
                allowed = pdef.condition.get("values", [])
                pval = params.get(parent)
                if pval not in allowed:
                    if pdef.default is not None:
                        params[pdef.name] = pdef.default
                    continue

            if pdef.param_type.value == "continuous":
                params[pdef.name] = trial.suggest_float(pdef.name, pdef.low, pdef.high)
            elif pdef.param_type.value == "integer":
                step = int(pdef.step) if pdef.step else 1
                params[pdef.name] = trial.suggest_int(pdef.name, int(pdef.low), int(pdef.high), step=step)
            elif pdef.param_type.value == "boolean":
                params[pdef.name] = trial.suggest_categorical(pdef.name, [True, False])
            elif pdef.param_type.value == "categorical":
                params[pdef.name] = trial.suggest_categorical(pdef.name, pdef.choices)

        config = ExperimentConfig(experiment_id=exp_id, parameters=params)

        # Safety validation
        reasons = validate_configuration(config, contract)
        if reasons:
            storage.store_rejected_proposal(campaign_id, exp_id, config, reasons)
            boundary_study.tell(trial, state=optuna.trial.TrialState.PRUNED)
            exp_id += 1
            continue

        # Execute
        exec_result = executor.execute(config)
        boundary_used += 1

        verdict = evaluate(exec_result, contract, config=config)

        storage.store_experiment(
            campaign_id, config, exec_result, verdict,
            phase="boundary", trial_index=trial_idx,
            planner_type=planner_type, benchmark=benchmark, seed=seed,
        )
        storage.store_boundary(campaign_id, config, verdict, trial_idx)

        if verdict.robustness is not None:
            boundary_study.tell(trial, values=abs(verdict.robustness))

            result.boundary_points.append({
                "experiment_id": exp_id,
                "robustness": verdict.robustness,
                "abs_robustness": abs(verdict.robustness),
                "outcome": verdict.outcome.value,
                "params": config.parameters,
            })

            # Track nearest pass/fail
            if verdict.outcome == OracleOutcome.PASS:
                if nearest_pass is None or verdict.robustness < nearest_pass:
                    nearest_pass = verdict.robustness
            elif verdict.outcome == OracleOutcome.DUT_FAILURE:
                if nearest_fail is None or verdict.robustness > nearest_fail:
                    nearest_fail = verdict.robustness
        else:
            boundary_study.tell(trial, state=optuna.trial.TrialState.PRUNED)

        trial_idx += 1
        exp_id += 1

    result.boundary_experiments = boundary_used
    if result.boundary_points:
        result.boundary_best_abs_robustness = min(
            bp["abs_robustness"] for bp in result.boundary_points
        )
    result.nearest_pass_robustness = nearest_pass
    result.nearest_fail_robustness = nearest_fail

