from __future__ import annotations

from decimal import Decimal
from typing import Any

import optuna

from domain import Control, InvalidRequest, SearchDomain, canonical, is_forbidden, number

from .plan_support import PlanCollector, grid_value, step_count

MAX_CANDIDATES = 200


class ManualPlanner:
    """Operator-chosen points (HLD 03 principle 9): validate, keep order, skip executed points.

    The planner never approves anything; every point still goes through Backend safety.
    A candidate matching a forbidden rule is rejected loudly rather than silently dropped.
    """

    name = "manual"

    def propose(self, domain, history, count, seed, config):
        raw = config.get("candidates")
        if not isinstance(raw, list) or not raw or len(raw) > MAX_CANDIDATES:
            raise InvalidRequest(f"manual planner needs candidates: a list of 1-{MAX_CANDIDATES} condition objects")
        parsed = [self._validate(domain, item, index) for index, item in enumerate(raw)]
        collector = PlanCollector(domain, history, count, "MANUAL")
        reasons: list[str] = []
        for index, conditions in enumerate(parsed):
            if collector.offer(conditions):
                reasons.append(f"Operator-chosen candidate {index + 1} of {len(parsed)}")
            if collector.full:
                break
        return collector.proposals(reasons, "operator list exhausted")

    def _validate(self, domain: SearchDomain, item: Any, index: int) -> dict[str, Any]:
        where = f"candidates[{index}]"
        if not isinstance(item, dict):
            raise InvalidRequest(f"{where} must be an object of control values")
        unknown = sorted(str(name) for name in set(item) - set(domain.controls))
        if unknown:
            raise InvalidRequest(f"{where} has unknown controls: {', '.join(unknown)}")
        missing = sorted(set(domain.controls) - set(item))
        if missing:
            raise InvalidRequest(f"{where} is missing controls: {', '.join(missing)}")
        conditions = {name: self._value(control, item[name], f"{where}.{name}")
                      for name, control in domain.controls.items()}
        if is_forbidden(domain, canonical(domain, conditions)):
            raise InvalidRequest(f"{where} matches a forbidden combination")
        return conditions

    @staticmethod
    def _value(control: Control, value: Any, where: str) -> Any:
        dist = control.distribution
        if isinstance(dist, optuna.distributions.CategoricalDistribution):
            if control.kind == "boolean":
                if not isinstance(value, bool):
                    raise InvalidRequest(f"{where} must be true or false")
                return value
            choice = value.strip().lower() if isinstance(value, str) else None
            if choice not in dist.choices:
                raise InvalidRequest(f"{where} must be one of: {', '.join(map(str, dist.choices))}")
            return choice
        amount = number(value, where)
        if not dist.low <= amount <= dist.high:
            raise InvalidRequest(f"{where}={value} is outside {dist.low}..{dist.high}")
        offset = (Decimal(str(amount)) - Decimal(str(dist.low))) / Decimal(str(dist.step))
        index = round(offset)
        if abs(offset - index) > Decimal("1e-6") or not 0 <= index <= step_count(control):
            raise InvalidRequest(f"{where}={value} is not on the step grid (min {dist.low}, step {dist.step})")
        return grid_value(control, int(index))
