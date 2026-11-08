"""Host-side second check of the bench's measured rail readings (HLD 03 §11.3, §13).

The test-controller MCU enforces the limits in hardware and is the primary protection. The coarse
adapter interface returns readings only after the episode, so this check runs on the capture: any
measured rail voltage or current above the contract's safety limit for that channel turns the
episode into a safety abort, which locks the campaign out. Readings the bench did not take are not
judged here; the Oracle already treats missing required measurements as invalid.

A rail voltage trips only when it exceeds the limit by more than its read-back uncertainty U (the
observation the contract's validity rule ties to that control), so noise at a legal maximum does
not lock the bench out. Currents carry no declared uncertainty and are compared directly.
"""

from __future__ import annotations

import math

from activequal.adapter.service.types import RawBenchCapture
from activequal.model.contract import ContractModel


def _current_key(control: str) -> str:
    return control[:-1] + "A" if control.endswith("V") else control + "A"   # oledRailV -> oledRailA


def host_limit_trips(model: ContractModel | None, capture: RawBenchCapture) -> tuple[str, ...]:
    if model is None or model.safety is None:
        return ()
    trips: list[str] = []
    allowance: dict[str, float] = {}
    for rule in model.validity or []:
        obs = (model.observations or {}).get(rule.metric)
        allowance[rule.tracks] = obs.uncertainty if obs is not None else 0.0
    for name, control in model.controls.items():
        target = control.bind[0] if control.bind else None
        limits = model.safety.channels.get(target) if target else None
        if not limits:
            continue
        for kind, unit, value, limit, slack in (
                ("voltage", "V", capture.measured_rail_v.get(name), limits["maxV"], allowance.get(name, 0.0)),
                ("current", "A", capture.measured_current_a.get(_current_key(name)), limits["maxA"], 0.0)):
            if value is None:
                continue
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                trips.append(f"host check: {kind} reading on {target} is not a finite number")
            elif value > limit + slack:
                trips.append(f"host check: {kind} on {target} measured {value:g} {unit}, above the {limit:g} {unit} limit")
    return tuple(trips)
