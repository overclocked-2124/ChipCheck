"""One verification session: confirm, minimize, probe necessity, bracket (HLD 04 §14, HLD 06 §7).

A session starts from one discovery failure (the *trigger*). It is a generator that yields the
next verification candidate and receives that candidate's outcome. It is a pure function of the
results fed to it, so the Agent can rebuild a half-finished session after a restart by replaying
the recorded log (``Backend.session_log``) and never needs private state.

Outcomes fed back are ``PASS``, ``DUT_FAILURE``, anything else for an unusable result
(``INVALID_EXPERIMENT``, ``SAFETY_ABORT``), and ``REJECTED`` for a candidate the safety rules
refused (it spends no budget). Single-episode decisions are used at every step (HLD 06 §7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Generator

from activequal.agent.service.plan import PlanConfig
from activequal.model.contract import ContractModel, ControlSpec, pin_inactive

PASS, FAIL, REJECTED = "PASS", "DUT_FAILURE", "REJECTED"

ROLE_CONFIRM, ROLE_MINIMIZE, ROLE_BRACKET, ROLE_PROBE = "confirm", "minimize", "bracket", "necessity_probe"


@dataclass(frozen=True)
class Request:
    conditions: dict[str, Any]
    role: str
    reason: str


@dataclass
class SessionSummary:
    trigger: dict[str, Any]
    status: str = "unverified"             # confirmed | transient | inconclusive | unverified
    replays: int = 0
    reproductions: int = 0
    minimized: dict[str, Any] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)           # controls returned to nominal, failure persisted
    kept: list[str] = field(default_factory=list)              # controls the failure needs
    necessity: dict[str, str] = field(default_factory=dict)    # discrete control at nominal -> necessary | not_necessary | untested
    intervals: dict[str, dict[str, Any]] = field(default_factory=dict)
    episodes_used: int = 0
    budget_exhausted: bool = False

    @property
    def confirmed(self) -> bool:
        return self.status == "confirmed"

    @property
    def reproduction_rate(self) -> float | None:
        return self.reproductions / self.replays if self.replays else None


Session = Generator[Request, str, SessionSummary]


def _is_discrete(control: ControlSpec) -> bool:
    return control.kind in ("boolean", "categorical")


def grid_value(control: ControlSpec, index: int) -> float | int:
    """The value at ``index`` steps above the minimum, computed exactly so it stays on the grid."""
    value = Decimal(str(control.minimum)) + index * Decimal(str(control.step))
    return int(value) if control.kind in ("integer", "duration") else float(value)


def grid_index(control: ControlSpec, value: float) -> int:
    return int(round((Decimal(str(value)) - Decimal(str(control.minimum))) / Decimal(str(control.step))))


def grid_size(control: ControlSpec) -> int:
    return grid_index(control, control.maximum)


def alternative(control: ControlSpec) -> Any:
    """The first non-nominal value of a discrete control, used for necessity probes."""
    return next(v for v in control.values if v != control.nominal)


def verification_session(model: ContractModel, trigger: dict[str, Any], plan: PlanConfig, budget: int) -> Session:
    summary = SessionSummary(trigger=dict(trigger), minimized=dict(trigger))
    tested: set[str] = set()

    def key(conditions: dict[str, Any]) -> str:
        return repr(sorted(conditions.items()))

    def run(conditions: dict[str, Any], role: str, reason: str) -> Generator[Request, str, str | None]:
        """Ask for one episode. Returns its outcome, REJECTED, or None when the pool is spent."""
        if summary.episodes_used >= budget:
            summary.budget_exhausted = True
            return None
        outcome = yield Request(dict(conditions), role, reason)
        if outcome != REJECTED:
            summary.episodes_used += 1
        tested.add(key(conditions))
        return outcome

    # 1. Confirm by replaying the failing point. Failures confirm, passes mark it transient.
    passes = other = 0
    while summary.replays + other < plan.confirm_max_replays:
        n = summary.replays + other + 1
        outcome = yield from run(trigger, ROLE_CONFIRM, f"confirmation replay {n} of up to {plan.confirm_max_replays}")
        if outcome is None:
            break
        if outcome == FAIL:
            summary.reproductions += 1
            summary.replays += 1
        elif outcome == PASS:
            passes += 1
            summary.replays += 1
        else:
            other += 1           # unusable replay: spends budget, counts toward neither verdict
        if summary.reproductions >= plan.confirm_if_fails:
            summary.status = "confirmed"
            break
        if passes >= plan.transient_if_passes:
            summary.status = "transient"
            return summary
    if summary.status != "confirmed":
        summary.status = "inconclusive" if (summary.replays + other) else "unverified"
        return summary

    current = dict(trigger)
    controls = model.controls

    # 2. Return each non-nominal control to nominal, discrete controls first, keeping changes that preserve the failure.
    order = [n for n, c in controls.items() if _is_discrete(c)] + [n for n, c in controls.items() if not _is_discrete(c)]
    for name in order:
        control = controls[name]
        if current[name] == control.nominal:
            continue
        candidate = pin_inactive(model, {**current, name: control.nominal})
        if candidate == current or key(candidate) in tested:
            continue
        outcome = yield from run(candidate, ROLE_MINIMIZE, f"minimize: {name} back to nominal")
        if outcome is None:
            break
        if outcome == FAIL:
            current = candidate
            summary.removed.append(name)
        elif outcome == PASS:
            summary.kept.append(name)
        else:                       # invalid or refused: says nothing about the failure, so do not claim it is needed
            summary.necessity[name] = "untested"
    summary.minimized = dict(current)

    # 3. A control already at nominal in the original failure cannot be shown necessary by minimizing: flip it once.
    if plan.necessity_probes:
        for name, control in controls.items():
            if not _is_discrete(control) or trigger[name] != control.nominal or current[name] != control.nominal:
                continue
            candidate = pin_inactive(model, {**current, name: alternative(control)})
            if candidate == current or candidate[name] == control.nominal:
                continue            # the control is inactive here: nothing to probe
            outcome = yield from run(candidate, ROLE_PROBE, f"necessity probe: {name} away from nominal")
            if outcome is None:
                break
            summary.necessity[name] = ("not_necessary" if outcome == FAIL
                                       else "necessary" if outcome == PASS else "untested")

    # 4. Bracket numeric controls. A control the failure needs is bracketed by expanding outward to a pass and
    #    bisecting (the ratified plan). A control the planner moved but minimization returned to nominal may still
    #    bound the failure region, which is the interval a researcher wants, so its two range ends are probed
    #    first: failing at an end means the failure continues to the limit (cheap for irrelevant controls),
    #    passing means bisect between the failing nominal and that end.
    numeric = [n for n, c in controls.items() if not _is_discrete(c)]
    plan_order = [(n, False) for n in summary.kept if n in numeric]
    plan_order += [(n, False) for n in numeric if summary.necessity.get(n) == "untested" and current[n] != controls[n].nominal]
    plan_order += [(n, True) for n in summary.removed if n in numeric and trigger[n] != controls[n].nominal]
    # A numeric control the failure was found at nominal (e.g. 3.30 V, inside the PRD §17.2 window) also bounds the
    # region; ends first, so an irrelevant control costs two episodes (HLD 04 §14 "bracket each remaining control").
    planned = {n for n, _ in plan_order}
    plan_order += [(n, True) for n in numeric if n not in planned and trigger[n] == controls[n].nominal
                   and current[n] == controls[n].nominal]
    for name, end_first in plan_order:
        interval = yield from bracket(model, current, name, run, end_first=end_first)
        summary.intervals[name] = interval
        if summary.budget_exhausted:
            break
    return summary


def bracket(model: ContractModel, current: dict[str, Any], name: str, run, *, end_first: bool = False
            ) -> Generator[Request, str, dict[str, Any]]:
    """Find where the failure stops on each side of ``current[name]``; ``current`` itself is known to fail."""
    control = model.controls[name]
    start = grid_index(control, current[name])
    last = grid_size(control)
    sides: dict[str, dict[str, Any]] = {}

    def probe(idx: int, verb: str, label: str) -> Generator[Request, str, str | None]:
        return run(pin_inactive(model, {**current, name: grid_value(control, idx)}), "bracket",
                   f"{verb} {name} {label} side at {grid_value(control, idx)}")

    for label, direction in (("low", -1), ("high", 1)):
        fail_idx, pass_idx, note = start, None, "resolved"
        if end_first:
            end = 0 if direction < 0 else last
            if end == start:
                note = "open: nominal is the control's limit"
            else:
                outcome = yield from probe(end, "end of range", label)
                if outcome == FAIL:
                    fail_idx, note = end, "open: still failing at the control's limit"
                elif outcome == PASS:
                    pass_idx = end
                else:
                    note = ("unresolved: verification budget used up" if outcome is None
                            else "unresolved: unusable result or candidate refused")
        else:
            offset = 1
            while True:                                        # expand outward, doubling the stride
                idx = min(max(start + direction * offset, 0), last)
                if idx == fail_idx:                            # the search space ended while still failing
                    note = "open: still failing at the control's limit"
                    break
                outcome = yield from probe(idx, "bracket", label)
                if outcome is None:
                    note = "unresolved: verification budget used up"
                    break
                if outcome == FAIL:
                    fail_idx = idx
                    offset *= 2
                    continue
                if outcome == PASS:
                    pass_idx = idx
                else:
                    note = "unresolved: unusable result or candidate refused"
                break
        while pass_idx is not None and abs(pass_idx - fail_idx) > 1:       # bisect down to one step
            mid = (fail_idx + pass_idx) // 2
            outcome = yield from probe(mid, "bisect", label)
            if outcome is None:
                note = "unresolved: verification budget used up"
                break
            if outcome == FAIL:
                fail_idx = mid
            elif outcome == PASS:
                pass_idx = mid
            else:
                note = "unresolved: unusable result or candidate refused"
                break
        sides[label] = {"lastFail": grid_value(control, fail_idx),
                        "firstPass": None if pass_idx is None else grid_value(control, pass_idx),
                        "resolution": None if pass_idx is None else abs(pass_idx - fail_idx) * control.step,
                        "note": note}
    return {"low": sides["low"]["lastFail"], "high": sides["high"]["lastFail"], "step": control.step, "sides": sides}
