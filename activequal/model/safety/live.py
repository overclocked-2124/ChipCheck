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


def _current_key(control: str) -> str:
    return control[:-1] + "A" if control.endswith("V") else control + "A"   # oledRailV -> oledRailA


def capture_trips(contract: ContractModel, volts: dict[str, float], amps: dict[str, float]) -> tuple[str, ...]:
    """Second check of rail read-backs taken during an episode (HLD 03 §13.1).

    ``volts`` is keyed by control name and ``amps`` by the matching current name (``oledRailA``).
    Only readings the bench took are judged; the Oracle handles missing required measurements.
    A voltage trips when it exceeds ``maxV`` by more than its read-back uncertainty U (the
    observation the contract's validity rule ties to that control), because a reading within U
    of the limit cannot be told apart from one at the limit. Currents carry no declared
    uncertainty and are compared directly. The test controller's hardware limit stays primary.
    """
    trips: list[str] = []
    try:
        if contract.safety is None:
            return ()
        allowance = {rule.tracks: (contract.observations or {})[rule.metric].uncertainty
                     for rule in contract.validity or [] if rule.metric in (contract.observations or {})}
        for name, control in contract.controls.items():
            target = control.bind[0] if control.bind else None
            limits = contract.safety.channels.get(target) if target else None
            if not limits:
                continue
            for kind, unit, value, limit, slack in (
                    ("voltage", "V", volts.get(name), limits["maxV"], allowance.get(name, 0.0)),
                    ("current", "A", amps.get(_current_key(name)), limits["maxA"], 0.0)):
                if value is None:
                    continue
                if not _finite(value):
                    trips.append(f"host check: {kind} reading on {target} is not a finite number")
                elif value > limit + slack:
                    trips.append(f"host check: {kind} on {target} measured {value:g} {unit}, "
                                 f"above the {limit:g} {unit} limit")
    except Exception as exc:  # fail closed
        trips.append(f"host check could not be evaluated ({type(exc).__name__})")
    return tuple(trips)
