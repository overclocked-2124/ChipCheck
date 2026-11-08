"""Helpers shared by the deterministic planners (fixed_corner, coverage, manual)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import optuna

from activequal.decision.service.domain import (CandidateProposal, Control, EpisodeRecord, SearchDomain, canonical, condition_key,
                    is_forbidden)


def executed_keys(history: list[EpisodeRecord]) -> set[tuple[Any, ...]]:
    """Keys of every point already run, whatever the outcome (INVALID and SAFETY_ABORT included)."""
    return {condition_key(record.conditions) for record in history if record.conditions is not None}


def is_numeric(control: Control) -> bool:
    return isinstance(control.distribution, (optuna.distributions.IntDistribution,
                                             optuna.distributions.FloatDistribution))


def step_count(control: Control) -> int:
    """Number of steps between min and max of a numeric control (values = steps + 1)."""
    dist = control.distribution
    return int(round((dist.high - dist.low) / dist.step))


def grid_value(control: Control, index: int) -> Any:
    """The ``index``-th value of a numeric control's step grid (0 = min, step_count = max)."""
    dist = control.distribution
    if isinstance(dist, optuna.distributions.IntDistribution):
        return dist.low + index * dist.step
    return float(Decimal(str(dist.low)) + index * Decimal(str(dist.step)))  # same grid as domain._finite_values


def discrete_values(control: Control) -> list[Any]:
    """Categorical/boolean values with the nominal first, then the declared order."""
    return [control.nominal] + [v for v in control.distribution.choices if v != control.nominal]


class PlanCollector:
    """Accepts planned points in order, dropping forbidden, executed and duplicate ones."""

    def __init__(self, domain: SearchDomain, history: list[EpisodeRecord], count: int, code: str, *,
                 keep_forbidden: bool = False) -> None:
        self.domain, self.count, self.code = domain, count, code
        self.keep_forbidden = keep_forbidden    # manual: let Backend reject and record it (HLD 03 principle 9)
        self.seen = executed_keys(history)
        self.items: list[dict[str, Any]] = []

    @property
    def full(self) -> bool:
        return len(self.items) >= self.count

    def offer(self, conditions: dict[str, Any]) -> bool:
        pinned = canonical(self.domain, conditions)
        key = condition_key(pinned)
        if self.full or key in self.seen or (not self.keep_forbidden and is_forbidden(self.domain, pinned)):
            return False
        self.seen.add(key)
        self.items.append(pinned)
        return True

    def proposals(self, reasons: list[str], exhausted_note: str) -> list[CandidateProposal]:
        """Build proposals; when fewer than ``count`` came back the reason says the plan ran out."""
        short = len(self.items) < self.count
        note = f" ({exhausted_note}; returning {len(self.items)} of {self.count} requested)" if short else ""
        return [CandidateProposal(f"candidate-{index + 1}", conditions, reasons[index] + note, self.code)
                for index, conditions in enumerate(self.items)]
