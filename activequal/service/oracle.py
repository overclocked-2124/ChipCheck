"""The Oracle: classifies one episode's evidence against the approved contract (HLD 03 §15.1,
HLD 04 §13).

Two separate calculations, both pure functions of (contract, requested conditions, evidence):

* Option A, the planner signal: per-requirement margins normalized and clipped to [-1, +1];
  robustness is their minimum over the requirements the episode exercised.
* Option B, the outcome: a guard-banded verdict using each observation's expanded
  uncertainty U (ILAC-G8 style). A value inside the guard band is inconclusive and becomes
  ``INVALID_EXPERIMENT`` with an inconclusive reason.

Missing evidence is never a pass and never a failure: it is ``INVALID_EXPERIMENT``.
The Oracle never sees the DUT's hidden fault trigger; it judges observable behavior only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from activequal.model.contract import ContractModel
from activequal.model.errors import InvalidRequest
from activequal.model.predicates import atom_matches

PASS = "PASS"
DUT_FAILURE = "DUT_FAILURE"
INVALID_EXPERIMENT = "INVALID_EXPERIMENT"
SAFETY_ABORT = "SAFETY_ABORT"

# Stable machine-readable reasons (the outcome says what happened, the code says why).
SAFETY_TRIP = "SAFETY_TRIP"
INSTRUMENT_ERROR = "INSTRUMENT_ERROR"
CONDITIONS_NOT_APPLIED = "CONDITIONS_NOT_APPLIED"
MISSING_OBSERVATION = "MISSING_OBSERVATION"
UNTRUSTWORTHY_OBSERVATION = "UNTRUSTWORTHY_OBSERVATION"
REQUIREMENT_VIOLATED = "REQUIREMENT_VIOLATED"
ALL_REQUIREMENTS_MET = "ALL_REQUIREMENTS_MET"
INCONCLUSIVE = "INCONCLUSIVE"

_PASS, _FAIL, _UNSURE = "pass", "fail", "inconclusive"


@dataclass(frozen=True)
class Evidence:
    """What the Controller submitted for one episode (facts, not an outcome).

    ``observations`` maps an observation name to its reduced value, or to ``None`` when the
    measurement was attempted but is unavailable. A name that is absent was never reported.
    """

    observations: dict[str, float | None]
    safety_trip: str | None = None
    instrument_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class Verdict:
    outcome: str
    reason_code: str
    reason: str
    margins: dict[str, float] = field(default_factory=dict)   # requirement id -> margin in [-1, 1]
    robustness: float | None = None                            # min margin; None unless PASS or DUT_FAILURE
    violated: tuple[str, ...] = ()                             # requirement ids
    inconclusive: tuple[str, ...] = ()                         # requirement ids inside the guard band

    @property
    def trains_planner(self) -> bool:
        """Only PASS and DUT_FAILURE update the functional model (HLD 03 §5)."""
        return self.outcome in (PASS, DUT_FAILURE)


def _clip(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _usable(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value))


def margin(op: str, x: float, *, limit: float | None, lo: float | None, hi: float | None,
           nominal: float | None) -> float:
    """Option A normalized headroom, clipped to [-1, +1]."""
    if op == "<=":
        return _clip((limit - x) / (limit - nominal))
    if op == ">=":
        return _clip((x - limit) / (nominal - limit))
    if op == "band":
        return _clip(min(x - lo, hi - x) / min(nominal - lo, hi - nominal))
    return 1.0 if x == limit else -1.0


def judge(op: str, x: float, u: float, *, limit: float | None, lo: float | None, hi: float | None) -> str:
    """Option B guard-banded verdict for one requirement.

    ``<=`` passes at or below ``limit - U`` and fails above ``limit + U``; ``>=`` mirrors it and
    ``band`` applies the rule to each bound. ``exact`` passes only on equality and fails once the
    difference exceeds U, so with U = 0 it is a plain equality test.
    """
    if op == "<=":
        return _PASS if x <= limit - u else _FAIL if x > limit + u else _UNSURE
    if op == ">=":
        return _PASS if x >= limit + u else _FAIL if x < limit - u else _UNSURE
    if op == "band":
        if x < lo - u or x > hi + u:
            return _FAIL
        return _PASS if lo + u <= x <= hi - u else _UNSURE
    difference = abs(x - limit)
    return _PASS if difference == 0 else _FAIL if difference > u else _UNSURE


def _invalid(code: str, reason: str) -> Verdict:
    return Verdict(INVALID_EXPERIMENT, code, reason)


def classify(contract: ContractModel, requested: dict[str, Any], evidence: Evidence) -> Verdict:
    """Classify one episode in the order of HLD 03 §15.1."""
    if contract.observations is None or contract.requirements is None or contract.validity is None:
        raise InvalidRequest("the Oracle needs a contract parsed with require_oracle=True")
    if set(requested) != set(contract.controls):
        raise InvalidRequest("requested conditions must name exactly the contract's controls")
    for rule in contract.validity:
        if not _usable(requested[rule.tracks]):
            raise InvalidRequest(f"requested {rule.tracks} must be a finite number")

    # 1. A safety mechanism triggered.
    if evidence.safety_trip:
        return Verdict(SAFETY_ABORT, SAFETY_TRIP, f"safety trip: {evidence.safety_trip}")

    # An instrument or communication error makes every measurement suspect (HLD 04 §6).
    if evidence.instrument_errors:
        return _invalid(INSTRUMENT_ERROR, "instrument error: " + "; ".join(evidence.instrument_errors))

    # Observations this episode must report: required, or required while its predicate holds.
    needed = [obs for obs in contract.observations.values()
              if obs.required or (obs.required_when is not None and atom_matches(obs.required_when, requested))]

    # 2. Were the requested conditions applied and measured within tolerance?
    for rule in contract.validity:
        value = evidence.observations.get(rule.metric)
        if not _usable(value):
            return _invalid(MISSING_OBSERVATION, f"validity measurement {rule.metric} is missing")
        deviation = abs(value - requested[rule.tracks])
        if deviation > rule.tolerance:
            return _invalid(CONDITIONS_NOT_APPLIED,
                            f"{rule.metric} = {value:g} differs from requested {rule.tracks} = "
                            f"{requested[rule.tracks]:g} by {deviation:g} (tolerance {rule.tolerance:g})")

    # 3. Are all required observations present and trustworthy? A gap is remembered, not returned yet:
    #    a requirement that a present, valid observation violates beyond the guard band is still a
    #    DUT failure (HLD 03 §15.1 step 3a), because the missing reading cannot undo it.
    gap: Verdict | None = None
    for obs in needed:
        if obs.name not in evidence.observations or evidence.observations[obs.name] is None:
            gap = gap or _invalid(MISSING_OBSERVATION, f"required observation {obs.name} is missing")
        elif not _usable(evidence.observations[obs.name]):
            gap = gap or _invalid(UNTRUSTWORTHY_OBSERVATION, f"observation {obs.name} is not a finite number")

    # Requirements the episode exercised; others (e.g. latency while idle) stay out of the minimum.
    exercised = {obs.name for obs in needed if _usable(evidence.observations.get(obs.name))}
    margins: dict[str, float] = {}
    violated: list[str] = []
    unsure: list[str] = []
    for req in contract.requirements:
        if req.metric not in exercised:
            continue
        x = float(evidence.observations[req.metric])
        u = contract.observations[req.metric].uncertainty
        margins[req.id] = margin(req.op, x, limit=req.limit, lo=req.lo, hi=req.hi, nominal=req.nominal)
        verdict = judge(req.op, x, u, limit=req.limit, lo=req.lo, hi=req.hi)
        if verdict == _FAIL:
            violated.append(req.id)
        elif verdict == _UNSURE:
            unsure.append(req.id)
    robustness = min(margins.values()) if margins else None

    # 4. A reviewed requirement was violated beyond the guard band.
    if violated:
        note = f" ({gap.reason}; the failure stands without it)" if gap else ""
        return Verdict(DUT_FAILURE, REQUIREMENT_VIOLATED, "requirement violated: " + ", ".join(violated) + note,
                       margins, robustness, tuple(violated), tuple(unsure))
    if gap is not None:
        return gap
    # 6. Inside the guard band: neither a pass nor a failure.
    if unsure:
        return Verdict(INVALID_EXPERIMENT, INCONCLUSIVE,
                       "inconclusive within the guard band: " + ", ".join(unsure), margins, None, (), tuple(unsure))
    # 5. Everything held. A contract whose only exercised requirements are none still passes only if
    #    at least one requirement was evaluated; an episode that checked nothing proves nothing.
    if not margins:
        return _invalid(INCONCLUSIVE, "no requirement was exercised by this episode")
    return Verdict(PASS, ALL_REQUIREMENTS_MET, "all exercised requirements met", margins, robustness)
