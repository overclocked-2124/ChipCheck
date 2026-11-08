"""Candidate safety rules (HLD 03 §7.1, §11.1-11.2; HLD 04 §8, §12.1).

``check_candidate`` is the single rule set used by Backend (authoritative validation) and by the
Controller (re-check before power is applied). It is pure, deterministic and fails closed: any
value it cannot evaluate, and any exception inside a rule, becomes a violation, never approval.
It collects every violation rather than stopping at the first.

Assumptions worth knowing:

* Numeric checks use ``decimal.Decimal(str(x))`` (``Decimal(int)`` for ints), so ``3.31`` is on a
  0.01 grid and ``3.3100000000000005`` is not. There is no float modulo and no rounding tolerance.
* Episode time: ``ramp_time_s`` is the maximum over slew-limited controls (those with
  ``slew_per_s_max``) of ``|value - shutdown| / slew_per_s_max``. The episode must satisfy
  ``ramp_time_s + dwell_s + SHUTDOWN_ALLOWANCE_S <= safety.max_episode_s``. ``dwell_s`` comes from
  the control named ``dwellMs`` (milliseconds unless its unit is ``s``), else 0. A slew-limited
  control without a ``shutdown`` value is unevaluable and rejected.
* ``DURATION_EXCEEDS_MAX`` applies to every control of kind ``duration`` (unit ms or s): its own
  length plus the shutdown allowance must fit in ``max_episode_s``.
* A control with unit ``V`` and a numeric kind must be bound to a target declared in
  ``safety.channels``, otherwise nothing bounds its voltage and it is rejected with
  ``CHANNEL_CAPABILITY_MISSING``. Every bound target (including ``dut``/``mcu``) must be in
  ``fixture_capabilities`` when that argument is given.
* Staleness: when either hash is given the other must be given and equal, otherwise
  ``STALE_CONTRACT``.
* ``previous``: for each slew-limited control the step to the candidate must not exceed
  ``slew_per_s_max * (dwell_s + ramp_time_s)``.
"""

from __future__ import annotations

import decimal
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from activequal.model.contract import ContractModel, ControlSpec, NUMERIC_TYPES
from activequal.model.predicates import atom_matches, rule_matches

VALUE_OUT_OF_RANGE = "VALUE_OUT_OF_RANGE"
OFF_STEP_GRID = "OFF_STEP_GRID"
WRONG_TYPE = "WRONG_TYPE"
UNKNOWN_CONTROL = "UNKNOWN_CONTROL"
MISSING_CONTROL = "MISSING_CONTROL"
NOT_IN_VALUES = "NOT_IN_VALUES"
INACTIVE_CONTROL_NOT_NOMINAL = "INACTIVE_CONTROL_NOT_NOMINAL"
FORBIDDEN_COMBINATION = "FORBIDDEN_COMBINATION"
CHANNEL_VOLTAGE_LIMIT = "CHANNEL_VOLTAGE_LIMIT"
CHANNEL_CAPABILITY_MISSING = "CHANNEL_CAPABILITY_MISSING"
SLEW_OR_RAMP_TOO_LONG = "SLEW_OR_RAMP_TOO_LONG"
DURATION_EXCEEDS_MAX = "DURATION_EXCEEDS_MAX"
EPISODE_TIME_BUDGET = "EPISODE_TIME_BUDGET"
STALE_CONTRACT = "STALE_CONTRACT"
UNEVALUABLE = "UNEVALUABLE"

CODES = frozenset({
    VALUE_OUT_OF_RANGE, OFF_STEP_GRID, WRONG_TYPE, UNKNOWN_CONTROL, MISSING_CONTROL, NOT_IN_VALUES,
    INACTIVE_CONTROL_NOT_NOMINAL, FORBIDDEN_COMBINATION, CHANNEL_VOLTAGE_LIMIT, CHANNEL_CAPABILITY_MISSING,
    SLEW_OR_RAMP_TOO_LONG, DURATION_EXCEEDS_MAX, EPISODE_TIME_BUDGET, STALE_CONTRACT, UNEVALUABLE,
})

SHUTDOWN_ALLOWANCE_S = 0.5
_ALLOWANCE = Decimal("0.5")
_PRECISION = 200


@dataclass(frozen=True)
class Violation:
    code: str
    control: str | None
    message: str


@dataclass(frozen=True)
class SafetyDecision:
    """``approved`` is derived: it is True only when there are no violations."""

    violations: tuple[Violation, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "violations", tuple(self.violations))

    @property
    def approved(self) -> bool:
        return len(self.violations) == 0

    @property
    def codes(self) -> frozenset[str]:
        return frozenset(violation.code for violation in self.violations)


class _Unevaluable(Exception):
    pass


def _r(value: Any) -> str:
    try:
        text = repr(value)
    except Exception:
        return "<unrepresentable>"
    return text if len(text) <= 60 else text[:57] + "..."


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _dec(value: Any) -> Decimal:
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(repr(value))


class _Check:
    def __init__(self, contract: ContractModel, conditions: dict[str, Any]) -> None:
        self.contract = contract
        self.conditions = conditions
        self.violations: list[Violation] = []
        self.bad: set[str] = set()   # controls whose value is missing or has the wrong type

    def add(self, code: str, control: str | None, message: str) -> None:
        self.violations.append(Violation(code, control, message))

    # -- per-control value checks -------------------------------------------------------------

    def check_value(self, name: str, spec: ControlSpec, value: Any) -> None:
        if spec.kind in NUMERIC_TYPES:
            self.check_numeric(name, spec, value)
        elif spec.kind == "boolean":
            if not isinstance(value, bool):
                self.bad.add(name)
                self.add(WRONG_TYPE, name, f"{name} must be true or false, got {_r(value)}")
        elif spec.kind == "categorical":
            if not isinstance(value, str):
                self.bad.add(name)
                self.add(WRONG_TYPE, name, f"{name} must be a string, got {_r(value)}")
            elif spec.values is None or value not in spec.values:
                self.add(NOT_IN_VALUES, name, f"{name} value {_r(value)} is not one of its allowed values")
        else:
            self.bad.add(name)
            self.add(UNEVALUABLE, name, f"{name} has unsupported kind {_r(spec.kind)}")

    def check_numeric(self, name: str, spec: ControlSpec, value: Any) -> None:
        if not _is_number(value):
            self.bad.add(name)
            self.add(WRONG_TYPE, name, f"{name} must be a finite number, got {_r(value)}")
            return
        if spec.minimum is None or spec.maximum is None or spec.step is None:
            self.bad.add(name)
            self.add(UNEVALUABLE, name, f"{name} has no range or step to check against")
            return
        low, high, step, current = _dec(spec.minimum), _dec(spec.maximum), _dec(spec.step), _dec(value)
        if step <= 0:
            self.bad.add(name)
            self.add(UNEVALUABLE, name, f"{name} has a non-positive step")
            return
        if current < low or current > high:
            self.add(VALUE_OUT_OF_RANGE, name, f"{name} value {_r(value)} is outside {_r(spec.minimum)} to "
                                               f"{_r(spec.maximum)}")
            return
        with decimal.localcontext() as context:
            context.prec = _PRECISION
            context.traps[decimal.Inexact] = True
            on_grid = (current - low) % step == 0
        if not on_grid or (spec.kind != "continuous" and current != current.to_integral_value()):
            self.add(OFF_STEP_GRID, name, f"{name} value {_r(value)} is not on the step grid")

    def check_nominal_when_inactive(self, name: str, spec: ControlSpec, value: Any) -> None:
        atom = spec.active_when
        if atom is None:
            return
        if not self.eval_atom(atom):
            if name in self.bad:
                return   # the type violation already rejects this candidate
            if spec.kind in NUMERIC_TYPES:
                same = _dec(value) == _dec(spec.nominal)
            elif spec.kind == "boolean":
                same = value is spec.nominal
            else:
                same = value == spec.nominal
            if not same:
                self.add(INACTIVE_CONTROL_NOT_NOMINAL, name,
                         f"{name} is inactive and must stay at its nominal value {_r(spec.nominal)}")

    def eval_atom(self, atom: dict[str, Any]) -> bool:
        ref = atom["control"]
        if ref not in self.conditions or ref in self.bad:
            raise _Unevaluable(f"predicate refers to {ref}, which has no usable value")
        strict = atom_matches(atom, self.conditions, on_error=False)
        lenient = atom_matches(atom, self.conditions, on_error=True)
        if strict != lenient:
            raise _Unevaluable(f"predicate on {ref} compares unorderable values")
        return strict

    # -- whole-candidate checks ---------------------------------------------------------------

    def check_forbidden(self) -> None:
        for index, rule in enumerate(self.contract.forbidden):
            try:
                refs = [atom["control"] for atom in rule["all"]]
                if any(ref not in self.conditions or ref in self.bad for ref in refs):
                    raise _Unevaluable("rule refers to a control with no usable value")
                if rule_matches(rule, self.conditions, on_error=True):
                    self.add(FORBIDDEN_COMBINATION, None, f"candidate matches forbidden rule {index}")
            except Exception:
                self.add(UNEVALUABLE, None, f"forbidden rule {index} could not be evaluated")

    def check_channels(self, capabilities: frozenset[str] | None) -> None:
        channels = self.contract.safety.channels
        for name, spec in self.contract.controls.items():
            target = spec.bind[0] if spec.bind else None
            if capabilities is not None and target is not None and target not in capabilities:
                self.add(CHANNEL_CAPABILITY_MISSING, name, f"fixture has no {target!r} for {name}")
            # Any numeric control bound to a declared safety channel is held to its voltage limit, whatever
            # its unit says; a missing or odd unit must not switch the check off (fail closed, PRD FR-05).
            if spec.kind not in NUMERIC_TYPES or (spec.unit != "V" and target not in channels):
                continue
            if target not in channels:
                self.add(CHANNEL_CAPABILITY_MISSING, name, f"{name} is a voltage with no declared safety channel")
            elif name not in self.bad and name in self.conditions:
                if _dec(self.conditions[name]) > _dec(channels[target]["maxV"]):
                    self.add(CHANNEL_VOLTAGE_LIMIT, name,
                             f"{name} {_r(self.conditions[name])} V exceeds {target} limit "
                             f"{_r(channels[target]['maxV'])} V")

    def dwell_s(self, unusable: list[str]) -> Decimal:
        """Sum of every duration control (an upper bound when several overlap). A duration in a unit other
        than ms or s cannot be converted, so it makes the time budget unevaluable."""
        total = Decimal(0)
        for name, spec in self.contract.controls.items():
            if spec.kind != "duration":
                continue
            value = self.conditions.get(name)
            if name in self.bad or not _is_number(value) or spec.unit not in ("ms", "s", None):
                unusable.append(name)
                continue
            total += _dec(value) if spec.unit == "s" else _dec(value) / 1000   # no unit: ms, as in the HLD 04 examples
        return total

    def ramp_s(self, unusable: list[str]) -> tuple[Decimal, str | None]:
        worst, worst_name = Decimal(0), None
        for name, spec in self.contract.controls.items():
            if spec.slew_per_s_max is None:
                continue
            value = self.conditions.get(name)
            if (name in self.bad or not _is_number(value) or spec.shutdown is None
                    or spec.slew_per_s_max <= 0):
                unusable.append(name)
                continue
            ramp = abs(_dec(value) - _dec(spec.shutdown)) / _dec(spec.slew_per_s_max)
            if ramp > worst or worst_name is None:
                worst, worst_name = max(worst, ramp), name
        return worst, worst_name

    def check_time(self, previous: dict[str, Any] | None) -> None:
        limit = _dec(self.contract.safety.max_episode_s)
        for name, spec in self.contract.controls.items():
            if spec.kind == "duration" and spec.unit in ("ms", "s") and name not in self.bad:
                value = self.conditions.get(name)
                if _is_number(value):
                    seconds = _dec(value) if spec.unit == "s" else _dec(value) / 1000
                    if seconds + _ALLOWANCE > limit:
                        self.add(DURATION_EXCEEDS_MAX, name,
                                 f"{name} {_r(value)} {spec.unit} plus the shutdown allowance exceeds the "
                                 f"{_r(self.contract.safety.max_episode_s)} s episode limit")
        unusable: list[str] = []
        dwell = self.dwell_s(unusable)
        ramp, ramp_name = self.ramp_s(unusable)
        if unusable:   # the totals below are lower bounds; the candidate is rejected regardless
            self.add(UNEVALUABLE, None, f"episode time cannot be fully evaluated: no usable value or slew "
                                        f"data for {', '.join(unusable)}")
        if ramp + _ALLOWANCE > limit:
            self.add(SLEW_OR_RAMP_TOO_LONG, ramp_name, f"ramp of {ramp:.3f} s plus the shutdown allowance exceeds "
                                                        f"the {_r(self.contract.safety.max_episode_s)} s episode limit")
        if ramp + dwell + _ALLOWANCE > limit:
            self.add(EPISODE_TIME_BUDGET, None, f"ramp {ramp:.3f} s + dwell {dwell:.3f} s + shutdown allowance "
                                                f"exceeds the {_r(self.contract.safety.max_episode_s)} s episode limit")
        if previous is not None:
            self.check_previous(previous, dwell + ramp)

    def check_previous(self, previous: dict[str, Any], window: Decimal) -> None:
        for name, spec in self.contract.controls.items():
            if spec.slew_per_s_max is None or name in self.bad:
                continue
            before, after = previous.get(name), self.conditions.get(name)
            if not _is_number(before) or not _is_number(after):
                self.add(UNEVALUABLE, name, f"previous or candidate value of {name} is not a number")
            elif abs(_dec(after) - _dec(before)) > _dec(spec.slew_per_s_max) * window:
                self.add(SLEW_OR_RAMP_TOO_LONG, name,
                         f"step of {name} from {_r(before)} to {_r(after)} exceeds its slew limit over the "
                         f"{window:.3f} s window")


def _guard(check: _Check, code_control: str | None, action: Any) -> None:
    try:
        action()
    except Exception as exc:  # fail closed: an exception inside a rule is a rejection
        check.add(UNEVALUABLE, code_control, f"rule could not be evaluated ({type(exc).__name__})")


def check_candidate(contract: ContractModel, conditions: Any, *, fixture_capabilities: frozenset[str] | None = None,
                    contract_hash: str | None = None, expected_hash: str | None = None,
                    previous: dict[str, Any] | None = None) -> SafetyDecision:
    """Return every reason the candidate must not run, or an approval when there are none."""
    try:
        if not isinstance(contract, ContractModel) or contract.safety is None:
            return SafetyDecision((Violation(UNEVALUABLE, None, "contract has no safety limits"),))
        if not isinstance(conditions, dict):
            return SafetyDecision((Violation(UNEVALUABLE, None, "conditions must be an object"),))
        check = _Check(contract, conditions)
        _run(check, fixture_capabilities, contract_hash, expected_hash, previous)
        return SafetyDecision(tuple(check.violations))
    except Exception as exc:  # last resort; never raises, never approves
        return SafetyDecision((Violation(UNEVALUABLE, None, f"safety check failed ({type(exc).__name__})"),))


def _run(check: _Check, capabilities: Any, contract_hash: Any, expected_hash: Any, previous: Any) -> None:
    contract, conditions = check.contract, check.conditions
    if contract_hash is not None or expected_hash is not None:
        if not (isinstance(contract_hash, str) and isinstance(expected_hash, str) and contract_hash == expected_hash):
            check.add(STALE_CONTRACT, None, "contract hash does not match the hash the candidate was made for")
    for key in conditions:
        if not isinstance(key, str) or key not in contract.controls:
            check.add(UNKNOWN_CONTROL, key if isinstance(key, str) else None, f"unknown control {_r(key)}")
    for name, spec in contract.controls.items():
        if name not in conditions:
            check.bad.add(name)
            check.add(MISSING_CONTROL, name, f"control {name} is missing")
            continue
        _guard(check, name, lambda: check.check_value(name, spec, conditions[name]))
    for name, spec in contract.controls.items():
        if name in conditions:
            def inactive() -> None:
                try:
                    check.check_nominal_when_inactive(name, spec, conditions[name])
                except _Unevaluable as exc:
                    check.add(UNEVALUABLE, name, f"activeWhen of {name} cannot be evaluated: {exc}")
            _guard(check, name, inactive)
    _guard(check, None, check.check_forbidden)
    if capabilities is not None and not isinstance(capabilities, (frozenset, set)):
        check.add(UNEVALUABLE, None, "fixture capabilities must be a set")
        capabilities = None
    _guard(check, None, lambda: check.check_channels(capabilities))
    if previous is not None and not isinstance(previous, dict):
        check.add(UNEVALUABLE, None, "previous conditions must be an object")
        previous = None
    _guard(check, None, lambda: check.check_time(previous))
