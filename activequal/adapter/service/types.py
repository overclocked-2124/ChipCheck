"""Value types crossing the Adapter boundary (HLD 03 §8, §10; SWE-POC-HANDOFF §6.1).

``ApprovedEpisode`` is what the Controller hands the adapter after Backend approval.
``RawBenchCapture`` is what comes back: requested and measured values are kept apart,
and anything the bench could not capture is listed explicitly rather than defaulted.
Nothing here carries hidden fault data; ground truth stays inside the simulator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, NamedTuple


class Phase(str, Enum):
    """Episode phases of HLD 03 §8 that the adapter can reach while it owns the bench."""

    PREFLIGHT = "PREFLIGHT"
    CONFIGURING = "CONFIGURING"
    SETTLING = "SETTLING"
    EXECUTING = "EXECUTING"
    OBSERVING = "OBSERVING"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    EMERGENCY_CUTOFF = "EMERGENCY_CUTOFF"


class Trip:
    """Reasons a safety mechanism fired (HLD 03 §13). A set ``trip`` always means SAFETY_ABORT."""

    ESTOP = "ESTOP"
    MCU_WATCHDOG = "MCU_WATCHDOG"
    INSTRUMENT_UNCERTAIN_OUTPUT = "INSTRUMENT_UNCERTAIN_OUTPUT"
    SHUTDOWN_FAILED = "SHUTDOWN_FAILED"


@dataclass(frozen=True)
class ApprovedEpisode:
    """One approved episode. ``conditions`` are the *requested* values, keyed by control name."""

    episode_id: str
    attempt: int
    contract_hash: str
    fixture_id: str
    conditions: dict[str, Any]
    duration_ms: int            # dwell / observation window
    seed: int                   # per-episode seed; same seed + attempt gives the same noise draw


class BenchEvent(NamedTuple):
    """A timestamped note from one phase. ``t_ms`` counts from the start of the episode."""

    phase: str
    t_ms: int
    note: str


@dataclass(frozen=True)
class RawBenchCapture:
    """Everything the bench measured. Interpretation (outcome, verdict) belongs to the Oracle.

    ``observations`` holds only values that were really captured. Anything expected but absent
    is named in ``missing_observations``; consumers must never read a missing name as zero.
    """

    episode_id: str
    attempt: int
    measured_rail_v: dict[str, float]       # measured, e.g. {"oledRailV": 3.247}; the request is in the episode
    measured_current_a: dict[str, float]
    observations: dict[str, float]          # oledLatencyMs, maxHeartbeatGapMs, resetCount, measuredDut3v3MinV
    events: tuple[BenchEvent, ...]
    phases_reached: tuple[str, ...]
    shutdown_confirmed: bool                # ordered shutdown (HLD 03 §12) confirmed the safe state
    trip: str | None = None                 # a Trip value, or None
    cutoff_engaged: bool = False            # hardware cutoff opened (HLD 03 §13)
    rail_settled: bool = False              # measured rail reached the requested value within tolerance
    missing_observations: tuple[str, ...] = ()
    instrument_errors: tuple[str, ...] = ()
    heartbeat_lost: bool = False


@dataclass(frozen=True)
class BenchHealth:
    """Result of ``health_check``: watchdog, E-stop and lockout state, DUT and instrument links."""

    ok: bool
    watchdog_ok: bool = True
    estop_released: bool = True
    locked_out: bool = False
    dut_connected: bool = True
    instruments_connected: bool = True
    dut_firmware_sha256: str | None = None      # identities read back from the DUT and the test controller
    mcu_firmware_sha256: str | None = None
    detail: tuple[str, ...] = field(default_factory=tuple)
