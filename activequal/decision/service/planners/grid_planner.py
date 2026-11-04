from __future__ import annotations

import optuna

from domain import InvalidRequest

from .base import OptunaPlanner

MAX_GRID = 10000


class GridPlanner(OptunaPlanner):
    """Baseline for small domains only; refuses to expand huge spaces."""

    name = "grid"

    def make_sampler(self, domain, seed, config):
        total = 1
        for values in domain.grid_values.values():
            total *= len(values)
        if total > MAX_GRID:
            raise InvalidRequest(f"grid baseline exceeds {MAX_GRID} combinations")
        return optuna.samplers.GridSampler(domain.grid_values, seed=seed)

    def reason(self, trained, config):
        return "Grid baseline"
