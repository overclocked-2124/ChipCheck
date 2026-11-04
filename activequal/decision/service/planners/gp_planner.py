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
    fallback_to_random = True
    deadline_seconds = 10.0  # keep below the console route timeout (15 s)
    fallback_reason = "GP proposed only already-executed points; random unseen fallback"

    def ask_limit(self, seen_count, count):
        # Repeated asks rarely change a stuck GP's answer and each costs seconds.
        return 3 * count + 1

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
