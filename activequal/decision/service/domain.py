"""Search domain built from a test contract (v2) or the legacy console setup.

Decision only reads what the contract declares. It never learns hidden fault
triggers, and its forbidden-combination filter is a courtesy to avoid wasted
proposals; Backend and Controller remain the authoritative safety checks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import optuna

CONTINUOUS = "continuous"
INTEGER_TYPES = {"integer", "duration"}
MAX_CONTROLS = 12
MAX_MAGNITUDE = 1e15   # numeric control bounds beyond this are not physical quantities
MAX_STEPS = 1e12       # keeps Optuna's decimal arithmetic and the grid logic well inside their limits
OUTCOMES = {"PASS", "DUT_FAILURE", "INVALID_EXPERIMENT", "SAFETY_ABORT"}


class InvalidRequest(ValueError):
    pass


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
class Control:
    name: str
    kind: str                      # continuous | integer | duration | boolean | categorical
    distribution: optuna.distributions.BaseDistribution
    nominal: Any
    active_when: dict[str, Any] | None = None
    continuous: bool = False


@dataclass(frozen=True)
class SearchDomain:
    name: str
    controls: dict[str, Control]
    forbidden: list[dict[str, Any]]
    budget: int
    # Grid baseline needs an explicit finite value list per control.
    grid_values: dict[str, list[Any]] = field(default_factory=dict)

    @property
    def distributions(self) -> dict[str, optuna.distributions.BaseDistribution]:
        return {name: control.distribution for name, control in self.controls.items()}


@dataclass(frozen=True)
class EpisodeRecord:
    outcome: str
    conditions: dict[str, Any] | None
    robustness: float | None


@dataclass(frozen=True)
class CandidateProposal:
    id: str
    conditions: dict[str, Any]
    reason: str


# ---------------------------------------------------------------- predicates

_COMPARATORS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "in": lambda a, b: a in b,
}


def _validate_atom(atom: Any, known: set[str], where: str) -> None:
    if not isinstance(atom, dict) or not isinstance(atom.get("control"), str):
        raise InvalidRequest(f"{where} predicate needs a control name")
    if atom["control"] not in known:
        raise InvalidRequest(f"{where} refers to unknown control {atom['control']!r}")
    ops = [key for key in atom if key in _COMPARATORS]
    if len(ops) != 1 or set(atom) != {"control", ops[0]}:
        raise InvalidRequest(f"{where} predicate needs exactly one comparator")
    if ops[0] == "in" and not isinstance(atom["in"], list):
        raise InvalidRequest(f"{where} 'in' needs a list")


def validate_rule(rule: Any, known: set[str], where: str) -> None:
    if not isinstance(rule, dict) or set(rule) != {"all"} or not isinstance(rule["all"], list) or not rule["all"]:
        raise InvalidRequest(f"{where} must be an object with a non-empty 'all' list")
    for atom in rule["all"]:
        _validate_atom(atom, known, where)


def _atom_matches(atom: dict[str, Any], conditions: dict[str, Any]) -> bool:
    op = next(key for key in atom if key in _COMPARATORS)
    value = conditions[atom["control"]]
    try:
        return bool(_COMPARATORS[op](value, atom[op]))
    except TypeError:
        return False


def rule_matches(rule: dict[str, Any], conditions: dict[str, Any]) -> bool:
    return all(_atom_matches(atom, conditions) for atom in rule["all"])


# ------------------------------------------------------------------ contract

def _control(name: str, spec: Any) -> Control:
    if not isinstance(spec, dict):
        raise InvalidRequest(f"control {name} must be an object")
    kind = spec.get("type")
    if not isinstance(kind, str):
        raise InvalidRequest(f"control {name} needs a type")
    if kind in {CONTINUOUS, "integer", "duration"}:
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
            dist: optuna.distributions.BaseDistribution = optuna.distributions.FloatDistribution(low, high, step=step)
            return Control(name, kind, dist, nominal, spec.get("activeWhen"), continuous=True)
        if any(float(item) != int(item) for item in (low, high, step, nominal)):
            raise InvalidRequest(f"{name} must use whole numbers")
        dist = optuna.distributions.IntDistribution(int(low), int(high), step=int(step))
        return Control(name, kind, dist, int(nominal), spec.get("activeWhen"))
    if kind == "boolean":
        nominal = spec.get("nominal", False)
        if not isinstance(nominal, bool):
            raise InvalidRequest(f"{name}.nominal must be true or false")
        return Control(name, kind, optuna.distributions.CategoricalDistribution([False, True]), nominal,
                       spec.get("activeWhen"))
    if kind == "categorical":
        values = options(spec.get("values"), f"{name}.values")
        choice = str(spec.get("nominal", values[0])).strip().lower()
        if choice not in values:
            raise InvalidRequest(f"{name}.nominal must be one of its values")
        return Control(name, kind, optuna.distributions.CategoricalDistribution(values), choice,
                       spec.get("activeWhen"))
    raise InvalidRequest(f"control {name} has unsupported type {kind!r}")


MAX_GRID_VALUES = 10000


def _finite_values(control: Control) -> list[Any]:
    """Every value of a control, or [] when there are too many to enumerate (grid baseline only).

    The count is computed arithmetically so a huge range never allocates a list.
    """
    dist = control.distribution
    if isinstance(dist, optuna.distributions.CategoricalDistribution):
        return list(dist.choices)
    if isinstance(dist, optuna.distributions.IntDistribution):
        if (dist.high - dist.low) // dist.step + 1 > MAX_GRID_VALUES:
            return []
        return list(range(dist.low, dist.high + 1, dist.step))
    assert isinstance(dist, optuna.distributions.FloatDistribution) and dist.step is not None
    if math.floor((dist.high - dist.low) / dist.step + 1e-9) + 1 > MAX_GRID_VALUES:
        return []
    from decimal import Decimal
    values: list[Any] = []
    current = Decimal(str(dist.low))
    while current <= Decimal(str(dist.high)):
        values.append(float(current))
        current += Decimal(str(dist.step))
    return values


def _check_activation(controls: dict[str, Control]) -> None:
    known = set(controls)
    for name, control in controls.items():
        if control.active_when is None:
            continue
        _validate_atom(control.active_when, known, f"{name}.activeWhen")
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


def domain_from_contract(contract: Any) -> SearchDomain:
    if not isinstance(contract, dict) or contract.get("contractVersion") != 2:
        raise InvalidRequest("contract must be an object with contractVersion 2")
    raw = contract.get("controls")
    if not isinstance(raw, dict) or not raw or len(raw) > MAX_CONTROLS:
        raise InvalidRequest(f"contract.controls must have 1–{MAX_CONTROLS} entries")
    controls = {name: _control(name, spec) for name, spec in raw.items()}
    _check_activation(controls)
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
    return SearchDomain(name, controls, forbidden, budget,
                        {key: _finite_values(control) for key, control in controls.items()})


# -------------------------------------------------------------- legacy setup

def domain_from_setup(setup: Any) -> SearchDomain:
    """Translate the console's wizard payload into the same control model."""
    if not isinstance(setup, dict) or not str(setup.get("name", "")).strip():
        raise InvalidRequest("setup.name is required")
    if str(setup.get("forbiddenCombinations", "")).strip():
        raise InvalidRequest("free-text forbidden combinations cannot be enforced by Decision; use a reviewed structured contract")
    safety = setup.get("safety")
    if not isinstance(safety, dict):
        raise InvalidRequest("setup.safety is required")
    ceiling = number(safety.get("maximumVolts"), "safety.maximumVolts")
    additional = setup.get("additionalRails", [])
    if not isinstance(additional, list) or len(additional) > 1:
        raise InvalidRequest("at most one additional sensor rail is supported")
    controls: dict[str, Control] = {}
    for parameter, rail in [("railVolts", setup.get("rail"))] + [("sensorRailVolts", item) for item in additional]:
        if not isinstance(rail, dict) or not str(rail.get("name", "")).strip():
            raise InvalidRequest(f"{parameter} requires a rail name")
        low = number(rail.get("minimumVolts"), f"{parameter}.minimumVolts")
        high = number(rail.get("maximumVolts"), f"{parameter}.maximumVolts")
        step = number(rail.get("stepVolts"), f"{parameter}.stepVolts")
        if low < 0 or high <= low or step <= 0 or step > high - low:
            raise InvalidRequest(f"{parameter} range or step is invalid")
        if high > ceiling:
            raise InvalidRequest("rail maximum exceeds the declared voltage ceiling")
        controls[parameter] = Control(parameter, CONTINUOUS,
                                      optuna.distributions.FloatDistribution(low, high, step=step),
                                      low, continuous=True)
    for key, field_name in (("redLed", "redLedOptions"), ("greenLed", "greenLedOptions")):
        values = options(setup.get(field_name), field_name, {"on", "off"})
        controls[key] = Control(key, "categorical", optuna.distributions.CategoricalDistribution(values), values[0])
    workloads = options(setup.get("workloadOptions"), "workloadOptions")
    controls["workload"] = Control("workload", "categorical",
                                   optuna.distributions.CategoricalDistribution(workloads), workloads[0])
    budget = setup.get("experimentBudget")
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
        raise InvalidRequest("experimentBudget must be a positive integer")
    return SearchDomain(str(setup["name"]), controls, [], budget,
                        {key: _finite_values(control) for key, control in controls.items()})


# ---------------------------------------------------------------- conditions

def canonical(domain: SearchDomain, conditions: dict[str, Any]) -> dict[str, Any]:
    """Inactive controls are pinned to nominal so equivalent candidates dedupe."""
    result = dict(conditions)
    for name, control in domain.controls.items():
        atom = control.active_when
        if atom is not None and not _atom_matches(atom, result):
            result[name] = control.nominal
    return result


def condition_key(conditions: dict[str, Any]) -> tuple[Any, ...]:
    return tuple((name, round(value, 9) if isinstance(value, float) else value)
                 for name, value in sorted(conditions.items()))


def is_forbidden(domain: SearchDomain, conditions: dict[str, Any]) -> bool:
    return any(rule_matches(rule, conditions) for rule in domain.forbidden)


def parse_history(domain: SearchDomain, history: Any) -> list[EpisodeRecord]:
    if not isinstance(history, list) or len(history) > 10000:
        raise InvalidRequest("history must be a list of at most 10000 results")
    records = []
    for item in history:
        if not isinstance(item, dict):
            raise InvalidRequest("history entries must be objects")
        outcome = item.get("outcome")
        if outcome not in OUTCOMES:
            raise InvalidRequest("history outcome is unsupported")
        conditions = item.get("conditions")
        trainable = outcome in {"PASS", "DUT_FAILURE"}
        if conditions is None and not trainable:
            records.append(EpisodeRecord(outcome, None, None))
            continue
        if not isinstance(conditions, dict) or set(conditions) != set(domain.controls):
            raise InvalidRequest("history needs complete conditions" if trainable
                                 else "history conditions do not match this setup")
        robustness = number(item.get("robustness"), "history.robustness") if trainable else None
        pinned = canonical(domain, conditions)
        try:  # Optuna validates every value against its distribution.
            optuna.trial.create_trial(params=pinned, distributions=domain.distributions, value=0.0)
        except ValueError as exc:
            raise InvalidRequest("history conditions do not match this setup") from exc
        records.append(EpisodeRecord(outcome, pinned, robustness))
    return records
