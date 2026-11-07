"""In-memory simulated bench (WP3): benchmark profiles B1a, B1b, B1w, B2, B3 and fault injection.

Deterministic given (profile, noise seed, episode seed, attempt); no sleeps, well under 1 ms per
episode. The hidden fault constants below are the ground truth of the benchmarks. They live only
in this module: ``types`` and ``base`` carry no fault data, and Decision must never import this
package (``activequal/tests/test_boundaries.py``).

Search space (HLD 06 §3): ``oledRailV`` 3.00-3.60 V in 0.01 V steps (61 values), ``redLed`` and
``greenLed`` booleans, ``workload`` in idle / oled_refresh / sensor_read / wifi_tx / flash_write:
61 x 2 x 2 x 5 = 1,220 points.

Latency is observed only under ``oled_refresh`` (HLD 04 §12: ``requiredWhen`` workload). Baseline
31 ms with Gaussian noise (sigma 2.5 ms by default). Fault-bearing profiles:

* B1a/B1b/B1w: a Gaussian latency bump centred at 3.25 V, amplitude 129 ms (peak 160 ms),
  scaled by the LED state. The bump width is chosen so the noise-free mean crosses 125 ms (the
  guard-banded fail line, 120 ms + U = 5 ms) halfway between the last failing voltage and the
  next one, giving exactly 5 failing voltages (3.23-3.27 V) for B1a/B1b and 11 (3.20-3.30 V, the
  PRD §17.2 window) for B1w, in the target state red ON, green OFF, oled_refresh. B1a shows a
  partial precursor in wrong LED states (60% of the amplitude with one LED wrong, 30% with both
  wrong; never failing); B1b shows none outside the target state.
* B2: cliff. ``resetCount`` = 1 and no precursor at 3.15-3.18 V with red ON and workload
  sensor_read, either green state: 4 voltages x 2 = 8 failing points. A reset also shows as a
  1,200 ms heartbeat gap (reboot time).
* B3: no fault.

Achieved failing-point counts equal the HLD counts exactly (checked in the tests).
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from enum import Enum
from typing import Any

from activequal.adapter.service.types import (ApprovedEpisode, BenchEvent, BenchHealth, Phase,
                                              RawBenchCapture, Trip)

VOLT_MIN, VOLT_STEP, VOLT_COUNT = 3.00, 0.01, 61
WORKLOADS = ("idle", "oled_refresh", "sensor_read", "wifi_tx", "flash_write")
PROFILE_NAMES = ("B1a", "B1b", "B1w", "B2", "B3")

BASE_LATENCY_MS = 31.0
LATENCY_SIGMA_MS = 2.5
RAIL_SIGMA_V = 0.002            # SWE-POC-HANDOFF Decision 4: sigma_V = 2 mV
FAIL_LINE_MS = 125.0            # 120 ms limit + U = 5 ms
_PEAK_EXCESS_MS = 129.0         # bump amplitude: peak 160 ms
_CENTER_INDEX = 25              # 3.25 V
_CLIFF_INDICES = range(15, 19)  # 3.15-3.18 V
_ESTOP_PHASES = (Phase.PREFLIGHT, Phase.CONFIGURING, Phase.SETTLING, Phase.EXECUTING, Phase.OBSERVING)

# Timeline (ms from episode start) taken from HLD 03 §21.1 starting values.
_T_CONFIGURING, _T_SETTLING, _SETTLE_MS, _OLED_READY_MS = 20, 60, 60, 150
_SETTLE_TIMEOUT_MS, _SHUTDOWN_MS = 200, 120


@dataclass(frozen=True)
class _Profile:
    half_width_steps: int | None     # B1: failing voltages are centre +- this many steps
    wrong_one_led: float = 0.0       # precursor scale with one LED wrong
    wrong_both_led: float = 0.0
    cliff: bool = False


_PROFILES: dict[str, _Profile] = {
    "B1A": _Profile(2, 0.6, 0.3),
    "B1B": _Profile(2),
    "B1W": _Profile(5, 0.6, 0.3),
    "B2": _Profile(None, cliff=True),
    "B3": _Profile(None),
}


class FaultKind(str, Enum):
    """HLD 03 §23.2 simulator cases (the normal pass and valid DUT failure come from the profiles)."""

    NONE = "none"
    RAIL_SETTLING_TIMEOUT = "rail_settling_timeout"
    MISSING_OLED_OBSERVATION = "missing_oled_observation"
    DUT_HEARTBEAT_LOSS = "dut_heartbeat_loss"
    INSTRUMENT_DISCONNECT_BEFORE_OUTPUT = "instrument_disconnect_before_output"
    INSTRUMENT_DISCONNECT_AFTER_OUTPUT = "instrument_disconnect_after_output"
    CONTROLLER_WATCHDOG_EXPIRY = "controller_watchdog_expiry"
    ESTOP = "estop"
    SHUTDOWN_FAILURE = "shutdown_failure"


@dataclass(frozen=True)
class FaultInjection:
    """Which fault the adapter injects. ``phase`` is required for ESTOP and forbidden otherwise.

    ``episode_ids`` limits the fault to those episodes; ``None`` applies it to every episode.
    """

    kind: FaultKind = FaultKind.NONE
    phase: Phase | None = None
    episode_ids: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if self.kind is FaultKind.ESTOP:
            if self.phase not in _ESTOP_PHASES:
                raise ValueError("ESTOP needs a phase in PREFLIGHT, CONFIGURING, SETTLING, EXECUTING, OBSERVING")
        elif self.phase is not None:
            raise ValueError("phase applies only to ESTOP")


class BenchLockedOut(RuntimeError):
    """Raised when an episode is requested while the cutoff lockout is latched (HLD 03 §13)."""


class _Trace:
    """Builds the phase list and event log of one episode."""

    def __init__(self) -> None:
        self.phases: list[str] = []
        self.events: list[BenchEvent] = []

    def enter(self, phase: Phase, t_ms: int, note: str) -> None:
        self.phases.append(phase.value)
        self.events.append(BenchEvent(phase.value, t_ms, note))

    def note(self, phase: Phase, t_ms: int, note: str) -> None:
        self.events.append(BenchEvent(phase.value, t_ms, note))


class SimulatedBenchAdapter:
    """``BenchAdapter`` implementation over synthetic physics."""

    def __init__(self, profile: str = "B3", noise_seed: int = 0, latency_sigma_ms: float = LATENCY_SIGMA_MS,
                 fault: FaultInjection | None = None, dut_firmware_sha256: str = "0" * 64,
                 mcu_firmware_sha256: str = "m" * 64) -> None:
        self.dut_firmware_sha256 = dut_firmware_sha256
        self.mcu_firmware_sha256 = mcu_firmware_sha256
        key = profile.upper()
        if key not in _PROFILES:
            raise ValueError(f"profile must be one of {', '.join(PROFILE_NAMES)}")
        self.profile = next(name for name in PROFILE_NAMES if name.upper() == key)
        self._p = _PROFILES[key]
        self.noise_seed = noise_seed
        self.latency_sigma_ms = latency_sigma_ms
        self.fault = fault or FaultInjection()
        self._locked_out = False
        if self._p.half_width_steps is not None:
            self._bump_width = (self._p.half_width_steps + 0.5) / math.sqrt(math.log(_PEAK_EXCESS_MS / (FAIL_LINE_MS - BASE_LATENCY_MS)))

    # ---------------------------------------------------------------- BenchAdapter

    def health_check(self) -> BenchHealth:
        if self._locked_out:
            return BenchHealth(ok=False, estop_released=False, locked_out=True,
                               dut_firmware_sha256=self.dut_firmware_sha256,
                               mcu_firmware_sha256=self.mcu_firmware_sha256,
                               detail=("cutoff lockout latched; manual interlock reset required",))
        return BenchHealth(ok=True, dut_firmware_sha256=self.dut_firmware_sha256,
                           mcu_firmware_sha256=self.mcu_firmware_sha256)

    def emergency_shutdown(self) -> None:
        self._locked_out = True

    def reset_lockout(self) -> None:
        """Simulator-only stand-in for the researcher's manual interlock reset (HLD 03 §13)."""
        self._locked_out = False

    def apply_and_measure(self, episode: ApprovedEpisode) -> RawBenchCapture:
        if self._locked_out:
            raise BenchLockedOut("cutoff lockout is latched")
        rng = self._rng(episode)
        draws = {name: rng.gauss(0.0, 1.0) for name in ("latency", "rail", "heartbeat", "dut", "current")}
        fault = self.fault
        if fault.kind is not FaultKind.NONE and (fault.episode_ids is None or episode.episode_id in fault.episode_ids):
            capture = self._faulted(episode, fault, draws)
        else:
            capture = self._normal(episode, draws)
        if capture.cutoff_engaged:
            self._locked_out = True
        return capture

    # ------------------------------------------------------------ ground truth

    def expected_observations(self, conditions: dict[str, Any]) -> dict[str, float]:
        """Noise-free observations for requested conditions. Ground truth for tests and scoring only."""
        index = self._index(conditions)
        result: dict[str, float] = {"resetCount": float(self._reset(conditions, index))}
        if conditions["workload"] == "oled_refresh":
            result["oledLatencyMs"] = self._latency_mean(conditions, index)
        return result

    # --------------------------------------------------------------- internals

    def _rng(self, episode: ApprovedEpisode) -> random.Random:
        digest = hashlib.sha256(f"{self.profile}|{self.noise_seed}|{episode.seed}|{episode.attempt}".encode()).digest()
        return random.Random(int.from_bytes(digest[:8], "big"))

    @staticmethod
    def _index(conditions: dict[str, Any]) -> int:
        index = round((float(conditions["oledRailV"]) - VOLT_MIN) / VOLT_STEP)
        if not 0 <= index < VOLT_COUNT:
            raise ValueError("oledRailV outside the simulated range")
        return index

    def _latency_mean(self, conditions: dict[str, Any], index: int) -> float:
        if self._p.half_width_steps is None:
            return BASE_LATENCY_MS
        wrong = int(not conditions["redLed"]) + int(bool(conditions["greenLed"]))
        scale = (1.0, self._p.wrong_one_led, self._p.wrong_both_led)[wrong]
        bump = math.exp(-((index - _CENTER_INDEX) / self._bump_width) ** 2)
        return BASE_LATENCY_MS + _PEAK_EXCESS_MS * scale * bump

    def _reset(self, conditions: dict[str, Any], index: int) -> int:
        return int(self._p.cliff and index in _CLIFF_INDICES and bool(conditions["redLed"])
                   and conditions["workload"] == "sensor_read")

    @staticmethod
    def _expected_names(episode: ApprovedEpisode) -> tuple[str, ...]:
        names = ["maxHeartbeatGapMs", "resetCount", "measuredDut3v3MinV"]
        if episode.conditions["workload"] == "oled_refresh":
            names.insert(0, "oledLatencyMs")
        return tuple(names)

    def _measurements(self, episode: ApprovedEpisode, draws: dict[str, float]) -> tuple[dict[str, float], dict[str, float]]:
        conditions = episode.conditions
        index = self._index(conditions)
        resets = self._reset(conditions, index)
        observations: dict[str, float] = {
            "maxHeartbeatGapMs": 1200.0 if resets else max(0.0, 200.0 + 5.0 * draws["heartbeat"]),
            "resetCount": float(resets),
            "measuredDut3v3MinV": 3.30 + 0.003 * draws["dut"],
        }
        if conditions["workload"] == "oled_refresh":
            observations["oledLatencyMs"] = max(1.0, self._latency_mean(conditions, index)
                                                + self.latency_sigma_ms * draws["latency"])
        currents = {"oledRailA": 0.020 + 0.0005 * draws["current"]}
        return observations, currents

    def _rail(self, episode: ApprovedEpisode, draws: dict[str, float]) -> float:
        return float(episode.conditions["oledRailV"]) + RAIL_SIGMA_V * draws["rail"]

    def _capture(self, episode: ApprovedEpisode, trace: _Trace, **fields: Any) -> RawBenchCapture:
        return RawBenchCapture(episode_id=episode.episode_id, attempt=episode.attempt, events=tuple(trace.events),
                               phases_reached=tuple(trace.phases), **fields)

    def _run_to_observing(self, episode: ApprovedEpisode, trace: _Trace) -> int:
        """Record PREFLIGHT..OBSERVING and return the time the observation window ends."""
        trace.enter(Phase.PREFLIGHT, 0, "identity and shutdown state verified")
        trace.enter(Phase.CONFIGURING, _T_CONFIGURING, "protection limits and capture programmed")
        trace.enter(Phase.SETTLING, _T_SETTLING, "outputs enabled")
        t_exec = _T_SETTLING + _SETTLE_MS
        trace.enter(Phase.EXECUTING, t_exec, "rail settled; workload started")
        t_obs = t_exec + _OLED_READY_MS
        trace.enter(Phase.OBSERVING, t_obs, "observation window open")
        return t_obs + episode.duration_ms

    def _normal(self, episode: ApprovedEpisode, draws: dict[str, float]) -> RawBenchCapture:
        trace = _Trace()
        t_end = self._run_to_observing(episode, trace)
        trace.enter(Phase.SHUTTING_DOWN, t_end, "window complete; ordered shutdown")
        trace.note(Phase.SHUTTING_DOWN, t_end + _SHUTDOWN_MS, "rails at shutdown threshold")
        observations, currents = self._measurements(episode, draws)
        return self._capture(episode, trace, measured_rail_v={"oledRailV": self._rail(episode, draws)},
                             measured_current_a=currents, observations=observations, shutdown_confirmed=True,
                             rail_settled=True)

    def _faulted(self, episode: ApprovedEpisode, fault: FaultInjection, draws: dict[str, float]) -> RawBenchCapture:
        kind = fault.kind
        requested = float(episode.conditions["oledRailV"])
        expected = self._expected_names(episode) + ("measuredOledRailV",)
        trace = _Trace()
        none: dict[str, float] = {}

        if kind is FaultKind.RAIL_SETTLING_TIMEOUT:
            trace.enter(Phase.PREFLIGHT, 0, "identity and shutdown state verified")
            trace.enter(Phase.CONFIGURING, _T_CONFIGURING, "protection limits and capture programmed")
            trace.enter(Phase.SETTLING, _T_SETTLING, "outputs enabled")
            trace.note(Phase.SETTLING, _T_SETTLING + _SETTLE_TIMEOUT_MS, "settling timeout: rail never in tolerance")
            trace.enter(Phase.SHUTTING_DOWN, _T_SETTLING + _SETTLE_TIMEOUT_MS, "ordered shutdown after timeout")
            return self._capture(
                episode, trace, measured_rail_v={"oledRailV": max(0.0, requested - 0.2 + RAIL_SIGMA_V * draws["rail"])},
                measured_current_a={"oledRailA": 0.020}, observations=none, shutdown_confirmed=True,
                rail_settled=False, missing_observations=expected)

        if kind is FaultKind.MISSING_OLED_OBSERVATION:
            capture = self._normal(episode, draws)
            observations = {k: v for k, v in capture.observations.items() if k != "oledLatencyMs"}
            events = capture.events + (BenchEvent(Phase.OBSERVING.value, 300, "optical sensor produced no data"),)
            return RawBenchCapture(
                episode_id=capture.episode_id, attempt=capture.attempt, measured_rail_v=capture.measured_rail_v,
                measured_current_a=capture.measured_current_a, observations=observations,
                events=events, phases_reached=capture.phases_reached, shutdown_confirmed=True,
                rail_settled=True, missing_observations=("oledLatencyMs",),
                instrument_errors=("optical sensor: no data in observation window",))

        if kind is FaultKind.DUT_HEARTBEAT_LOSS:
            t_end = self._run_to_observing(episode, trace)
            trace.note(Phase.OBSERVING, t_end - episode.duration_ms // 2, "DUT heartbeat lost")
            trace.enter(Phase.SHUTTING_DOWN, t_end, "window complete; ordered shutdown")
            observations = {"maxHeartbeatGapMs": float(episode.duration_ms), "resetCount": 0.0,
                            "measuredDut3v3MinV": 3.30 + 0.003 * draws["dut"]}
            return self._capture(
                episode, trace, measured_rail_v={"oledRailV": self._rail(episode, draws)},
                measured_current_a={"oledRailA": 0.020}, observations=observations, shutdown_confirmed=True,
                rail_settled=True, heartbeat_lost=True,
                missing_observations=tuple(n for n in expected if n not in observations and n != "measuredOledRailV"))

        if kind is FaultKind.INSTRUMENT_DISCONNECT_BEFORE_OUTPUT:
            trace.enter(Phase.PREFLIGHT, 0, "identity and shutdown state verified")
            trace.enter(Phase.CONFIGURING, _T_CONFIGURING, "supply.ch2 did not answer; outputs never enabled")
            trace.enter(Phase.SHUTTING_DOWN, _T_CONFIGURING + 100, "configuration error; outputs confirmed off by MCU")
            return self._capture(
                episode, trace, measured_rail_v=none, measured_current_a=none, observations=none,
                shutdown_confirmed=True, rail_settled=False, missing_observations=expected,
                instrument_errors=("supply.ch2: command timeout, instrument disconnected before output enable",))

        if kind is FaultKind.INSTRUMENT_DISCONNECT_AFTER_OUTPUT:
            trace.enter(Phase.PREFLIGHT, 0, "identity and shutdown state verified")
            trace.enter(Phase.CONFIGURING, _T_CONFIGURING, "protection limits and capture programmed")
            trace.enter(Phase.SETTLING, _T_SETTLING, "outputs enabled")
            trace.note(Phase.SETTLING, _T_SETTLING + 30, "supply.ch2 lost with output state uncertain")
            trace.enter(Phase.EMERGENCY_CUTOFF, _T_SETTLING + 30, "hardware cutoff opened")
            return self._capture(
                episode, trace, measured_rail_v={"oledRailV": max(0.0, requested / 2)}, measured_current_a=none,
                observations=none, shutdown_confirmed=False, trip=Trip.INSTRUMENT_UNCERTAIN_OUTPUT,
                cutoff_engaged=True, rail_settled=False, missing_observations=expected,
                instrument_errors=("supply.ch2: instrument disconnected after output enable",))

        if kind is FaultKind.CONTROLLER_WATCHDOG_EXPIRY:
            trace.enter(Phase.PREFLIGHT, 0, "identity and shutdown state verified")
            trace.enter(Phase.CONFIGURING, _T_CONFIGURING, "protection limits and capture programmed")
            trace.enter(Phase.SETTLING, _T_SETTLING, "outputs enabled")
            trace.enter(Phase.EXECUTING, _T_SETTLING + _SETTLE_MS, "rail settled; workload started")
            trace.note(Phase.EXECUTING, _T_SETTLING + _SETTLE_MS + 2000, "test-controller watchdog expired")
            trace.enter(Phase.EMERGENCY_CUTOFF, _T_SETTLING + _SETTLE_MS + 2000, "hardware watchdog removed power")
            return self._capture(
                episode, trace, measured_rail_v={"oledRailV": self._rail(episode, draws)},
                measured_current_a={"oledRailA": 0.020}, observations=none, shutdown_confirmed=False,
                trip=Trip.MCU_WATCHDOG, cutoff_engaged=True, rail_settled=True,
                missing_observations=tuple(n for n in expected if n != "measuredOledRailV"))

        if kind is FaultKind.ESTOP:
            return self._estop(episode, fault.phase, draws, trace, expected)

        if kind is FaultKind.SHUTDOWN_FAILURE:
            t_end = self._run_to_observing(episode, trace)
            trace.enter(Phase.SHUTTING_DOWN, t_end, "window complete; ordered shutdown")
            trace.note(Phase.SHUTTING_DOWN, t_end + 500, "rail did not reach shutdown threshold within 500 ms")
            trace.enter(Phase.EMERGENCY_CUTOFF, t_end + 500, "normal shutdown failed; cutoff requested")
            observations, currents = self._measurements(episode, draws)
            return self._capture(
                episode, trace, measured_rail_v={"oledRailV": self._rail(episode, draws)}, measured_current_a=currents,
                observations=observations, shutdown_confirmed=False, trip=Trip.SHUTDOWN_FAILED,
                cutoff_engaged=True, rail_settled=True)

        raise ValueError(f"unsupported fault {kind!r}")

    def _estop(self, episode: ApprovedEpisode, phase: Phase | None, draws: dict[str, float], trace: _Trace,
               expected: tuple[str, ...]) -> RawBenchCapture:
        assert phase is not None
        requested = float(episode.conditions["oledRailV"])
        steps = [(Phase.PREFLIGHT, 0, "identity and shutdown state verified"),
                 (Phase.CONFIGURING, _T_CONFIGURING, "protection limits and capture programmed"),
                 (Phase.SETTLING, _T_SETTLING, "outputs enabled"),
                 (Phase.EXECUTING, _T_SETTLING + _SETTLE_MS, "rail settled; workload started"),
                 (Phase.OBSERVING, _T_SETTLING + _SETTLE_MS + _OLED_READY_MS, "observation window open")]
        t = 0
        for step_phase, t, note in steps:
            trace.enter(step_phase, t, note)
            if step_phase is phase:
                break
        t += 10
        trace.note(phase, t, "E-stop pressed")
        trace.enter(Phase.EMERGENCY_CUTOFF, t, "hardware cutoff opened")
        rails: dict[str, float] = {}
        currents: dict[str, float] = {}
        settled = False
        if phase is Phase.SETTLING:
            rails = {"oledRailV": max(0.0, requested / 2)}      # caught mid-ramp
        elif phase in (Phase.EXECUTING, Phase.OBSERVING):
            rails = {"oledRailV": self._rail(episode, draws)}
            currents = {"oledRailA": 0.020}
            settled = True
        missing = tuple(n for n in expected if not (n == "measuredOledRailV" and rails))
        return self._capture(episode, trace, measured_rail_v=rails, measured_current_a=currents, observations={},
                             shutdown_confirmed=False, trip=Trip.ESTOP, cutoff_engaged=True, rail_settled=settled,
                             missing_observations=missing)
