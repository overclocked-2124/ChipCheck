"""``SerialBenchAdapter``: the host side of the test-controller protocol (HLD 10 WP9, HLD 05 §9).

Implements the ``BenchAdapter`` Protocol over a ``ByteStream``. It runs one episode as
PREFLIGHT, CONFIGURING, SETTLING, EXECUTING, OBSERVING, SHUTTING_DOWN (HLD 03 §8, §12) and returns the
same ``RawBenchCapture`` shapes as the simulator for the same situations.

Rules it follows (HLD 03 §13, HLD 05 §9.3, §11):

* Every command waits for its ACK (100 ms). A lost ACK is retried with the same seq (the MCU never
  executes a repeated seq twice); READ_ALL and HEARTBEAT are simply sent again with a new seq.
* HEARTBEAT every 250 ms of protocol time, inside every wait loop.
* Rail settling means three consecutive in-tolerance read-backs within 200 ms of the ramp ending.
  The ramp itself is slew limited and takes ``target / slew`` seconds.
* Any uncertainty about the physical state ends in SHUTDOWN, then cutoff, and a ``Trip`` value. A
  failure never produces a successful-looking capture.

``clock`` and ``sleep`` are injectable so tests run on virtual time.
"""

from __future__ import annotations

import hashlib
import statistics
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from activequal.adapter.service.serial import framing, messages as m
from activequal.adapter.service.serial.stream import ByteStream
from activequal.adapter.service.simulator import BenchLockedOut
from activequal.adapter.service.types import (ApprovedEpisode, BenchEvent, BenchHealth, Phase, RawBenchCapture,
                                              Trip)

ACK_TIMEOUT_S = 0.1
HEARTBEAT_INTERVAL_S = 0.25
SETTLE_TIMEOUT_S = 0.2
SETTLE_COUNT = 3
SETTLE_TOLERANCE_V = 0.010
SHUTDOWN_THRESHOLD_V = 0.100
SHUTDOWN_TIMEOUT_S = 0.7            # the MCU gives up at 0.5 s and opens the cutoff; the host allows its report time
OBSERVE_DELAY_MS = 150
CRC_STORM = 8                        # consecutive undecodable frames without a valid one

_ALERT_TRIPS = {
    m.AlertCode.ESTOP: Trip.ESTOP,
    m.AlertCode.HOST_LOSS: Trip.MCU_WATCHDOG,
    m.AlertCode.WATCHDOG: Trip.MCU_WATCHDOG,
    m.AlertCode.SHUTDOWN_FAILED: Trip.SHUTDOWN_FAILED,
    # Trip has no over-current / over-voltage / over-temperature / episode-timeout value. These are
    # reported as an uncertain output; the exact cause is in the events and instrument_errors.
    m.AlertCode.OVERCURRENT: Trip.INSTRUMENT_UNCERTAIN_OUTPUT,
    m.AlertCode.OVERVOLTAGE: Trip.INSTRUMENT_UNCERTAIN_OUTPUT,
    m.AlertCode.OVERTEMP: Trip.INSTRUMENT_UNCERTAIN_OUTPUT,
    m.AlertCode.EPISODE_TIMEOUT: Trip.INSTRUMENT_UNCERTAIN_OUTPUT,
}


def episode_tag(episode_id: str) -> int:
    """Low 32 bits of the episode id (HLD 05 §9.1). A UUID uses its own low bits; any other id is hashed."""
    try:
        return uuid.UUID(episode_id).int & 0xFFFFFFFF
    except ValueError:
        return int.from_bytes(hashlib.sha256(episode_id.encode()).digest()[:4], "little")


@dataclass(frozen=True)
class RailBinding:
    """A contract control bound to an MCU channel (HLD 04 §12 ``bind``)."""

    control: str                  # contract control name, also the key in measured_rail_v
    channel: int                  # MCU channel id
    name: str                     # contract target, e.g. "supply.ch2"
    current_key: str              # key in measured_current_a
    measured_name: str            # observation name for "missing" lists
    max_v: float = 3.6
    max_a: float = 0.2
    slew_v_per_s: float = 0.5     # must not exceed the control's slewPerSMax
    hw_slew_v_per_s: float = 0.5  # the MCU-side slew limit programmed with SET_LIMITS
    gain: float = 1.0             # calibration: volts = gain * raw + offset (tools/calibrate.py)
    offset: float = 0.0


DEFAULT_RAILS = (
    RailBinding("oledRailV", m.OLED_RAIL_CH, "supply.ch2", "oledRailA", "measuredOledRailV"),
    RailBinding("sensorRailV", m.SENSOR_RAIL_CH, "supply.ch3", "sensorRailA", "measuredSensorRailV"),
)


@dataclass(frozen=True)
class HostConfig:
    rails: tuple[RailBinding, ...] = DEFAULT_RAILS
    ack_timeout_s: float = ACK_TIMEOUT_S
    ack_retries: int = 2
    heartbeat_interval_s: float = HEARTBEAT_INTERVAL_S
    settle_timeout_s: float = SETTLE_TIMEOUT_S
    settle_count: int = SETTLE_COUNT
    settle_tolerance_v: float = SETTLE_TOLERANCE_V
    poll_interval_s: float = 0.05
    shutdown_threshold_v: float = SHUTDOWN_THRESHOLD_V
    shutdown_timeout_s: float = SHUTDOWN_TIMEOUT_S
    observe_delay_ms: int = OBSERVE_DELAY_MS
    max_episode_ms: int = 12_000      # MCU backstop above the contract's maxEpisodeS (slew ramps take seconds)
    expected_fixture_id: str | None = None   # defaults to the episode's fixture


class _Fault(Exception):
    """Internal: a step failed. ``kind`` selects the recovery path."""

    def __init__(self, kind: str, detail: str, *, alert: m.Alert | None = None, flags: m.Flag | None = None) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail, self.alert, self.flags = kind, detail, alert, flags


COMM, NACKED, ALERTED, SETTLE, TIMEOUT, CONFIG, ABORTED = ("comm", "nack", "alert", "settle", "timeout", "config",
                                                          "abort")


@dataclass
class _Run:
    episode: ApprovedEpisode
    tag: int
    start: float
    rails: tuple[RailBinding, ...]
    phases: list[str] = field(default_factory=list)
    events: list[BenchEvent] = field(default_factory=list)
    output_risk: bool = False           # an ENABLE_RAIL may have taken effect
    settled: bool = False
    instrument_errors: list[str] = field(default_factory=list)
    last_v: dict[str, float] = field(default_factory=dict)
    last_a: dict[str, float] = field(default_factory=dict)
    obs_v: dict[str, list[float]] = field(default_factory=dict)
    obs_a: dict[str, list[float]] = field(default_factory=dict)
    observations: dict[str, float] = field(default_factory=dict)
    heartbeat_lost: bool = False
    cutoff_engaged: bool = False


class SerialBenchAdapter:
    def __init__(self, stream: ByteStream, config: HostConfig | None = None, *,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        self.stream = stream
        self.cfg = config or HostConfig()
        self._clock, self._sleep = clock, sleep
        self._decoder = framing.FrameDecoder(resync_types=())
        self._lock = threading.RLock()
        self._seq = 0
        self._busy = threading.Event()
        self._abort = threading.Event()
        self._locked_known = False
        self._cleanup = False
        self._last_health: BenchHealth | None = None
        self._reset_link_state()
        self.stats = {"crc_errors": 0, "frames": 0, "duplicates": 0, "gaps": 0, "heartbeats": 0, "retries": 0}

    # ---------------------------------------------------------------------------------- link state

    def _reset_link_state(self) -> None:
        self._replies: dict[int, m.Ack | m.Nack] = {}
        self._pending_alerts: list[m.Alert] = []
        self._mcu_events: list[tuple[float, m.Event]] = []
        self._rails: dict[int, m.RailReading] = {}
        self._rails_n = 0
        self._obs: dict[str, float] = {}
        self._identity: m.Identity | None = None
        self._limits_echo: m.LimitsReadback | None = None
        self._state = m.State.SAFE
        self._flags = m.Flag.WATCHDOG_OK | m.Flag.DUT_LINK_OK | m.Flag.INSTRUMENTS_OK
        self._bad_streak = 0
        self._last_hb = self._clock()

    # ------------------------------------------------------------------------------------ transport

    def _next_seq(self) -> int:
        with self._lock:                 # the emergency path draws from the same counter on another thread
            seq = self._seq
            self._seq = (self._seq + 1) & 0xFFFF
            return seq

    def _write(self, data: bytes) -> None:
        try:
            self.stream.write(data)
        except OSError as exc:
            raise _Fault(COMM, f"instrument disconnected on write: {exc}") from exc

    def _poll(self, wait_s: float = 0.0) -> None:
        try:
            data = self.stream.read(4096, wait_s)
        except OSError as exc:
            raise _Fault(COMM, f"instrument disconnected on read: {exc}") from exc
        if not data:
            return
        for event in self._decoder.feed(data):
            if isinstance(event, framing.Frame):
                self._bad_streak = 0
                self.stats["frames"] += 1
                self._dispatch(event)
            elif isinstance(event, framing.FrameError):
                self.stats["crc_errors"] += 1
                self._bad_streak += 1
            elif isinstance(event, framing.Gap):
                self.stats["gaps"] += event.missing
            else:
                self.stats["duplicates"] += 1
        if self._bad_streak >= CRC_STORM:
            raise _Fault(COMM, f"CRC error storm: {self._bad_streak} undecodable frames in a row")

    def _dispatch(self, frame: framing.Frame) -> None:
        if frame.type not in m.MCU_TYPES:
            return
        try:
            msg = m.decode_mcu_message(frame.type, frame.payload)
        except (m.MessageError, KeyError):
            self.stats["crc_errors"] += 1
            return
        now = self._clock()
        if isinstance(msg, (m.Ack, m.Nack)):
            self._state, self._flags = msg.state, msg.flags
            self._replies[msg.cmd_seq] = msg
        elif isinstance(msg, m.Event):
            self._mcu_events.append((now, msg))
        elif isinstance(msg, m.Alert):
            self._pending_alerts.append(msg)
        elif isinstance(msg, m.RailsMeasurement):
            self._rails = {r.channel: r for r in msg.rails}
            self._rails_n += 1
        elif isinstance(msg, m.Observation):
            self._obs[m.OBS_NAMES[msg.obs_id]] = msg.value
        elif isinstance(msg, m.Identity):
            self._identity = msg
        elif isinstance(msg, m.LimitsReadback):
            self._limits_echo = msg

    def _command(self, msg: Any, *, tag: int = 0) -> m.Ack:
        """Send one command and wait for its ACK. Raises ``_Fault`` on NACK, timeout or disconnect."""
        msg_type = msg.TYPE
        payload = msg.pack()
        fresh_seq_on_retry = msg_type in (m.READ_ALL, m.HEARTBEAT)
        seq = self._next_seq()
        for attempt in range(1 + self.cfg.ack_retries):
            if attempt:
                self.stats["retries"] += 1
                if fresh_seq_on_retry:
                    seq = self._next_seq()
            with self._lock:
                self._write(framing.encode_frame(msg_type, seq, payload, tag))
            if msg_type == m.HEARTBEAT:
                self.stats["heartbeats"] += 1
            reply = self._await_reply(seq, self.cfg.ack_timeout_s)
            if reply is not None:
                break
        else:
            raise _Fault(COMM, f"{m.NAMES[msg_type]}: no ACK within {int(self.cfg.ack_timeout_s * 1000)} ms "
                               f"after {1 + self.cfg.ack_retries} attempts")
        if isinstance(reply, m.Nack):
            self._check_alerts()
            raise _Fault(NACKED, f"MCU rejected {m.NAMES[msg_type]}: {reply.reason.name}", flags=reply.flags)
        return reply

    def _await_reply(self, seq: int, timeout_s: float) -> m.Ack | m.Nack | None:
        deadline = self._clock() + timeout_s
        while True:
            if seq in self._replies:
                return self._replies.pop(seq)
            remaining = deadline - self._clock()
            if remaining <= 0:
                return None
            self._poll(remaining)

    # --------------------------------------------------------------------------- waiting and alerts

    def _check_alerts(self) -> None:
        if self._pending_alerts and not self._cleanup:
            raise _Fault(ALERTED, describe_alert(self._pending_alerts[0]), alert=self._pending_alerts[0])
        if self._abort.is_set() and not self._cleanup:
            raise _Fault(ABORTED, "emergency shutdown requested by the Controller")

    def _service(self) -> None:
        """Heartbeat when due, read what has arrived, and surface alerts."""
        now = self._clock()
        if now - self._last_hb >= self.cfg.heartbeat_interval_s:
            self._last_hb = now
            self._command(m.Heartbeat(int(now * 1000)))
        self._poll(0.0)
        self._check_alerts()

    def _spin(self, done: Callable[[], bool], timeout_s: float, *, step_s: float = 0.01) -> bool:
        deadline = self._clock() + timeout_s
        while True:
            self._service()
            if done():
                return True
            now = self._clock()
            if now >= deadline:
                return False
            until_hb = max(0.001, self.cfg.heartbeat_interval_s - (now - self._last_hb))
            self._sleep(min(step_s, deadline - now, until_hb))

    def _read_all(self) -> dict[int, m.RailReading]:
        before = self._rails_n
        self._command(m.ReadAll())
        deadline = self._clock() + self.cfg.ack_timeout_s
        while self._rails_n == before:
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise _Fault(COMM, "READ_ALL: acknowledged but no MEASUREMENT followed")
            self._poll(remaining)
        self._check_alerts()
        return dict(self._rails)

    def _volts(self, binding: RailBinding, reading: m.RailReading) -> float:
        return binding.gain * (reading.mv / 1000.0) + binding.offset

    # ------------------------------------------------------------------------------- BenchAdapter

    def health_check(self) -> BenchHealth:
        if self._busy.is_set():
            return self._last_health or BenchHealth(ok=False, detail=("an episode is in progress",))
        try:
            with self._lock:
                self._hello()
        except _Fault as fault:
            health = BenchHealth(ok=False, watchdog_ok=False, instruments_connected=False,
                                 detail=(f"test controller unreachable: {fault.detail}",))
            self._last_health = health
            return health
        flags, identity = self._flags, self._identity
        locked = bool(flags & m.Flag.LOCKED_OUT) or bool(flags & m.Flag.CUTOFF_OPEN)
        estop_released = not flags & m.Flag.ESTOP
        watchdog_ok = bool(flags & m.Flag.WATCHDOG_OK)
        dut = bool(flags & m.Flag.DUT_LINK_OK)
        instruments = bool(flags & m.Flag.INSTRUMENTS_OK)
        detail = []
        if locked:
            detail.append("cutoff lockout latched; manual interlock reset required")
        if not estop_released:
            detail.append("E-stop pressed")
        if not watchdog_ok:
            detail.append("hardware watchdog tripped")
        if self._state not in (m.State.SAFE,) and not locked:
            detail.append(f"test controller is not in the safe state ({self._state.name})")
        self._locked_known = locked
        health = BenchHealth(
            ok=not locked and estop_released and watchdog_ok and dut and instruments and self._state is m.State.SAFE,
            watchdog_ok=watchdog_ok, estop_released=estop_released, locked_out=locked, dut_connected=dut,
            instruments_connected=instruments, dut_firmware_sha256=identity.dut_fw_sha256 if identity else None,
            mcu_firmware_sha256=identity.mcu_fw_sha256 if identity else None, detail=tuple(detail))
        self._last_health = health
        return health

    def reset_lockout(self) -> None:
        """Forget the cached lockout so the next ``health_check`` re-reads it. The real reset is a physical
        action on the interlock; this never touches hardware."""
        self._locked_known = False

    def emergency_shutdown(self) -> None:
        """Open the hardware cutoff via the MCU. Never raises."""
        self._abort.set()
        self._locked_known = True
        try:
            if self._busy.is_set():
                with self._lock:                     # the running episode sees the ACK / ALERT and stands down
                    self._write(framing.encode_frame(m.SHUTDOWN, self._next_seq(), m.Shutdown(m.SHUTDOWN_CUTOFF).pack()))
            else:
                self._cleanup = True
                try:
                    self._command(m.Shutdown(m.SHUTDOWN_CUTOFF))
                finally:
                    self._cleanup = False
                    self._abort.clear()
        except Exception:
            self._cleanup = False
            if not self._busy.is_set():
                self._abort.clear()

    def apply_and_measure(self, episode: ApprovedEpisode) -> RawBenchCapture:
        if self._locked_known:
            raise BenchLockedOut("cutoff lockout is latched")
        self._abort.clear()
        self._busy.set()
        try:
            return self._run_episode(episode)
        except BenchLockedOut:
            raise
        except BaseException:
            self._cutoff_best_effort()                  # a bug or interrupt mid-episode: uncertain state, cut power
            raise
        finally:
            self._busy.clear()
            self._cleanup = False

    def _cutoff_best_effort(self) -> None:
        try:
            self._cleanup = True
            self._command(m.Shutdown(m.SHUTDOWN_CUTOFF))
        except Exception:
            pass
        finally:
            self._cleanup = False
        self._locked_known = True

    # ---------------------------------------------------------------------------------- the episode

    def _hello(self) -> m.Ack:
        self._decoder = framing.FrameDecoder()
        self._reset_link_state()
        self._identity = None
        ack = self._command(m.Hello(framing.PROTOCOL_VERSION))
        if not self._spin_quiet(lambda: self._identity is not None, self.cfg.ack_timeout_s):
            raise _Fault(COMM, "HELLO: acknowledged but no identity followed")
        assert self._identity is not None
        if self._identity.protocol != framing.PROTOCOL_VERSION:
            raise _Fault(CONFIG, f"test controller speaks protocol {self._identity.protocol}")
        return ack

    def _spin_quiet(self, done: Callable[[], bool], timeout_s: float) -> bool:
        """Wait for a reply message without heartbeat or alert side effects (used before an episode)."""
        deadline = self._clock() + timeout_s
        while not done():
            remaining = deadline - self._clock()
            if remaining <= 0:
                return False
            self._poll(remaining)
        return True

    def _run_episode(self, episode: ApprovedEpisode) -> RawBenchCapture:
        rails = tuple(r for r in self.cfg.rails if r.control in episode.conditions)
        run = _Run(episode, episode_tag(episode.episode_id), self._clock(), rails)
        try:
            self._preflight(run)
            self._configure(run)
            self._energize_and_settle(run)
            self._execute(run)
        except _Fault as fault:
            return self._recover(run, fault)
        return self._finish_normal(run)

    # -- bookkeeping -------------------------------------------------------------------------------

    def _t(self, run: _Run) -> int:
        return int(round((self._clock() - run.start) * 1000))

    def _enter(self, run: _Run, phase: Phase, note: str) -> None:
        run.phases.append(phase.value)
        run.events.append(BenchEvent(phase.value, self._t(run), note))

    def _note(self, run: _Run, note: str, phase: str | None = None) -> None:
        run.events.append(BenchEvent(phase or (run.phases[-1] if run.phases else Phase.PREFLIGHT.value), self._t(run), note))

    # -- PREFLIGHT ---------------------------------------------------------------------------------

    def _preflight(self, run: _Run) -> None:
        self._enter(run, Phase.PREFLIGHT, "identity and shutdown state verified")
        self._cleanup = False
        ack = self._hello()
        expected = self.cfg.expected_fixture_id or run.episode.fixture_id
        assert self._identity is not None
        if self._identity.fixture_id != expected:
            raise _Fault(CONFIG, f"fixture identity {self._identity.fixture_id!r}, expected {expected!r}")
        if ack.flags & (m.Flag.LOCKED_OUT | m.Flag.ESTOP | m.Flag.CUTOFF_OPEN):
            trip_code = m.AlertCode.ESTOP if ack.flags & m.Flag.ESTOP else m.AlertCode.WATCHDOG
            if not ack.flags & m.Flag.ESTOP and self._locked_known:
                raise BenchLockedOut("cutoff lockout is latched")
            raise _Fault(ALERTED, "test controller was already locked out at preflight",
                         alert=m.Alert(trip_code, 0, 0), flags=ack.flags)
        if not ack.flags & m.Flag.WATCHDOG_OK:
            raise _Fault(CONFIG, "hardware watchdog is not healthy")
        if ack.state is not m.State.SAFE:                 # a previous session left something armed: stand it down first
            mark = len(self._mcu_events)
            self._command(m.Shutdown(m.SHUTDOWN_ORDERLY))
            if not self._spin_quiet(lambda: self._event_seen(m.EventCode.SHUTDOWN_COMPLETE, mark), 0.8):
                raise _Fault(CONFIG, f"test controller would not return to the safe state ({ack.state.name})")
        self._last_hb = self._clock()

    # -- CONFIGURING -------------------------------------------------------------------------------

    def _configure(self, run: _Run) -> None:
        episode = run.episode
        self._enter(run, Phase.CONFIGURING, "protection limits and capture programmed")
        if not run.rails:
            raise _Fault(CONFIG, "the episode controls no programmable rail")
        limits = tuple(m.ChannelLimit(r.channel, round(r.max_v * 1000), round(r.max_a * 1e6),
                                      round(r.hw_slew_v_per_s * 1000)) for r in run.rails)
        self._limits_echo = None
        self._command(m.SetLimits(self.cfg.max_episode_ms, limits), tag=run.tag)
        self._spin_quiet(lambda: self._limits_echo is not None, self.cfg.ack_timeout_s)
        echo = self._limits_echo
        if echo is None or echo.limits != limits or echo.max_episode_ms != self.cfg.max_episode_ms:
            raise _Fault(CONFIG, f"SET_LIMITS read-back mismatch: sent {limits}, read back "
                                 f"{None if echo is None else echo.limits}")
        workload = episode.conditions.get("workload", "idle")
        if workload not in m.WORKLOAD_CODES:
            raise _Fault(CONFIG, f"unknown workload {workload!r}")
        plan = m.LoadPlan(m.WORKLOAD_CODES[workload], bool(episode.conditions.get("redLed", False)),
                          bool(episode.conditions.get("greenLed", False)),
                          int(episode.conditions.get("flashOffsetMs", 0)), episode.duration_ms,
                          self.cfg.observe_delay_ms, episode.seed & 0xFFFFFFFF, episode.attempt & 0xFFFF)
        self._command(plan, tag=run.tag)

    # -- SETTLING ----------------------------------------------------------------------------------

    def _energize_and_settle(self, run: _Run) -> None:
        episode = run.episode
        targets = {r.channel: float(episode.conditions[r.control]) for r in run.rails}
        for r in run.rails:
            self._command(m.SetRail(r.channel, round(targets[r.channel] * 1000), round(r.slew_v_per_s * 1000)),
                          tag=run.tag)
        run.output_risk = True               # from here on an unacknowledged ENABLE_RAIL might have worked
        for r in run.rails:
            self._command(m.EnableRail(r.channel), tag=run.tag)
        self._enter(run, Phase.SETTLING, "outputs enabled")
        ramp_s = max(targets[r.channel] / r.slew_v_per_s for r in run.rails)
        deadline = self._clock() + ramp_s + self.cfg.settle_timeout_s
        streak = 0
        while True:
            readings = self._read_all()
            self._store_readings(run, readings)
            inside = all(abs(run.last_v[r.control] - targets[r.channel]) <= self.cfg.settle_tolerance_v
                         for r in run.rails)
            streak = streak + 1 if inside else 0
            if streak >= self.cfg.settle_count:
                run.settled = True
                return
            now = self._clock()
            if now >= deadline:
                self._note(run, f"settling timeout: rail never in tolerance (last read-back "
                                f"{ {r.control: round(run.last_v[r.control], 3) for r in run.rails} } V)")
                raise _Fault(SETTLE, "rail did not settle")
            self._service()
            self._sleep(min(self.cfg.poll_interval_s, deadline - now))

    def _store_readings(self, run: _Run, readings: dict[int, m.RailReading], observing: bool = False) -> None:
        for r in run.rails:
            reading = readings.get(r.channel)
            if reading is None:
                continue
            volts, amps = self._volts(r, reading), reading.ua / 1e6
            run.last_v[r.control], run.last_a[r.control] = volts, amps
            if observing:
                run.obs_v.setdefault(r.control, []).append(volts)
                run.obs_a.setdefault(r.control, []).append(amps)

    # -- EXECUTING / OBSERVING ---------------------------------------------------------------------

    def _event_seen(self, code: m.EventCode, since: int = 0) -> bool:
        return any(e.code is code for _, e in self._mcu_events[since:])

    def _execute(self, run: _Run) -> None:
        episode = run.episode
        mark = len(self._mcu_events)
        self._obs.clear()
        self._command(m.Execute(), tag=run.tag)
        self._enter(run, Phase.EXECUTING, "rail settled; workload started")
        dwell_s = episode.duration_ms / 1000.0
        budget = self.cfg.observe_delay_ms / 1000.0 + dwell_s + 0.5
        deadline = self._clock() + budget
        observing = False
        next_read = 0.0
        while True:
            self._service()
            if not observing and self._event_seen(m.EventCode.OBSERVE_STARTED, mark):
                observing = True
                self._enter(run, Phase.OBSERVING, "observation window open")
            if self._event_seen(m.EventCode.EXEC_DONE, mark):
                break
            now = self._clock()
            if now >= deadline:
                raise _Fault(TIMEOUT, "workload did not complete: no EXEC_DONE from the test controller")
            if observing and now >= next_read:
                self._store_readings(run, self._read_all(), observing=True)
                next_read = now + max(0.1, self.cfg.poll_interval_s)
            self._sleep(min(self.cfg.poll_interval_s, max(0.001, deadline - now)))
        if not observing:                                  # DONE seen before the OBSERVE event was handled
            self._enter(run, Phase.OBSERVING, "observation window open")
        self._store_readings(run, self._read_all(), observing=True)
        run.observations = dict(self._obs)
        for _, event in self._mcu_events[mark:]:
            if event.code is m.EventCode.DUT_HEARTBEAT_LOST:
                run.heartbeat_lost = True
            elif event.code is m.EventCode.SENSOR_NO_DATA:
                run.instrument_errors.append("optical sensor: no data in observation window")
            elif event.code is m.EventCode.DUT_RESET:
                self._note(run, "DUT reset observed")

    # -- SHUTDOWN ----------------------------------------------------------------------------------

    def _ordered_shutdown(self, run: _Run) -> bool:
        """HLD 03 §12. True when the MCU confirmed and the host's own read-back agrees the rails are down."""
        previous, self._cleanup = self._cleanup, True
        try:
            mark = len(self._mcu_events)
            self._pending_alerts.clear()
            self._command(m.Shutdown(m.SHUTDOWN_ORDERLY), tag=run.tag)
            done = self._spin(lambda: self._event_seen(m.EventCode.SHUTDOWN_COMPLETE, mark)
                              or bool(self._pending_alerts) or bool(self._flags & m.Flag.LOCKED_OUT),
                              self.cfg.shutdown_timeout_s)
            if not done or self._pending_alerts or self._flags & m.Flag.LOCKED_OUT:
                self._note(run, "rail did not reach shutdown threshold in time")
                return False
            readings = self._read_all()             # verification only: the measured values stay the pre-shutdown ones
            threshold_mv = self.cfg.shutdown_threshold_v * 1000
            down = all(readings[c].mv <= threshold_mv for c in (r.channel for r in self.cfg.rails) if c in readings)
            if down:
                self._note(run, "rails at shutdown threshold")
            else:
                self._note(run, "read-back after shutdown still above the shutdown threshold")
            return down
        except _Fault as fault:
            self._note(run, f"ordered shutdown failed: {fault.detail}")
            run.instrument_errors.append(f"shutdown: {fault.detail}")
            return False
        finally:
            self._cleanup = previous

    def _cutoff(self, run: _Run, reason: str) -> None:
        """Request the hardware cutoff through the MCU and record whether the MCU confirmed it."""
        previous, self._cleanup = self._cleanup, True
        confirmed = False
        try:
            ack = self._command(m.Shutdown(m.SHUTDOWN_CUTOFF))
            confirmed = bool(ack.flags & m.Flag.CUTOFF_OPEN)
        except _Fault as fault:
            run.instrument_errors.append(f"cutoff request not acknowledged: {fault.detail}")
        finally:
            self._cleanup = previous
        run.cutoff_engaged = True
        self._enter(run, Phase.EMERGENCY_CUTOFF, "hardware cutoff opened" if confirmed else f"cutoff requested: {reason}")
        self._locked_known = True
        try:                                              # best-effort evidence that power is really gone
            self._cleanup = True
            after = self._read_all()
            self._note(run, "rails after cutoff: " + ", ".join(
                f"ch{c}={after[c].mv} mV" for c in sorted(after) if c != m.DUT_RAIL_CH))
        except _Fault:
            pass
        finally:
            self._cleanup = previous

    # -- capture construction ----------------------------------------------------------------------

    def _expected_names(self, run: _Run) -> tuple[str, ...]:
        names = ["maxHeartbeatGapMs", "resetCount", "measuredDut3v3MinV"]
        if run.episode.conditions.get("workload") == "oled_refresh":
            names.insert(0, "oledLatencyMs")
        return tuple(names)

    def _measured(self, run: _Run) -> tuple[dict[str, float], dict[str, float]]:
        volts: dict[str, float] = {}
        amps: dict[str, float] = {}
        for r in run.rails:
            if r.control in run.obs_v:
                volts[r.control] = statistics.fmean(run.obs_v[r.control])
                amps[r.current_key] = statistics.fmean(run.obs_a[r.control])
            elif r.control in run.last_v:
                volts[r.control], amps[r.current_key] = run.last_v[r.control], run.last_a[r.control]
        return volts, amps

    def _capture(self, run: _Run, *, shutdown_confirmed: bool, trip: str | None = None, observations: bool = True,
                 missing_rail: bool = False) -> RawBenchCapture:
        volts, amps = self._measured(run)
        obs = dict(run.observations) if observations else {}
        missing = [n for n in self._expected_names(run) if n not in obs]
        if missing_rail or not volts:
            missing.append(run.rails[0].measured_name if run.rails else "measuredOledRailV")
        return RawBenchCapture(
            episode_id=run.episode.episode_id, attempt=run.episode.attempt, measured_rail_v=volts,
            measured_current_a=amps, observations=obs, events=tuple(run.events), phases_reached=tuple(run.phases),
            shutdown_confirmed=shutdown_confirmed, trip=trip, cutoff_engaged=run.cutoff_engaged,
            rail_settled=run.settled, missing_observations=tuple(missing),
            instrument_errors=tuple(run.instrument_errors), heartbeat_lost=run.heartbeat_lost)

    def _finish_normal(self, run: _Run) -> RawBenchCapture:
        self._enter(run, Phase.SHUTTING_DOWN, "window complete; ordered shutdown")
        if self._ordered_shutdown(run):
            return self._capture(run, shutdown_confirmed=True)
        run.instrument_errors.append("normal shutdown failed; cutoff requested")
        self._cutoff(run, "normal shutdown failed")
        alerts = self._pending_alerts
        trip = Trip.SHUTDOWN_FAILED
        if alerts and alerts[0].code is not m.AlertCode.SHUTDOWN_FAILED:
            trip = _ALERT_TRIPS.get(alerts[0].code, Trip.INSTRUMENT_UNCERTAIN_OUTPUT)
            run.instrument_errors.append(describe_alert(alerts[0]))
        return self._capture(run, shutdown_confirmed=False, trip=trip)

    # -- failures ----------------------------------------------------------------------------------

    def _recover(self, run: _Run, fault: _Fault) -> RawBenchCapture:
        """Turn a failed step into the capture a real bench would produce. Never a fabricated success."""
        self._note(run, fault.detail)
        if fault.kind in (ALERTED, ABORTED) or (fault.kind == NACKED and fault.flags is not None
                                                 and fault.flags & (m.Flag.LOCKED_OUT | m.Flag.ESTOP)):
            return self._tripped(run, fault)
        if fault.kind == COMM:
            run.instrument_errors.append(fault.detail)
            if run.output_risk or not self._link_confirms_safe(run):
                run.instrument_errors.append("output state uncertain after loss of the link")
                self._cutoff(run, "link lost with output state uncertain")
                return self._capture(run, shutdown_confirmed=False, trip=Trip.INSTRUMENT_UNCERTAIN_OUTPUT,
                                     observations=False, missing_rail=not run.settled)
        elif fault.kind in (NACKED, CONFIG, TIMEOUT):
            run.instrument_errors.append(fault.detail)
        # Clean failure with a working link (settling timeout, NACK, bad configuration, workload timeout).
        if not run.phases or run.phases[-1] != Phase.SHUTTING_DOWN.value:
            self._enter(run, Phase.SHUTTING_DOWN,
                        "ordered shutdown after timeout" if fault.kind == SETTLE else "configuration error; ordered shutdown")
        if self._ordered_shutdown(run):
            return self._capture(run, shutdown_confirmed=True, observations=False,
                                 missing_rail=fault.kind in (SETTLE, CONFIG, NACKED) and not run.settled)
        run.instrument_errors.append("normal shutdown failed; cutoff requested")
        self._cutoff(run, "normal shutdown failed")
        trip = Trip.SHUTDOWN_FAILED if not self._pending_alerts else _ALERT_TRIPS.get(self._pending_alerts[0].code,
                                                                                        Trip.INSTRUMENT_UNCERTAIN_OUTPUT)
        return self._capture(run, shutdown_confirmed=False, trip=trip, observations=False)

    def _link_confirms_safe(self, run: _Run) -> bool:
        """After a link fault before any output was enabled: can an orderly SHUTDOWN still be confirmed?"""
        previous, self._cleanup = self._cleanup, True
        try:
            self._command(m.Shutdown(m.SHUTDOWN_ORDERLY))
            return True
        except _Fault:
            return False
        finally:
            self._cleanup = previous

    def _tripped(self, run: _Run, fault: _Fault) -> RawBenchCapture:
        alert = fault.alert
        if alert is None and fault.kind == NACKED:
            alert = m.Alert(m.AlertCode.ESTOP if fault.flags and fault.flags & m.Flag.ESTOP else m.AlertCode.WATCHDOG,
                            0, 0)
        if fault.kind == ABORTED:
            trip = Trip.INSTRUMENT_UNCERTAIN_OUTPUT
            run.instrument_errors.append(fault.detail)
        else:
            assert alert is not None
            trip = _ALERT_TRIPS.get(alert.code, Trip.INSTRUMENT_UNCERTAIN_OUTPUT)
            if trip == Trip.INSTRUMENT_UNCERTAIN_OUTPUT:
                run.instrument_errors.append(describe_alert(alert))
        for extra in self._pending_alerts[1:] if self._pending_alerts else ():
            self._note(run, describe_alert(extra))
        self._pending_alerts.clear()
        self._cutoff(run, fault.detail)
        return self._capture(run, shutdown_confirmed=False, trip=trip, observations=False)


def describe_alert(alert: m.Alert) -> str:
    unit = {m.AlertCode.OVERCURRENT: "uA", m.AlertCode.OVERVOLTAGE: "mV", m.AlertCode.OVERTEMP: "mdegC"}.get(alert.code)
    where = f" ch{alert.channel}" if alert.channel else ""
    if unit:
        return f"ALERT {alert.code.name}{where}: {alert.value} {unit} against limit {alert.limit} {unit}"
    return f"ALERT {alert.code.name}{where} at MCU t={alert.t_ms} ms"
