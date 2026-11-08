"""The campaign phase plan (HLD 04 §14), read from the campaign's plan and filled with defaults."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from activequal.model.errors import InvalidRequest

ON_CONFIRMED = ("stop", "continue")


@dataclass(frozen=True)
class PlanConfig:
    discovery_budget: int
    verification_budget: int
    init_enabled: bool = False                 # optional coverage phase, off by default (HLD 04 §14)
    init_min_fraction: float = 0.20
    init_max_fraction: float = 0.35
    confirm_max_replays: int = 3
    confirm_if_fails: int = 2
    necessity_probes: bool = True
    on_confirmed: str = "stop"
    consecutive_invalid: int = 3
    max_consecutive_rejections: int = 5

    @property
    def transient_if_passes(self) -> int:
        """Passes among the replays that mark the failure transient (two of three by default)."""
        return self.confirm_max_replays - self.confirm_if_fails + 1

    def init_episodes(self, pairwise_rows: int) -> int:
        """Size of the coverage phase: the larger of the array and the minimum share, capped (HLD 04 §14.1)."""
        if not self.init_enabled:
            return 0
        wanted = max(pairwise_rows, math.ceil(self.init_min_fraction * self.discovery_budget))
        return min(wanted, math.floor(self.init_max_fraction * self.discovery_budget), self.discovery_budget)


def _section(plan: dict[str, Any], key: str) -> dict[str, Any]:
    value = plan.get(key, {})
    if not isinstance(value, dict):
        raise InvalidRequest(f"plan.{key} must be an object")
    return value


def _int(value: Any, name: str, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise InvalidRequest(f"{name} must be an integer of at least {minimum}")
    return value


def plan_config(plan: Any, discovery_budget: int, verification_budget: int) -> PlanConfig:
    """``plan`` is the campaign's stored plan: a name (defaults) or the object of HLD 04 §14."""
    if plan is None or isinstance(plan, str):
        return PlanConfig(discovery_budget, verification_budget)
    if not isinstance(plan, dict):
        raise InvalidRequest("plan must be a name or an object")
    if "forcedEveryN" in _section(plan, "explore"):
        raise InvalidRequest("forced exploration was removed from the plan (HLD 04 §14)")
    init, confirm = _section(plan, "init"), _section(plan, "confirm")
    minimize, stop = _section(plan, "minimize"), _section(plan, "stop")
    config = PlanConfig(
        discovery_budget, verification_budget,
        init_enabled=bool(init.get("enabled", False)),
        init_min_fraction=float(init.get("minFraction", 0.20)), init_max_fraction=float(init.get("maxFraction", 0.35)),
        confirm_max_replays=_int(confirm.get("maxReplays", 3), "confirm.maxReplays", 1),
        confirm_if_fails=_int(confirm.get("confirmIfFails", 2), "confirm.confirmIfFails", 1),
        necessity_probes=bool(minimize.get("necessityProbes", True)),
        on_confirmed=plan.get("onConfirmed", "stop"),
        consecutive_invalid=_int(stop.get("consecutiveInvalid", 3), "stop.consecutiveInvalid", 1))
    if config.on_confirmed not in ON_CONFIRMED:
        raise InvalidRequest(f"onConfirmed must be one of {', '.join(ON_CONFIRMED)}")
    if config.confirm_if_fails > config.confirm_max_replays:
        raise InvalidRequest("confirm.confirmIfFails cannot exceed confirm.maxReplays")
    if not 0 < config.init_min_fraction <= config.init_max_fraction <= 1:
        raise InvalidRequest("init fractions must satisfy 0 < minFraction <= maxFraction <= 1")
    return config
