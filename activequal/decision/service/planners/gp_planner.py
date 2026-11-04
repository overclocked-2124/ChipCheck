from __future__ import annotations

import warnings

import optuna

from domain import InvalidRequest

from .base import OptunaPlanner


class GPPlanner(OptunaPlanner):
    """Gaussian-process Bayesian optimization on measured robustness.

    Needs the optional dependencies in ``requirements-gp.txt`` (torch, scipy). A
    proposal can take from about 0.1 s to a few seconds with a few dozen points of
    history, which is small next to a physical episode.
    """

    name = "gp"

    def make_sampler(self, domain, seed, config):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return optuna.samplers.GPSampler(seed=seed, n_startup_trials=config["warmupTrials"])
        except ImportError as exc:
            raise InvalidRequest("method gp needs the optional dependencies: pip install -r requirements-gp.txt") from exc

    def reason(self, trained, config):
        if trained >= config["warmupTrials"]:
            return "GP model selected this from prior measured robustness"
        return "Startup coverage before adaptive feedback"
