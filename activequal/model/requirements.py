"""Observations, requirements, validity rules and safety limits of contract v2 (HLD 04 §12.1).

These are the sections the Backend safety validator and the Oracle consume. They are parsed
separately from the controls so that Decision, which only reads controls, keeps working on
contracts that do not carry them yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from activequal.model.errors import InvalidRequest
from activequal.model.predicates import validate_atom
from activequal.model.values import number

SOURCES = {"firmware", "mcu", "instrument", "optical"}
REDUCTIONS = {"max", "min", "mean", "max_gap", "count"}
OPERATORS = {"<=", ">=", "exact", "band"}
MAX_OBSERVATIONS = 32
MAX_REQUIREMENTS = 32
IDENTIFIER_LIMIT = 80


@dataclass(frozen=True)
class ObservationSpec:
    """One required or conditionally required measurement.

    ``uncertainty`` is the expanded measurement uncertainty U (k = 2, about 2σ) from the
    fixture's calibration. It is the guard band of HLD 04 §13 and defaults to 0.
    """

    name: str
    unit: str
    source: str
    reduction: str
    required: bool = False
    required_when: dict[str, Any] | None = None
    uncertainty: float = 0.0


@dataclass(frozen=True)
class RequirementSpec:
    id: str
    metric: str
    op: str
    limit: float | None = None      # "<=", ">=", "exact"
    lo: float | None = None         # "band"
    hi: float | None = None
    nominal: float | None = None    # scale of the planner margin (HLD 04 §13); optional for "exact"


@dataclass(frozen=True)
class ValiditySpec:
    """The measured ``metric`` must stay within ``tolerance`` of the requested ``tracks`` control."""

    metric: str
    tracks: str
    tolerance: float


@dataclass(frozen=True)
class SafetySpec:
    channels: dict[str, dict[str, float]]     # target -> {"maxA": ..., "maxV": ...}
    max_temp_c: float
    max_episode_s: float


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > IDENTIFIER_LIMIT:
        raise InvalidRequest(f"{name} must be a non-empty string of at most {IDENTIFIER_LIMIT} characters")
    return value.strip()


def parse_observations(raw: Any, control_names: set[str]) -> dict[str, ObservationSpec]:
    if not isinstance(raw, dict) or not raw or len(raw) > MAX_OBSERVATIONS:
        raise InvalidRequest(f"contract.observations must have 1–{MAX_OBSERVATIONS} entries")
    result: dict[str, ObservationSpec] = {}
    for name, spec in raw.items():
        where = f"observations.{name}"
        if not isinstance(spec, dict):
            raise InvalidRequest(f"{where} must be an object")
        source = spec.get("source")
        if source not in SOURCES:
            raise InvalidRequest(f"{where}.source must be one of {', '.join(sorted(SOURCES))}")
        reduction = spec.get("reduction")
        if reduction not in REDUCTIONS:
            raise InvalidRequest(f"{where}.reduction must be one of {', '.join(sorted(REDUCTIONS))}")
        required = spec.get("required", False)
        if not isinstance(required, bool):
            raise InvalidRequest(f"{where}.required must be true or false")
        required_when = spec.get("requiredWhen")
        if required_when is not None:
            validate_atom(required_when, control_names, f"{where}.requiredWhen")
        if not required and required_when is None:
            raise InvalidRequest(f"{where} must be required or declare requiredWhen")
        uncertainty = number(spec.get("uncertainty", 0), f"{where}.uncertainty")
        if uncertainty < 0:
            raise InvalidRequest(f"{where}.uncertainty must not be negative")
        result[name] = ObservationSpec(name, _text(spec.get("unit"), f"{where}.unit"), source, reduction,
                                       required, required_when, uncertainty)
    return result


def parse_requirements(raw: Any, observations: dict[str, ObservationSpec]) -> list[RequirementSpec]:
    if not isinstance(raw, list) or not raw or len(raw) > MAX_REQUIREMENTS:
        raise InvalidRequest(f"contract.requirements must have 1–{MAX_REQUIREMENTS} entries")
    result: list[RequirementSpec] = []
    seen: set[str] = set()
    for index, spec in enumerate(raw):
        where = f"requirements[{index}]"
        if not isinstance(spec, dict):
            raise InvalidRequest(f"{where} must be an object")
        ident = _text(spec.get("id"), f"{where}.id")
        if ident in seen:
            raise InvalidRequest(f"{where}.id {ident!r} is duplicated")
        seen.add(ident)
        metric = spec.get("metric")
        if metric not in observations:
            raise InvalidRequest(f"{where}.metric refers to unknown observation {metric!r}")
        op = spec.get("op")
        if op not in OPERATORS:
            raise InvalidRequest(f"{where}.op must be one of <=, >=, exact, band")
        nominal = number(spec["nominal"], f"{where}.nominal") if "nominal" in spec else None
        if op == "band":
            lo, hi = number(spec.get("lo"), f"{where}.lo"), number(spec.get("hi"), f"{where}.hi")
            if hi <= lo:
                raise InvalidRequest(f"{where} needs lo < hi")
            if nominal is None or not lo < nominal < hi:
                raise InvalidRequest(f"{where}.nominal must lie strictly inside the band")
            result.append(RequirementSpec(ident, metric, op, lo=lo, hi=hi, nominal=nominal))
            continue
        limit = number(spec.get("limit"), f"{where}.limit")
        if op == "exact":
            result.append(RequirementSpec(ident, metric, op, limit=limit, nominal=nominal))
            continue
        if nominal is None:
            raise InvalidRequest(f"{where}.nominal is required for {op}")
        if (op == "<=" and not nominal < limit) or (op == ">=" and not nominal > limit):
            raise InvalidRequest(f"{where}.nominal must satisfy the requirement with room to spare")
        result.append(RequirementSpec(ident, metric, op, limit=limit, nominal=nominal))
    return result


def parse_validity(raw: Any, observations: dict[str, ObservationSpec], numeric_controls: set[str]
                   ) -> list[ValiditySpec]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_REQUIREMENTS:
        raise InvalidRequest("contract.validity must be a list")
    result = []
    for index, spec in enumerate(raw):
        where = f"validity[{index}]"
        if not isinstance(spec, dict):
            raise InvalidRequest(f"{where} must be an object")
        metric, tracks = spec.get("metric"), spec.get("tracks")
        if metric not in observations:
            raise InvalidRequest(f"{where}.metric refers to unknown observation {metric!r}")
        if tracks not in numeric_controls:
            raise InvalidRequest(f"{where}.tracks must name a numeric control")
        tolerance = number(spec.get("tolerance"), f"{where}.tolerance")
        if tolerance <= 0:
            raise InvalidRequest(f"{where}.tolerance must be positive")
        result.append(ValiditySpec(metric, tracks, tolerance))
    return result


def parse_safety(raw: Any) -> SafetySpec:
    if not isinstance(raw, dict):
        raise InvalidRequest("contract.safety must be an object")
    channels_raw = raw.get("channels")
    if not isinstance(channels_raw, dict) or not channels_raw:
        raise InvalidRequest("safety.channels must name at least one channel")
    channels: dict[str, dict[str, float]] = {}
    for target, limits in channels_raw.items():
        if not isinstance(limits, dict):
            raise InvalidRequest(f"safety.channels.{target} must be an object")
        parsed = {key: number(limits.get(key), f"safety.channels.{target}.{key}") for key in ("maxA", "maxV")}
        if any(value <= 0 for value in parsed.values()):
            raise InvalidRequest(f"safety.channels.{target} limits must be positive")
        channels[str(target)] = parsed
    max_temp = number(raw.get("maxTempC"), "safety.maxTempC")
    max_episode = number(raw.get("maxEpisodeS"), "safety.maxEpisodeS")
    if max_episode <= 0:
        raise InvalidRequest("safety.maxEpisodeS must be positive")
    return SafetySpec(channels, max_temp, max_episode)
