"""Live safety checks against measured readings (HLD 03 §11.3, §13; HLD 04 §8).

``live_trips`` returns one human-readable reason per tripped limit. An empty tuple means no limit
was exceeded and every required safety measurement was present and finite. A missing or
non-finite reading is itself a trip, and anything the function cannot evaluate trips as well.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from activequal.model.contract import ContractModel


@dataclass(frozen=True)
class LiveReadings:
    volts: dict[str, float] = field(default_factory=dict)
    amps: dict[str, float] = field(default_factory=dict)
    temp_c: float | None = None
    elapsed_s: float = 0.0


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _channel(trips: list[str], kind: str, unit: str, target: str, readings: Any, limit: float) -> None:
    value = readings.get(target) if isinstance(readings, dict) else None
    if not _finite(value):
        trips.append(f"{kind} reading for {target} is missing or not finite")
    elif value > limit:
        trips.append(f"{kind} on {target} is {value:g} {unit}, above the {limit:g} {unit} limit")


def live_trips(contract: ContractModel, readings: LiveReadings) -> tuple[str, ...]:
    trips: list[str] = []
    try:
        safety = contract.safety
        if safety is None:
            return ("contract has no safety limits, so live readings cannot be judged",)
        for target, limits in safety.channels.items():
            _channel(trips, "voltage", "V", target, readings.volts, limits["maxV"])
            _channel(trips, "current", "A", target, readings.amps, limits["maxA"])
        if not _finite(readings.temp_c):
            trips.append("temperature reading is missing or not finite")
        elif readings.temp_c > safety.max_temp_c:
            trips.append(f"temperature is {readings.temp_c:g} C, above the {safety.max_temp_c:g} C limit")
        if not _finite(readings.elapsed_s):
            trips.append("elapsed time is missing or not finite")
        elif readings.elapsed_s > safety.max_episode_s:
            trips.append(f"episode has run {readings.elapsed_s:g} s, above the {safety.max_episode_s:g} s limit")
    except Exception as exc:  # fail closed: anything unevaluable is a trip
        trips.append(f"live safety check could not be evaluated ({type(exc).__name__})")
    return tuple(trips)
