"""The result a bench submits for one episode (HLD 05 §7.1): facts, never an outcome.

``manifest_hash`` is the SHA-256 of the canonical JSON of the payload without its own
``manifestHash`` field. Backend recomputes it, so a payload altered after the Controller hashed
it is rejected (HLD 03 §16, ``INTEGRITY_ERROR``). Both processes call the same function.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

from activequal.model.canonical import CanonicalError, canonical_json
from activequal.model.errors import InvalidRequest

MAX_EVENTS = 2000
MAX_TRACES = 64
MAX_TEXT = 500


def manifest_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "manifestHash"}
    try:
        return hashlib.sha256(canonical_json(body)).hexdigest()
    except CanonicalError as exc:
        raise InvalidRequest(f"result cannot be canonicalized: {exc}") from exc


@dataclass(frozen=True)
class Measured:
    value: float | None            # None: attempted but unavailable
    uncertainty: float | None = None


@dataclass(frozen=True)
class EpisodeResult:
    episode_id: str
    attempt: int
    lease_id: str
    contract_hash: str
    fixture_id: str
    requested: dict[str, Any]
    measured: dict[str, Measured]
    rail_settled: bool
    instrument_fault: bool
    shutdown_confirmed: bool
    timeouts: tuple[str, ...]
    safety_trip: str | None
    events: tuple[dict[str, Any], ...]
    traces: tuple[dict[str, Any], ...]
    manifest_hash: str


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 200:
        raise InvalidRequest(f"{name} must be a non-empty string")
    return value


def parse_result(payload: Any) -> EpisodeResult:
    """Validate the shape of a result payload. It does not judge the evidence."""
    if not isinstance(payload, dict):
        raise InvalidRequest("result must be an object")
    attempt = payload.get("attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise InvalidRequest("attempt must be a positive integer")
    requested = payload.get("requested")
    if not isinstance(requested, dict) or not requested:
        raise InvalidRequest("requested must be an object")
    measured_raw = payload.get("measured")
    if not isinstance(measured_raw, dict):
        raise InvalidRequest("measured must be an object")
    measured: dict[str, Measured] = {}
    for name, item in measured_raw.items():
        if not isinstance(item, dict) or "value" not in item:
            raise InvalidRequest(f"measured.{name} needs a value (null when unavailable)")
        value, uncertainty = item["value"], item.get("uncertainty")
        for label, number in (("value", value), ("uncertainty", uncertainty)):
            if number is None and label == "uncertainty":
                continue
            if number is None:
                continue
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                raise InvalidRequest(f"measured.{name}.{label} must be a finite number or null")
        measured[str(name)] = Measured(None if value is None else float(value),
                                       None if uncertainty is None else float(uncertainty))
    quality = payload.get("quality")
    if not isinstance(quality, dict):
        raise InvalidRequest("quality must be an object")
    for flag in ("railSettled", "instrumentFault", "shutdownConfirmed"):
        if not isinstance(quality.get(flag), bool):
            raise InvalidRequest(f"quality.{flag} must be true or false")
    timeouts = quality.get("timeouts", [])
    if not isinstance(timeouts, list) or not all(isinstance(t, str) and len(t) <= MAX_TEXT for t in timeouts):
        raise InvalidRequest("quality.timeouts must be a list of strings")
    trip = payload.get("safetyTrip")
    if trip is not None and (not isinstance(trip, str) or not trip.strip() or len(trip) > MAX_TEXT):
        raise InvalidRequest("safetyTrip must be null or a non-empty string")
    events = payload.get("events", [])
    if not isinstance(events, list) or len(events) > MAX_EVENTS or not all(isinstance(e, dict) for e in events):
        raise InvalidRequest(f"events must be a list of at most {MAX_EVENTS} objects")
    traces = payload.get("traces", [])
    if not isinstance(traces, list) or len(traces) > MAX_TRACES or not all(isinstance(t, dict) for t in traces):
        raise InvalidRequest(f"traces must be a list of at most {MAX_TRACES} objects")
    for trace in traces:
        digest = trace.get("sha256")
        if not (isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)):
            raise InvalidRequest("every trace needs a lowercase hex sha256")
    return EpisodeResult(
        episode_id=_text(payload.get("episodeId"), "episodeId"), attempt=attempt,
        lease_id=_text(payload.get("leaseId"), "leaseId"), contract_hash=_text(payload.get("contractHash"), "contractHash"),
        fixture_id=_text(payload.get("fixtureId"), "fixtureId"), requested=requested, measured=measured,
        rail_settled=quality["railSettled"], instrument_fault=quality["instrumentFault"],
        shutdown_confirmed=quality["shutdownConfirmed"], timeouts=tuple(timeouts),
        safety_trip=trip.strip() if isinstance(trip, str) else None, events=tuple(events), traces=tuple(traces),
        manifest_hash=_text(payload.get("manifestHash"), "manifestHash"))
