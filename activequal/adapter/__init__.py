"""Bench adapter layer: the narrow hardware boundary (HLD 01, HLD 03 §10) and its simulator.

Importing this package must not load optuna or any planner code.
"""

from __future__ import annotations

from activequal.adapter.service.base import BenchAdapter
from activequal.adapter.service.simulator import FaultInjection, FaultKind, SimulatedBenchAdapter
from activequal.adapter.service.types import (ApprovedEpisode, BenchEvent, BenchHealth, Phase,
                                              RawBenchCapture, Trip)

__all__ = ["ApprovedEpisode", "BenchAdapter", "BenchEvent", "BenchHealth", "FaultInjection", "FaultKind",
           "Phase", "RawBenchCapture", "SimulatedBenchAdapter", "Trip"]
