from __future__ import annotations

import warnings

import optuna

from .base import OptunaPlanner


class TPEPlanner(OptunaPlanner):
    """Multivariate, grouped TPE so voltage, LED and workload interactions are modelled jointly."""

    name = "tpe"

    def make_sampler(self, domain, seed, config):
        with warnings.catch_warnings():  # group and constant_liar are flagged experimental
            warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)
            return optuna.samplers.TPESampler(seed=seed, n_startup_trials=config["warmupTrials"],
                                              multivariate=True, group=True, constant_liar=True)

    def reason(self, trained, config):
        if trained >= config["warmupTrials"]:
            return "TPE selected this from prior measured robustness"
        return "Startup coverage before adaptive feedback"

    def code(self, trained, config):
        return "MODEL" if trained >= config["warmupTrials"] else "STARTUP"
