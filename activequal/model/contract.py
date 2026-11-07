"""Contract v2 parsing (HLD 04 §12), independent of any planner library.

This validates the parts of the contract that every service needs: controls with their
ranges, steps and nominal values, ``activeWhen`` dependencies, ``forbidden`` rules, the
campaign budget and the DUT name. Observations, requirements, validity rules and safety
limits are parsed as well. They are mandatory when ``require_oracle`` is set (Backend and
Oracle); Decision only needs the controls and parses leniently.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from activequal.model.errors import InvalidRequest
from activequal.model.predicates import validate_atom, validate_rule
from activequal.model.requirements import (ObservationSpec, RequirementSpec, SafetySpec, ValiditySpec,
                                           parse_observations, parse_requirements, parse_safety,
                                           parse_validity)
from activequal.model.values import number, options

CONTINUOUS = "continuous"
INTEGER_TYPES = {"integer", "duration"}
NUMERIC_TYPES = {CONTINUOUS} | INTEGER_TYPES
MAX_CONTROLS = 12
MAX_MAGNITUDE = 1e15   # numeric control bounds beyond this are not physical quantities
MAX_STEPS = 1e12       # keeps Optuna's decimal arithmetic and the grid logic well inside their limits


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
    unit: str | None = None
    shutdown: float | None = None            # value the control returns to in the safe state
    slew_per_s_max: float | None = None      # maximum rate of change, in control units per second
    bind: tuple[str, str] | None = None      # (adapter target, action); the fixture-specific part

    @property
    def continuous(self) -> bool:
        return self.kind == CONTINUOUS


@dataclass(frozen=True)
class ContractModel:
    dut: str
    controls: dict[str, ControlSpec]
    forbidden: list[dict[str, Any]]
    budget: int
    observations: dict[str, ObservationSpec] | None = None
    requirements: list[RequirementSpec] | None = None
    validity: list[ValiditySpec] | None = None
    safety: SafetySpec | None = None
    plan: Any = None                         # campaign.plan: a name or the phase-plan object (HLD 04 §14)
    setup: dict[str, Any] = field(default_factory=dict)   # dut, firmwareSha256, fixture, fixtureRev


def _parse_control(name: str, spec: Any) -> ControlSpec:
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


def _extras(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    if "unit" in spec:
        if not isinstance(spec["unit"], str) or not spec["unit"].strip() or len(spec["unit"]) > 20:
            raise InvalidRequest(f"{name}.unit must be a short non-empty string")
        extras["unit"] = spec["unit"].strip()
    if "shutdown" in spec:
        extras["shutdown"] = number(spec["shutdown"], f"{name}.shutdown")
    if "slewPerSMax" in spec:
        slew = number(spec["slewPerSMax"], f"{name}.slewPerSMax")
        if slew <= 0:
            raise InvalidRequest(f"{name}.slewPerSMax must be positive")
        extras["slew_per_s_max"] = slew
    if "bind" in spec:
        bind = spec["bind"]
        if (not isinstance(bind, dict) or set(bind) != {"target", "action"}
                or not all(isinstance(bind[key], str) and bind[key].strip() for key in bind)):
            raise InvalidRequest(f"{name}.bind needs a target and an action")
        extras["bind"] = (bind["target"].strip(), bind["action"].strip())
    return extras


def parse_control(name: str, spec: Any) -> ControlSpec:
    control = _parse_control(name, spec)
    extras = _extras(name, spec)
    return replace(control, **extras) if extras else control


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


def parse_contract(contract: Any, require_oracle: bool = False) -> ContractModel:
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
    plan = campaign.get("plan")
    if plan is not None and not isinstance(plan, (str, dict)):
        raise InvalidRequest("contract.campaign.plan must be a name or an object")
    model = ContractModel(name, controls, forbidden, budget, plan=plan, setup=dict(setup))
    oracle_sections = ("observations", "requirements", "safety")
    if not require_oracle and not any(key in contract for key in oracle_sections + ("validity",)):
        return model
    missing = [key for key in oracle_sections if key not in contract]
    if missing:
        raise InvalidRequest(f"contract is missing {', '.join(missing)}")
    observations = parse_observations(contract["observations"], set(controls))
    requirements = parse_requirements(contract["requirements"], observations)
    numeric = {key for key, control in controls.items() if control.minimum is not None}
    validity = parse_validity(contract.get("validity"), observations, numeric)
    tracked = {rule.metric for rule in validity}
    for requirement in requirements:
        if requirement.metric in tracked:   # a requirement on a swept rail would make legal commands fail (HLD 04 §12.1)
            raise InvalidRequest(f"requirement {requirement.id!r} is on {requirement.metric!r}, which tracks a "
                                 "control; use a validity rule instead")
    return ContractModel(name, controls, forbidden, budget, observations, requirements, validity,
                         parse_safety(contract["safety"]), plan, dict(setup))


def pin_inactive(model: ContractModel, conditions: dict[str, Any]) -> dict[str, Any]:
    """Hold every control whose ``activeWhen`` is false at its nominal value (HLD 04 §12.1).

    Dependencies are resolved to a fixed point, so a chain of conditions is handled whatever order
    the controls were declared in.
    """
    from activequal.model.predicates import atom_matches
    result = dict(conditions)
    for _ in range(len(model.controls) + 1):
        changed = False
        for name, control in model.controls.items():
            if control.active_when is not None and not atom_matches(control.active_when, result):
                if result[name] != control.nominal:
                    result[name] = control.nominal
                    changed = True
        if not changed:
            return result
    return result
