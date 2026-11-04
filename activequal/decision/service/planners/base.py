"""Planner plugin interface and the shared candidate loop.

A planner is a pure function of (domain, history, count, seed, config). It never
approves a candidate or touches an instrument. To add an algorithm, drop a file in
this package and register it in ``planners/__init__.py``.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

import optuna

from domain import (CandidateProposal, EpisodeRecord, SearchDomain, canonical, condition_key,
                    is_forbidden)

optuna.logging.set_verbosity(optuna.logging.WARNING)


class PlannerPlugin(Protocol):
    name: str

    def propose(self, domain: SearchDomain, history: list[EpisodeRecord], count: int, seed: int,
                config: dict[str, Any]) -> list[CandidateProposal]: ...


class OptunaPlanner:
    """Shared loop for planners backed by an Optuna sampler."""

    name = "base"
    # A model-based sampler can keep returning a point that was already executed. When
    # this is set, the remaining slots are filled with random unseen points (and the
    # reason says so) instead of returning too few candidates.
    fallback_to_random = False
    deadline_seconds: float | None = None
    fallback_reason = "Model proposed only already-executed points; random unseen fallback"

    def ask_limit(self, seen_count: int, count: int) -> int:
        return seen_count + max(50, count * 50)

    def make_sampler(self, domain: SearchDomain, seed: int, config: dict[str, Any]) -> optuna.samplers.BaseSampler:
        raise NotImplementedError

    def reason(self, trained: int, config: dict[str, Any]) -> str:
        raise NotImplementedError

    def propose(self, domain: SearchDomain, history: list[EpisodeRecord], count: int, seed: int,
                config: dict[str, Any]) -> list[CandidateProposal]:
        # Advance the seed with the amount of history. A fixed seed would replay the
        # same pseudo-random sequence from index 0 on every stateless call.
        sampler = self.make_sampler(domain, seed + len(history), config)
        study = optuna.create_study(direction="minimize", sampler=sampler)
        seen: set[tuple[Any, ...]] = set()
        trained = 0
        for record in history:
            if record.conditions is None:
                continue
            # Every executed or aborted point is remembered so it is never proposed
            # again; only valid PASS/DUT_FAILURE results train the model.
            seen.add(condition_key(record.conditions))
            if record.outcome in {"PASS", "DUT_FAILURE"}:
                study.add_trial(optuna.trial.create_trial(
                    params=record.conditions, distributions=domain.distributions, value=record.robustness))
                trained += 1

        proposals: list[CandidateProposal] = []
        reason = self.reason(trained, config)
        attempts, limit = 0, self.ask_limit(len(seen), count)
        started = time.monotonic()
        while len(proposals) < count and attempts < limit:
            if self.deadline_seconds is not None and time.monotonic() - started > self.deadline_seconds:
                break
            attempts += 1
            try:
                trial = study.ask(fixed_distributions=domain.distributions)
            except RuntimeError:  # a finite grid is exhausted
                break
            conditions = canonical(domain, trial.params)
            key = condition_key(conditions)
            if key in seen or is_forbidden(domain, conditions):
                continue
            seen.add(key)
            proposals.append(CandidateProposal(f"candidate-{len(proposals) + 1}", conditions, reason))
        if self.fallback_to_random and len(proposals) < count:
            self._fill_random(domain, seen, proposals, count, seed + len(history))
        return proposals

    def _fill_random(self, domain: SearchDomain, seen: set[tuple[Any, ...]],
                     proposals: list[CandidateProposal], count: int, seed: int) -> None:
        study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=seed + 7919))
        attempts, limit = 0, len(seen) + max(50, count * 50)
        while len(proposals) < count and attempts < limit:
            attempts += 1
            conditions = canonical(domain, study.ask(fixed_distributions=domain.distributions).params)
            key = condition_key(conditions)
            if key in seen or is_forbidden(domain, conditions):
                continue
            seen.add(key)
            proposals.append(CandidateProposal(f"candidate-{len(proposals) + 1}", conditions, self.fallback_reason))
