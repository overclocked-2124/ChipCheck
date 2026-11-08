"""Search domain built from a test contract (v2) or the legacy console setup.

Decision only reads what the contract declares. It never learns hidden fault
triggers, and its forbidden-combination filter is a courtesy to avoid wasted
proposals; Backend and Controller remain the authoritative safety checks.
"""

from __future__ import annotations

import math
from decimal import Decimal
from dataclasses import dataclass, field
from typing import Any

import optuna

from activequal.model.contract import CONTINUOUS, ControlSpec, parse_contract
from activequal.model.values import number, options
from activequal.model.errors import InvalidRequest
from activequal.model.predicates import atom_matches, rule_matches

REASON_CODES = ("STARTUP", "MODEL", "FALLBACK", "BASELINE", "MANUAL")  # machine-readable (NFR-08)
OUTCOMES = {"PASS", "DUT_FAILURE", "INVALID_EXPERIMENT", "SAFETY_ABORT"}


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
    reason: str          # human text
    code: str            # one of REASON_CODES


# ------------------------------------------------------------------ contract

def _distribution(spec: ControlSpec) -> optuna.distributions.BaseDistribution:
    if spec.kind == CONTINUOUS:
        return optuna.distributions.FloatDistribution(spec.minimum, spec.maximum, step=spec.step)
    if spec.minimum is not None:
        return optuna.distributions.IntDistribution(int(spec.minimum), int(spec.maximum), step=int(spec.step))
    return optuna.distributions.CategoricalDistribution(list(spec.values))


def _control(spec: ControlSpec) -> Control:
    return Control(spec.name, spec.kind, _distribution(spec), spec.nominal, spec.active_when,
                   continuous=spec.continuous)


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


def domain_from_contract(contract: Any) -> SearchDomain:
    model = parse_contract(contract)
    controls = {name: _control(spec) for name, spec in model.controls.items()}
    return SearchDomain(model.dut, controls, model.forbidden, model.budget,
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

def snap(distribution: Any, value: Any) -> Any:
    """Put a float on its decimal step grid exactly: 3.5300000000000002 becomes 3.53.

    Optuna and the coverage designs compute grid values in binary floating point, and the safety rules check the
    grid in exact decimal, so an unsnapped value is refused as OFF_STEP_GRID and wastes a proposal.
    """
    if (not isinstance(distribution, optuna.distributions.FloatDistribution) or distribution.step is None
            or not isinstance(value, float) or not math.isfinite(value)):
        return value
    step, low = Decimal(str(distribution.step)), Decimal(str(distribution.low))
    index = ((Decimal(repr(value)) - low) / step).to_integral_value()
    return float(min(max(low + index * step, low), Decimal(str(distribution.high))))


def canonical(domain: SearchDomain, conditions: dict[str, Any]) -> dict[str, Any]:
    """Values are snapped onto their step grid, and inactive controls pinned to nominal so equivalent candidates dedupe."""
    result = {name: snap(domain.controls[name].distribution, value) if name in domain.controls else value
              for name, value in conditions.items()}
    for name, control in domain.controls.items():
        atom = control.active_when
        if atom is not None and not atom_matches(atom, result):
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
