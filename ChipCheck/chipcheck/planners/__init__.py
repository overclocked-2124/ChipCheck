"""Experiment planners for ChipCheck.

Provides a common planner interface with TPE (adaptive) and Random (baseline)
implementations using Optuna.

The planner reads parameter definitions from the contract.
It does NOT hardcode ESP32 or LDR assumptions.
It does NOT know the simulator's internal failure equations.

TPE (Tree-structured Parzen Estimator) uses density estimation to guide
sampling. It is NOT a custom uncertainty-aware hybrid acquisition algorithm.
It does NOT explicitly estimate calibrated failure probabilities,
predictive uncertainty, or novelty.

Startup-trial requirements: TPE needs ~10-20 random trials before its
density estimates become useful. With small datasets, proposals are
essentially random.
"""

from __future__ import annotations

import abc
import logging
from typing import Any, Optional

import optuna
from optuna.samplers import TPESampler, RandomSampler

from chipcheck.models import (
    ExperimentContract, ExperimentConfig, ParamType, OracleOutcome,
)

logger = logging.getLogger(__name__)

# Suppress Optuna's verbose logging
optuna.logging.set_verbosity(optuna.logging.WARNING)


class ExperimentPlanner(abc.ABC):
    """Abstract experiment planner interface."""

    @abc.abstractmethod
    def suggest(self, experiment_id: int) -> ExperimentConfig:
        """Generate a candidate experiment configuration."""
        ...

    @abc.abstractmethod
    def report(self, config: ExperimentConfig, robustness: Optional[float],
               outcome: OracleOutcome) -> None:
        """Report the result of an executed experiment back to the planner.

        Invalid or inconclusive measurements are NOT trained on as if they
        were valid functional outcomes.
        """
        ...

    @abc.abstractmethod
    def get_name(self) -> str:
        """Return the planner's name."""
        ...

    def close(self) -> None:
        """Release Optuna's SQLite connection, especially before temp cleanup."""
        storage = getattr(getattr(self, "study", None), "_storage", None)
        seen = set()
        while storage is not None and id(storage) not in seen:
            seen.add(id(storage))
            remove_session = getattr(storage, "remove_session", None)
            if callable(remove_session):
                remove_session()
            engine = getattr(storage, "engine", None)
            if engine is not None:
                engine.dispose()
            storage = getattr(storage, "_backend", None)

    def _add_external_trial(
        self, config: ExperimentConfig, robustness: Optional[float], outcome: OracleOutcome
    ) -> None:
        dist_dict = {}
        for pdef in self.contract.parameters:
            if pdef.name in config.parameters:
                if pdef.param_type == ParamType.CONTINUOUS and pdef.step:
                    n_steps = round((pdef.high - pdef.low) / pdef.step)
                    dist_dict[pdef.name] = optuna.distributions.IntDistribution(0, n_steps)
                elif pdef.param_type == ParamType.CONTINUOUS:
                    dist_dict[pdef.name] = optuna.distributions.FloatDistribution(pdef.low, pdef.high)
                elif pdef.param_type == ParamType.INTEGER:
                    step = int(pdef.step) if pdef.step else 1
                    dist_dict[pdef.name] = optuna.distributions.IntDistribution(
                        int(pdef.low), int(pdef.high), step=step
                    )
                elif pdef.param_type == ParamType.BOOLEAN:
                    dist_dict[pdef.name] = optuna.distributions.CategoricalDistribution([True, False])
                elif pdef.param_type == ParamType.CATEGORICAL:
                    dist_dict[pdef.name] = optuna.distributions.CategoricalDistribution(pdef.choices)

        trial_params = {}
        for pdef in self.contract.parameters:
            if pdef.name not in config.parameters or pdef.name not in dist_dict:
                continue
            value = config.parameters[pdef.name]
            if pdef.param_type == ParamType.CONTINUOUS and pdef.step:
                value = int(round((value - pdef.low) / pdef.step))
            trial_params[pdef.name] = value
        is_valid = (
            outcome not in (
                OracleOutcome.INVALID_EXPERIMENT,
                OracleOutcome.INCONCLUSIVE,
                OracleOutcome.SAFETY_ABORT,
            )
            and robustness is not None
        )
        state = optuna.trial.TrialState.COMPLETE if is_valid else optuna.trial.TrialState.PRUNED
        values = [robustness] if is_valid else None
        try:
            trial = optuna.trial.create_trial(
                params=trial_params,
                distributions=dist_dict,
                values=values,
                state=state,
            )
            self.study.add_trial(trial)
        except Exception as e:
            logger.debug("Could not add external trial: %s", e)


def _suggest_from_trial(
    trial: optuna.Trial,
    contract: ExperimentContract,
    params_out: dict[str, Any],
) -> None:
    """Use an Optuna trial to suggest parameter values from the contract."""
    for pdef in contract.parameters:
        # Handle conditional parameters
        if pdef.condition:
            parent_name = pdef.condition.get("parent")
            allowed_values = pdef.condition.get("values", [])
            parent_val = params_out.get(parent_name)
            if parent_val not in allowed_values:
                # Conditional parameter not active; use default or skip
                if pdef.default is not None:
                    params_out[pdef.name] = pdef.default
                continue

        if pdef.param_type == ParamType.CONTINUOUS:
            if pdef.step:
                n_steps = round((pdef.high - pdef.low) / pdef.step)
                code = trial.suggest_int(pdef.name, 0, n_steps)
                val = pdef.low + code * pdef.step
            else:
                val = trial.suggest_float(pdef.name, pdef.low, pdef.high)
            params_out[pdef.name] = val

        elif pdef.param_type == ParamType.INTEGER:
            step = int(pdef.step) if pdef.step else 1
            val = trial.suggest_int(pdef.name, int(pdef.low), int(pdef.high), step=step)
            params_out[pdef.name] = val

        elif pdef.param_type == ParamType.BOOLEAN:
            val = trial.suggest_categorical(pdef.name, [True, False])
            params_out[pdef.name] = val

        elif pdef.param_type == ParamType.CATEGORICAL:
            val = trial.suggest_categorical(pdef.name, pdef.choices)
            params_out[pdef.name] = val


class TPEPlanner(ExperimentPlanner):
    """Adaptive planner using Optuna's TPESampler.

    Objective: minimize robustness (seek configurations with low/negative
    robustness to discover failures).

    TPE uses density estimation to guide sampling toward promising regions.
    It needs ~10-20 startup trials before its estimates become useful.
    """

    def __init__(
        self,
        contract: ExperimentContract,
        seed: int = 42,
        storage_url: Optional[str] = None,
        study_name: Optional[str] = None,
        n_startup_trials: int = 15,
    ):
        self.contract = contract
        self.seed = seed
        self.n_startup_trials = n_startup_trials

        sampler = TPESampler(seed=seed, n_startup_trials=n_startup_trials)

        storage = None if storage_url == "memory" else (storage_url or "sqlite:///chipcheck_optuna.db")
        study_name = study_name or f"tpe_discovery_{seed}"

        # Delete existing study if any (for clean runs)
        if storage is not None:
            try:
                optuna.delete_study(study_name=study_name, storage=storage)
            except KeyError:
                pass

        self.study = optuna.create_study(
            study_name=study_name,
            direction="minimize",  # minimize robustness to find failures
            sampler=sampler,
            storage=storage,
        )
        self._pending_trials: dict[int, optuna.Trial] = {}

    def suggest(self, experiment_id: int) -> ExperimentConfig:
        trial = self.study.ask()
        params: dict[str, Any] = {}
        _suggest_from_trial(trial, self.contract, params)
        self._pending_trials[experiment_id] = trial
        return ExperimentConfig(
            experiment_id=experiment_id,
            command="RUN_TIMING_TEST",
            parameters=params,
        )

    def report(self, config: ExperimentConfig, robustness: Optional[float],
               outcome: OracleOutcome) -> None:
        trial = self._pending_trials.pop(config.experiment_id, None)
        if trial is None:
            self._add_external_trial(config, robustness, outcome)
            return

        # Do NOT train on invalid/inconclusive as valid functional outcomes
        if outcome in (OracleOutcome.INVALID_EXPERIMENT, OracleOutcome.INCONCLUSIVE,
                       OracleOutcome.SAFETY_ABORT):
            self.study.tell(trial, state=optuna.trial.TrialState.PRUNED)
            return

        if robustness is None:
            self.study.tell(trial, state=optuna.trial.TrialState.PRUNED)
            return

        self.study.tell(trial, values=robustness)

    def get_name(self) -> str:
        return "TPE"


class RandomPlanner(ExperimentPlanner):
    """Baseline planner using Optuna's RandomSampler.

    Same interface as TPE for fair comparison.
    """

    def __init__(
        self,
        contract: ExperimentContract,
        seed: int = 42,
        storage_url: Optional[str] = None,
        study_name: Optional[str] = None,
    ):
        self.contract = contract
        self.seed = seed

        sampler = RandomSampler(seed=seed)

        storage = None if storage_url == "memory" else (storage_url or "sqlite:///chipcheck_optuna.db")
        study_name = study_name or f"random_discovery_{seed}"

        if storage is not None:
            try:
                optuna.delete_study(study_name=study_name, storage=storage)
            except KeyError:
                pass

        self.study = optuna.create_study(
            study_name=study_name,
            direction="minimize",
            sampler=sampler,
            storage=storage,
        )
        self._pending_trials: dict[int, optuna.Trial] = {}

    def suggest(self, experiment_id: int) -> ExperimentConfig:
        trial = self.study.ask()
        params: dict[str, Any] = {}
        _suggest_from_trial(trial, self.contract, params)
        self._pending_trials[experiment_id] = trial
        return ExperimentConfig(
            experiment_id=experiment_id,
            command="RUN_TIMING_TEST",
            parameters=params,
        )

    def report(self, config: ExperimentConfig, robustness: Optional[float],
               outcome: OracleOutcome) -> None:
        trial = self._pending_trials.pop(config.experiment_id, None)
        if trial is None:
            self._add_external_trial(config, robustness, outcome)
            return

        if outcome in (OracleOutcome.INVALID_EXPERIMENT, OracleOutcome.INCONCLUSIVE,
                       OracleOutcome.SAFETY_ABORT):
            self.study.tell(trial, state=optuna.trial.TrialState.PRUNED)
            return

        if robustness is None:
            self.study.tell(trial, state=optuna.trial.TrialState.PRUNED)
            return

        self.study.tell(trial, values=robustness)

    def get_name(self) -> str:
        return "Random"

