from __future__ import annotations

import optuna

from .base import OptunaPlanner


class RandomPlanner(OptunaPlanner):
    name = "random"

    def make_sampler(self, domain, seed, config):
        return optuna.samplers.RandomSampler(seed=seed)

    def reason(self, trained, config):
        return "Uniform random baseline"
