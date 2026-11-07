"""Contract v2 parsing (HLD 04 §12), independent of any planner library.

This validates the parts of the contract that every service needs: controls with their
ranges, steps and nominal values, ``activeWhen`` dependencies, ``forbidden`` rules, the
campaign budget and the DUT name. The remaining sections (observations, requirements,
validity, safety) are added with the safety-rule library and the Oracle.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from activequal.model.errors import InvalidRequest
from activequal.model.predicates import validate_atom, validate_rule

CONTINUOUS = "continuous"
INTEGER_TYPES = {"integer", "duration"}
NUMERIC_TYPES = {CONTINUOUS} | INTEGER_TYPES
MAX_CONTROLS = 12
MAX_MAGNITUDE = 1e15   # numeric control bounds beyond this are not physical quantities
MAX_STEPS = 1e12       # keeps Optuna's decimal arithmetic and the grid logic well inside their limits


def number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise InvalidRequest(f"{name} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequest(f"{name} must be a number") from exc
    if not math.isfinite(result):
        raise InvalidRequest(f"{name} must be finite")
    return result


def options(value: Any, name: str, allowed: set[str] | None = None) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > 20:
        raise InvalidRequest(f"{name} must have 1–20 options")
    result = [str(item).strip().lower() for item in value]
    if any(not item or len(item) > 60 for item in result) or len(set(result)) != len(result):
        raise InvalidRequest(f"{name} contains empty or duplicate options")
    if allowed and any(item not in allowed for item in result):
        raise InvalidRequest(f"{name} has an unsupported option")
    return result


@dataclass(frozen=True)
class ControlSpec:
    """One validated control. Numeric controls carry ``minimum``/``maximum``/``step``;
    ``boolean`` and ``categorical`` controls carry ``values``."""

    name: str
    kind: str                      # continuous | integer | duration | boolean | categorical
    nominal: Any
    active_when: dict[str, Any] | None = None
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    values: tuple[Any, ...] | None = None

    @property
    def continuous(self) -> bool:
        return self.kind == CONTINUOUS


@dataclass(frozen=True)
class ContractModel:
    dut: str
    controls: dict[str, ControlSpec]
    forbidden: list[dict[str, Any]]
    budget: int


def parse_control(name: str, spec: Any) -> ControlSpec:
    if not isinstance(spec, dict):
        raise InvalidRequest(f"control {name} must be an object")
    kind = spec.get("type")
    if not isinstance(kind, str):
        raise InvalidRequest(f"control {name} needs a type")
    active_when = spec.get("activeWhen")
    if kind in NUMERIC_TYPES:
        low = number(spec.get("min"), f"{name}.min")
        high = number(spec.get("max"), f"{name}.max")
        step = number(spec.get("step"), f"{name}.step")
        nominal = number(spec.get("nominal"), f"{name}.nominal")
        for label, value in (("min", low), ("max", high), ("step", step), ("nominal", nominal)):
            if abs(value) > MAX_MAGNITUDE:
                raise InvalidRequest(f"{name}.{label} is outside the supported range")
        if high <= low or step <= 0 or step > high - low or not low <= nominal <= high:
            raise InvalidRequest(f"{name} range, step or nominal is invalid")
        steps = (high - low) / step
        if steps > MAX_STEPS:
            raise InvalidRequest(f"{name} has more than 10^12 steps")
        tolerance = 1e-6 + 1e-12 * steps
        if abs(steps - round(steps)) > tolerance:  # Optuna would silently lower max otherwise
            raise InvalidRequest(f"{name} range must be a whole number of steps")
        offset = (nominal - low) / step
        if abs(offset - round(offset)) > tolerance:
            raise InvalidRequest(f"{name}.nominal must sit on the step grid")
        if kind == CONTINUOUS:
            return ControlSpec(name, kind, nominal, active_when, low, high, step)
        if any(float(item) != int(item) for item in (low, high, step, nominal)):
            raise InvalidRequest(f"{name} must use whole numbers")
        return ControlSpec(name, kind, int(nominal), active_when, int(low), int(high), int(step))
    if kind == "boolean":
        nominal = spec.get("nominal", False)
        if not isinstance(nominal, bool):
            raise InvalidRequest(f"{name}.nominal must be true or false")
        return ControlSpec(name, kind, nominal, active_when, values=(False, True))
    if kind == "categorical":
        values = options(spec.get("values"), f"{name}.values")
        choice = str(spec.get("nominal", values[0])).strip().lower()
        if choice not in values:
            raise InvalidRequest(f"{name}.nominal must be one of its values")
        return ControlSpec(name, kind, choice, active_when, values=tuple(values))
    raise InvalidRequest(f"control {name} has unsupported type {kind!r}")


def check_activation(controls: dict[str, ControlSpec]) -> None:
    known = set(controls)
    for name, control in controls.items():
        if control.active_when is None:
            continue
        validate_atom(control.active_when, known, f"{name}.activeWhen")
        if control.active_when["control"] == name:
            raise InvalidRequest(f"{name}.activeWhen cannot refer to itself")
    for start in controls:  # cycle check over the activeWhen dependency graph
        seen: set[str] = set()
        current = start
        while (atom := controls[current].active_when) is not None:
            if current in seen:
                raise InvalidRequest("activeWhen dependencies form a cycle")
            seen.add(current)
            current = atom["control"]


def parse_contract(contract: Any) -> ContractModel:
    if not isinstance(contract, dict) or contract.get("contractVersion") != 2:
        raise InvalidRequest("contract must be an object with contractVersion 2")
    raw = contract.get("controls")
    if not isinstance(raw, dict) or not raw or len(raw) > MAX_CONTROLS:
        raise InvalidRequest(f"contract.controls must have 1–{MAX_CONTROLS} entries")
    controls = {name: parse_control(name, spec) for name, spec in raw.items()}
    check_activation(controls)
    forbidden = contract.get("forbidden", [])
    if not isinstance(forbidden, list):
        raise InvalidRequest("contract.forbidden must be a list")
    for index, rule in enumerate(forbidden):
        validate_rule(rule, set(controls), f"forbidden[{index}]")
    campaign = contract.get("campaign")
    budget = campaign.get("budget") if isinstance(campaign, dict) else None
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
        raise InvalidRequest("contract.campaign.budget must be a positive integer")
    setup = contract.get("setup")
    name = str(setup.get("dut", "")).strip() if isinstance(setup, dict) else ""
    if not name:
        raise InvalidRequest("contract.setup.dut is required")
    return ContractModel(name, controls, forbidden, budget)
