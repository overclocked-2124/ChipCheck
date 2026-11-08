"""In-process emulator of the RP2040 test-controller firmware (HLD 10 WP9, HLD 02 §8, HLD 05 §9).

This is the reference implementation the firmware author ports. It speaks ``messages`` over a
``ByteStream`` using ``framing``, driven by a virtual clock: ``feed(bytes)`` delivers received bytes,
``tick(ms)`` advances time in 1 ms steps, ``pump()`` reads pending bytes from the stream. No threads,
no sleeping.

Firmware behaviour implemented here (each is a requirement for the real firmware):

* Every valid command gets exactly one ACK or NACK. A repeated seq is never executed again; the
  cached replies are re-sent (with fresh MCU sequence numbers). A seq that went backwards is dropped.
  Corrupt frames are counted and ignored and never count as host liveness.
* Limits (``SET_LIMITS``) are checked against hardware maxima, echoed back, and then enforced on every
  1 ms step: a measured over-voltage or over-current on an enabled rail opens the cutoff, latches the
  lockout and sends an ALERT. Limits can only be programmed while no rail is enabled.
* Rail outputs ramp from their present setpoint at the programmed slew, never faster than the
  channel's ``slew_max_mv_per_s``. Disabling a rail and SHUTDOWN are hard output-off, not slew limited.
* No valid frame for 1000 ms while anything is armed or energized: orderly shutdown to the safe state
  (not a lockout) and ALERT HOST_LOSS.
* E-stop and the hardware watchdog open the cutoff and latch a lockout that only ``manual_reset()``
  (the researcher's physical action) clears. ``SHUTDOWN`` is acknowledged in every state.
* Ordered shutdown: DUT workload stopped, rails disabled, rails must fall below the shutdown threshold
  within 500 ms or ALERT SHUTDOWN_FAILED opens the cutoff.

The simulated plant (first-order rail with seeded read noise, resistive loads, a DUT model) lives
here too. The DUT model reuses ``SimulatedBenchAdapter`` so the hidden fault stays inside this module;
nothing but measured values ever leaves it.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from activequal.adapter.service.simulator import SimulatedBenchAdapter
from activequal.adapter.service.types import ApprovedEpisode
from activequal.adapter.service.serial import framing, messages as m
from activequal.adapter.service.serial.stream import ByteStream, InMemoryPipe, _Endpoint

HOST_LOSS_MS = 1000
SHUTDOWN_THRESHOLD_MV = 100
SHUTDOWN_TIMEOUT_MS = 500
WATCHDOG_MS = 2000
FW_VERSION = 1


class DutFault(str, Enum):
    NONE = "none"
    SENSOR_NO_DATA = "sensor_no_data"
    HEARTBEAT_LOSS = "heartbeat_loss"


@dataclass
class HardwareLimits:
    """What the board can physically do, independent of anything the host programs."""

    max_mv: int = 3600
    max_ua: int = 200_000
    slew_max_mv_per_s: int = 2000


@dataclass
class EmulatorConfig:
    fixture_id: str = "bench-A"
    mcu_fw_sha256: str = "m" * 64
    dut_fw_sha256: str = "0" * 64
    profile: str = "B3"                  # hidden benchmark profile (HLD 06); never sent on the wire
    noise_seed: int = 0
    read_noise_mv: float = 2.0
    read_noise_ua: float = 300.0
    tau_up_ms: float = 15.0
    tau_down_ms: float = 20.0
    tau_cutoff_ms: float = 3.0
    load_ohm: dict[int, float] = field(default_factory=lambda: {m.OLED_RAIL_CH: 162.5, m.SENSOR_RAIL_CH: 6600.0})
    dut_rail_mv: int = 3300
    dut_current_ua: int = 100_000
    hardware: HardwareLimits = field(default_factory=HardwareLimits)


class _Channel:
    def __init__(self, channel: int) -> None:
        self.channel = channel
        self.enabled = False
        self.target_mv = 0
        self.target_set = False
        self.slew = 0                      # mV/s, commanded
        self.setpoint = 0.0                # mV, noise-free output setpoint (what the ramp generator is at)
        self.v = 0.0                       # mV, true rail voltage
        self.extra_ua = 0.0                # injected extra load (a short, for example)
        self.cap_mv: float | None = None   # regulator cannot exceed this (dropout fault)
        self.stuck_on = False              # output ignores disable until the cutoff opens
        self.adc_gain = 1.0
        self.adc_offset_mv = 0.0
        self.limit: m.ChannelLimit | None = None
        self.max_slew_seen = 0.0           # mV/s, largest setpoint rate observed
        self.held_mv = 0.0                 # voltage a stuck-on output keeps after a disable

    def clear_episode(self) -> None:
        self.enabled = False
        self.target_mv = 0
        self.target_set = False
        self.slew = 0
        self.setpoint = 0.0
        self.limit = None


class McuEmulator:
    def __init__(self, stream: ByteStream, config: EmulatorConfig | None = None, *, record_trace: bool = False) -> None:
        self.stream = stream
        self.cfg = config or EmulatorConfig()
        self.now_ms = 0
        self.state = m.State.SAFE
        self.channels = {ch: _Channel(ch) for ch in m.PROGRAMMABLE_CHANNELS}
        self.max_episode_ms = 0
        self.limits_set = False
        self.plan: m.LoadPlan | None = None
        self.episode_tag = 0
        self.estop = False
        self.locked_out = False
        self.cutoff_open = False
        self.watchdog_tripped = False
        self.dut_link_ok = True
        self.instruments_ok = True
        self.dut_fault = DutFault.NONE
        self.firmware_locked_up = False
        self._lockup_ms = 0
        self._rng = random.Random(self.cfg.noise_seed ^ 0x5EED)
        self._sim = SimulatedBenchAdapter(self.cfg.profile, noise_seed=self.cfg.noise_seed)
        self._decoder = framing.FrameDecoder(resync_types=[m.HELLO])
        self._tx_seq = 0
        self._last_rx_ms = 0
        self._last_cmd_seq: int | None = None
        self._last_replies: list[tuple[int, bytes]] = []
        self._exec_start = 0
        self._observe_at = 0
        self._done_at = 0
        self._observing_announced = False
        self._shutdown_start = 0
        self._energized_at: int | None = None
        self.duplicates = 0
        self.gaps = 0
        self.errors = 0
        self.executed: dict[int, int] = {}                      # command type -> times actually executed
        self.log: list[tuple[int, str]] = []
        self.sent_alerts: list[m.Alert] = []
        self.trace: list[tuple[int, int, float]] | None = [] if record_trace else None
        self.wire_log: list[tuple[int, str]] | None = None

    # ------------------------------------------------------------------ physical-world hooks (tests)

    def press_estop(self) -> None:
        self.estop = True
        self._cutoff(m.AlertCode.ESTOP, 0)

    def release_estop(self) -> None:
        self.estop = False

    def manual_reset(self) -> bool:
        """The researcher inspects the fixture and resets the interlock. Fails while E-stop is pressed."""
        if self.estop:
            return False
        self.cutoff_open = self.locked_out = self.watchdog_tripped = self.firmware_locked_up = False
        self.state = m.State.SAFE
        self._clear_episode()
        self._log("manual reset")
        return True

    def lock_up_firmware(self) -> None:
        """Main loop stops (no rx, no monitoring, no watchdog feed). The hardware watchdog fires after 2 s."""
        self.firmware_locked_up = True
        self._lockup_ms = 0

    def inject_load(self, channel: int, extra_ua: float) -> None:
        self.channels[channel].extra_ua = extra_ua

    def set_regulator_cap(self, channel: int, cap_mv: float | None) -> None:
        self.channels[channel].cap_mv = cap_mv

    def set_stuck_on(self, channel: int, stuck: bool = True) -> None:
        self.channels[channel].stuck_on = stuck

    def set_adc_error(self, channel: int, gain: float = 1.0, offset_mv: float = 0.0) -> None:
        self.channels[channel].adc_gain, self.channels[channel].adc_offset_mv = gain, offset_mv

    def true_voltage_mv(self, channel: int) -> float:
        return self.cfg.dut_rail_mv if channel == m.DUT_RAIL_CH else self.channels[channel].v

    def max_slew_seen(self, channel: int) -> float:
        return self.channels[channel].max_slew_seen

    @property
    def flags(self) -> m.Flag:
        flags = m.Flag(0)
        for cond, flag in ((self.estop, m.Flag.ESTOP), (self.locked_out, m.Flag.LOCKED_OUT),
                           (self.cutoff_open, m.Flag.CUTOFF_OPEN), (not self.watchdog_tripped, m.Flag.WATCHDOG_OK),
                           (self.dut_link_ok, m.Flag.DUT_LINK_OK), (self.instruments_ok, m.Flag.INSTRUMENTS_OK)):
            if cond:
                flags |= flag
        return flags

    # ------------------------------------------------------------------------------------ time and io

    def pump(self) -> None:
        """Read whatever the host has written (non-blocking) and process it."""
        while True:
            data = self.stream.read(4096, 0.0)
            if not data:
                return
            self.feed(data)

    def feed(self, data: bytes) -> None:
        if self.firmware_locked_up:
            return
        for event in self._decoder.feed(data):
            if isinstance(event, framing.Frame):
                self._last_rx_ms = self.now_ms
                self._handle(event)
            elif isinstance(event, framing.Duplicate):
                if event.stale:
                    self.duplicates += 1
                    self._log(f"dropped stale seq {event.frame.seq}")
                else:
                    self._last_rx_ms = self.now_ms          # a replay is a valid frame from a live host
                    self.duplicates += 1
                    self._replay(event.frame)
            elif isinstance(event, framing.Gap):
                self.gaps += event.missing
            else:
                self.errors += 1

    def tick(self, ms: int = 1) -> None:
        for _ in range(ms):
            self.now_ms += 1
            self._step()

    # ------------------------------------------------------------------------------------- emit

    def _send(self, msg_type: int, payload: bytes) -> None:
        data = framing.encode_frame(msg_type, self._tx_seq, payload, self.episode_tag)
        self._tx_seq = (self._tx_seq + 1) & 0xFFFF
        try:
            self.stream.write(data)
        except OSError:
            pass                                                # host gone: outputs are protected by timers
        if self.wire_log is not None:
            self.wire_log.append((self.now_ms, m.NAMES.get(msg_type, hex(msg_type))))

    def _reply(self, msg_type: int, payload: bytes, *, cache: bool = True) -> None:
        if cache:
            self._last_replies.append((msg_type, payload))
        self._send(msg_type, payload)

    def _ack(self, frame: framing.Frame) -> None:
        self._reply(m.ACK, m.Ack(frame.type, frame.seq, self.state, self.flags).pack())

    def _nack(self, frame: framing.Frame, reason: m.Reason) -> None:
        self._log(f"NACK {m.NAMES.get(frame.type, frame.type)} seq {frame.seq}: {reason.name}")
        self._reply(m.NACK, m.Nack(frame.type, frame.seq, reason, self.state, self.flags).pack())

    def _event(self, code: m.EventCode, arg: int = 0) -> None:
        self._send(m.EVENT, m.Event(code, self.now_ms, arg).pack())

    def _alert(self, code: m.AlertCode, channel: int = 0, value: int = 0, limit: int = 0) -> None:
        alert = m.Alert(code, channel, self.now_ms, value, limit)
        self.sent_alerts.append(alert)
        self._send(m.ALERT, alert.pack())

    def _log(self, text: str) -> None:
        self.log.append((self.now_ms, text))

    # ----------------------------------------------------------------------------- commands

    def _replay(self, frame: framing.Frame) -> None:
        if frame.seq == self._last_cmd_seq:
            for msg_type, payload in self._last_replies:
                self._send(msg_type, payload)
        # A duplicate of anything older was already answered once; nothing more to say.

    def _handle(self, frame: framing.Frame) -> None:
        self._last_cmd_seq = frame.seq
        self._last_replies = []
        if frame.type not in m.HOST_TYPES:
            self._nack(frame, m.Reason.UNKNOWN_TYPE)
            return
        try:
            msg = m.decode_host_message(frame.type, frame.payload)
        except m.MessageError as exc:
            self._log(f"bad payload: {exc}")
            self._nack(frame, m.Reason.BAD_LENGTH)
            return
        handler: Callable[[framing.Frame, object], None] = getattr(self, "_do_" + m.NAMES[frame.type].lower())
        handler(frame, msg)

    def _executed(self, frame: framing.Frame) -> None:
        self.executed[frame.type] = self.executed.get(frame.type, 0) + 1

    def _gate(self, frame: framing.Frame, *, states: tuple[m.State, ...], tag_checked: bool = True) -> bool:
        """Common admission checks. Returns True when the command may run (else a NACK was sent)."""
        if self.locked_out:
            self._nack(frame, m.Reason.LOCKED_OUT)
            return False
        if self.state not in states:
            self._nack(frame, m.Reason.BAD_STATE)
            return False
        if tag_checked and self.episode_tag and frame.episode_tag not in (0, self.episode_tag):
            self._nack(frame, m.Reason.BAD_VALUE)
            return False
        return True

    def _do_hello(self, frame: framing.Frame, msg: m.Hello) -> None:
        if msg.protocol != framing.PROTOCOL_VERSION:
            self._nack(frame, m.Reason.BAD_VERSION)
            return
        self._executed(frame)
        self._ack(frame)
        self._reply(m.STATUS, m.Identity(framing.PROTOCOL_VERSION, FW_VERSION, self.cfg.mcu_fw_sha256,
                                         self.cfg.dut_fw_sha256, self.cfg.fixture_id).pack())
        self._reply(m.STATUS, m.Counters(self.errors, self.duplicates, self.gaps).pack())

    def _do_heartbeat(self, frame: framing.Frame, msg: m.Heartbeat) -> None:
        self._executed(frame)
        self._ack(frame)

    def _do_set_limits(self, frame: framing.Frame, msg: m.SetLimits) -> None:
        if not self._gate(frame, states=(m.State.SAFE, m.State.ARMED), tag_checked=False):
            return
        hw = self.cfg.hardware
        for lim in msg.limits:
            if lim.channel not in self.channels:
                self._nack(frame, m.Reason.BAD_CHANNEL)
                return
            if not (0 < lim.max_mv <= hw.max_mv and 0 < lim.max_ua <= hw.max_ua
                    and 0 < lim.slew_max_mv_per_s <= hw.slew_max_mv_per_s):
                self._nack(frame, m.Reason.OUT_OF_LIMITS)
                return
        if not msg.limits or not 0 < msg.max_episode_ms <= 60_000:
            self._nack(frame, m.Reason.BAD_VALUE)
            return
        for ch in self.channels.values():
            ch.limit = None
        for lim in msg.limits:
            self.channels[lim.channel].limit = lim
        self.max_episode_ms = msg.max_episode_ms
        self.limits_set = True
        self._executed(frame)
        self._ack(frame)
        self._reply(m.STATUS, m.LimitsReadback(self.max_episode_ms, msg.limits).pack())

    def _do_load_plan(self, frame: framing.Frame, msg: m.LoadPlan) -> None:
        if not self._gate(frame, states=(m.State.SAFE, m.State.ARMED), tag_checked=False):
            return
        if not self.limits_set:
            self._nack(frame, m.Reason.NO_LIMITS)
            return
        if msg.dwell_ms > 60_000 or msg.observe_delay_ms > 60_000:
            self._nack(frame, m.Reason.BAD_VALUE)
            return
        self.plan = msg
        self.episode_tag = frame.episode_tag
        self.state = m.State.ARMED
        self._executed(frame)
        self._ack(frame)

    def _do_set_rail(self, frame: framing.Frame, msg: m.SetRail) -> None:
        if not self._gate(frame, states=(m.State.ARMED, m.State.ENERGIZED)):
            return
        ch = self.channels.get(msg.channel)
        if ch is None:
            self._nack(frame, m.Reason.BAD_CHANNEL)
            return
        if ch.limit is None:
            self._nack(frame, m.Reason.NO_LIMITS)
            return
        if msg.target_mv > ch.limit.max_mv:
            self._nack(frame, m.Reason.OUT_OF_LIMITS)
            return
        if not 0 < msg.slew_mv_per_s <= ch.limit.slew_max_mv_per_s:
            self._nack(frame, m.Reason.SLEW_EXCEEDED)
            return
        ch.target_mv, ch.slew, ch.target_set = msg.target_mv, msg.slew_mv_per_s, True
        self._executed(frame)
        self._ack(frame)

    def _do_enable_rail(self, frame: framing.Frame, msg: m.EnableRail) -> None:
        if self.estop:
            self._nack(frame, m.Reason.ESTOP_ACTIVE)
            return
        if not self._gate(frame, states=(m.State.ARMED, m.State.ENERGIZED)):
            return
        ch = self.channels.get(msg.channel)
        if ch is None:
            self._nack(frame, m.Reason.BAD_CHANNEL)
            return
        if not ch.target_set or self.plan is None:
            self._nack(frame, m.Reason.NO_PLAN)
            return
        ch.enabled = True
        self.state = m.State.ENERGIZED
        if self._energized_at is None:
            self._energized_at = self.now_ms
        self._executed(frame)
        self._ack(frame)
        self._event(m.EventCode.RAIL_ENABLED, ch.channel)

    def _do_disable_rail(self, frame: framing.Frame, msg: m.DisableRail) -> None:
        if self.locked_out:
            self._nack(frame, m.Reason.LOCKED_OUT)
            return
        ch = self.channels.get(msg.channel)
        if ch is None:
            self._nack(frame, m.Reason.BAD_CHANNEL)
            return
        self._disable(ch)
        self._executed(frame)
        self._ack(frame)
        self._event(m.EventCode.RAIL_DISABLED, ch.channel)

    def _do_read_all(self, frame: framing.Frame, msg: m.ReadAll) -> None:
        self._executed(frame)
        self._ack(frame)
        readings = [self._read(m.DUT_RAIL_CH)] + [self._read(c) for c in m.PROGRAMMABLE_CHANNELS]
        self._send(m.MEASUREMENT, m.RailsMeasurement(self.now_ms, tuple(readings)).pack())

    def _do_execute(self, frame: framing.Frame, msg: m.Execute) -> None:
        if not self._gate(frame, states=(m.State.ENERGIZED,)):
            return
        assert self.plan is not None
        self.state = m.State.EXECUTING
        self._exec_start = self.now_ms
        self._observe_at = self.now_ms + self.plan.observe_delay_ms
        self._done_at = self._observe_at + self.plan.dwell_ms
        self._observing_announced = False
        self._executed(frame)
        self._ack(frame)
        self._event(m.EventCode.EXEC_STARTED)

    def _do_abort(self, frame: framing.Frame, msg: m.Abort) -> None:
        if self.state is m.State.EXECUTING:
            self.state = m.State.ENERGIZED
            self._event(m.EventCode.ABORTED)
        self._executed(frame)
        self._ack(frame)

    def _do_shutdown(self, frame: framing.Frame, msg: m.Shutdown) -> None:
        self._executed(frame)
        if msg.mode == m.SHUTDOWN_CUTOFF:
            self._cutoff(None, 0, requested=True)
        elif not self.locked_out:
            self._begin_shutdown()
        self._ack(frame)

    # ---------------------------------------------------------------------------- state changes

    def _disable(self, ch: _Channel) -> None:
        if ch.enabled:
            ch.held_mv = ch.setpoint if ch.stuck_on else 0.0
        ch.enabled = False
        ch.setpoint = 0.0
        ch.target_mv = 0
        ch.target_set = False

    def _clear_episode(self) -> None:
        for ch in self.channels.values():
            ch.clear_episode()
        self.limits_set = False
        self.plan = None
        self.episode_tag = 0
        self._energized_at = None

    def _begin_shutdown(self) -> None:
        """Ordered shutdown: stop the workload, signal paths off, rails off, then confirm below threshold."""
        if self.state is m.State.SHUTTING_DOWN:
            return
        was_active = any(ch.enabled for ch in self.channels.values()) or self.state not in (m.State.SAFE,)
        for ch in self.channels.values():
            if ch.enabled:
                self._event(m.EventCode.RAIL_DISABLED, ch.channel)
            self._disable(ch)
        self.state = m.State.SHUTTING_DOWN
        self._shutdown_start = self.now_ms
        self._log("shutdown started" if was_active else "shutdown (idle)")

    def _cutoff(self, code: m.AlertCode | None, channel: int, value: int = 0, limit: int = 0, *,
                requested: bool = False) -> None:
        """Open the hardware cutoff: all programmable power removed at once, lockout latched."""
        if self.locked_out and not requested:
            return
        already = self.locked_out
        self.cutoff_open = self.locked_out = True
        for ch in self.channels.values():
            self._disable(ch)
            ch.held_mv = 0.0                                     # the cutoff removes power even from a stuck output
        self._clear_episode()
        self.state = m.State.LOCKED_OUT
        if code is not None:
            self._alert(code, channel, value, limit)
        if not already:
            self._event(m.EventCode.CUTOFF_OPENED)
        self._log(f"cutoff opened ({code.name if code else 'host request'})")

    # ------------------------------------------------------------------------------ one ms step

    def _step(self) -> None:
        if self.firmware_locked_up:
            self._lockup_ms += 1
            self._plant_step()
            if self._lockup_ms >= WATCHDOG_MS:                  # hardware watchdog bites: reboot into lockout
                self.firmware_locked_up = False
                self.watchdog_tripped = True
                self._cutoff(m.AlertCode.WATCHDOG, 0)
            return
        self._ramp_step()
        self._plant_step()
        self._monitor()
        if self.state is m.State.EXECUTING:
            self._execution_step()
        elif self.state is m.State.SHUTTING_DOWN:
            self._shutdown_step()
        if (self.state not in (m.State.SAFE, m.State.LOCKED_OUT, m.State.SHUTTING_DOWN)
                and self.now_ms - self._last_rx_ms > HOST_LOSS_MS):
            self._alert(m.AlertCode.HOST_LOSS)
            self._event(m.EventCode.HOST_LOSS_SHUTDOWN)
            self._begin_shutdown()
        if (self._energized_at is not None and self.state not in (m.State.LOCKED_OUT, m.State.SHUTTING_DOWN)
                and self.now_ms - self._energized_at > self.max_episode_ms):
            self._cutoff(m.AlertCode.EPISODE_TIMEOUT, 0, self.now_ms - self._energized_at, self.max_episode_ms)
        if self.state is m.State.ENERGIZED or self.state is m.State.COMPLETE:
            if not any(ch.enabled for ch in self.channels.values()):
                self.state = m.State.ARMED

    def _ramp_step(self) -> None:
        for ch in self.channels.values():
            if not ch.enabled:
                continue
            assert ch.limit is not None
            rate = min(ch.slew, ch.limit.slew_max_mv_per_s)     # the programmed limit always wins
            step = rate / 1000.0
            before = ch.setpoint
            if ch.setpoint < ch.target_mv:
                ch.setpoint = min(ch.setpoint + step, float(ch.target_mv))
            elif ch.setpoint > ch.target_mv:
                ch.setpoint = max(ch.setpoint - step, float(ch.target_mv))
            observed = abs(ch.setpoint - before) * 1000.0
            if observed > ch.max_slew_seen:
                ch.max_slew_seen = observed
            if self.trace is not None and ch.setpoint != before:
                self.trace.append((self.now_ms, ch.channel, ch.setpoint))

    def _plant_step(self) -> None:
        for ch in self.channels.values():
            if self.cutoff_open:
                goal, tau = 0.0, self.cfg.tau_cutoff_ms
            elif ch.enabled or ch.held_mv:
                goal = ch.setpoint if ch.enabled else ch.held_mv
                if ch.cap_mv is not None:
                    goal = min(goal, ch.cap_mv)
                tau = self.cfg.tau_up_ms if goal >= ch.v else self.cfg.tau_down_ms
            else:
                goal, tau = 0.0, self.cfg.tau_down_ms
            ch.v += (goal - ch.v) * (1.0 - math.exp(-1.0 / tau))
            if ch.v < 0.01:
                ch.v = 0.0

    def _load_ua(self, ch: _Channel) -> float:
        return ch.v / 1000.0 / self.cfg.load_ohm[ch.channel] * 1e6 + (ch.extra_ua if ch.v > 50 else 0.0)

    def _monitor(self) -> None:
        for ch in self.channels.values():
            if not ch.enabled or ch.limit is None or self.locked_out:
                continue
            seen_mv = ch.v * ch.adc_gain + ch.adc_offset_mv
            if seen_mv > ch.limit.max_mv:
                self._cutoff(m.AlertCode.OVERVOLTAGE, ch.channel, round(seen_mv), ch.limit.max_mv)
                return
            current = self._load_ua(ch)
            if current > ch.limit.max_ua:
                self._cutoff(m.AlertCode.OVERCURRENT, ch.channel, round(current), ch.limit.max_ua)
                return

    def _shutdown_step(self) -> None:
        if all(ch.v <= SHUTDOWN_THRESHOLD_MV for ch in self.channels.values()):
            self.state = m.State.SAFE
            self._clear_episode()
            self._event(m.EventCode.SHUTDOWN_COMPLETE)
        elif self.now_ms - self._shutdown_start > SHUTDOWN_TIMEOUT_MS:
            worst = max(self.channels.values(), key=lambda c: c.v)
            self._cutoff(m.AlertCode.SHUTDOWN_FAILED, worst.channel, round(worst.v), SHUTDOWN_THRESHOLD_MV)

    # -------------------------------------------------------------------------------- the DUT

    def _execution_step(self) -> None:
        assert self.plan is not None
        if not self._observing_announced and self.now_ms >= self._observe_at:
            self._observing_announced = True
            self._event(m.EventCode.OBSERVE_STARTED)
        if self.now_ms >= self._done_at:
            self._finish_execution()

    def _finish_execution(self) -> None:
        plan = self.plan
        assert plan is not None
        oled_mv = self.channels[m.OLED_RAIL_CH].v
        observations: dict[str, float] = {}
        if oled_mv >= 2900 and self.dut_link_ok:
            index = min(60, max(0, round((oled_mv / 1000.0 - 3.00) / 0.01)))
            conditions = {"oledRailV": round(3.00 + 0.01 * index, 2), "redLed": plan.red_led,
                          "greenLed": plan.green_led, "workload": m.WORKLOAD_NAMES[plan.workload],
                          "dwellMs": plan.dwell_ms}
            episode = ApprovedEpisode(episode_id=str(self.episode_tag), attempt=plan.attempt,
                                      contract_hash="", fixture_id=self.cfg.fixture_id, conditions=conditions,
                                      duration_ms=plan.dwell_ms, seed=plan.episode_seed)
            observations = dict(self._sim.apply_and_measure(episode).observations)   # the hidden fault acts here
            if self.dut_fault is DutFault.HEARTBEAT_LOSS:
                observations.pop("oledLatencyMs", None)
                observations["maxHeartbeatGapMs"] = float(plan.dwell_ms)
                observations["resetCount"] = 0.0
                self._event(m.EventCode.DUT_HEARTBEAT_LOST)
            elif self.dut_fault is DutFault.SENSOR_NO_DATA and "oledLatencyMs" in observations:
                del observations["oledLatencyMs"]
                self._event(m.EventCode.SENSOR_NO_DATA, int(m.ObsId.OLED_LATENCY_MS))
            if observations.get("resetCount", 0.0) > 0:
                self._event(m.EventCode.DUT_RESET)
        else:
            self._event(m.EventCode.DUT_HEARTBEAT_LOST)
        for name, value in observations.items():
            self._send(m.MEASUREMENT, m.Observation(self.now_ms, m.OBS_IDS[name], value).pack())
        self.state = m.State.COMPLETE
        self._event(m.EventCode.EXEC_DONE)

    # ----------------------------------------------------------------------------------- readings

    def _read(self, channel: int) -> m.RailReading:
        if channel == m.DUT_RAIL_CH:
            mv = self.cfg.dut_rail_mv + self._rng.gauss(0, self.cfg.read_noise_mv)
            ua = self.cfg.dut_current_ua + self._rng.gauss(0, self.cfg.read_noise_ua)
            return m.RailReading(channel, round(mv), round(ua), self.cfg.dut_rail_mv, True, False)
        ch = self.channels[channel]
        mv = ch.v * ch.adc_gain + ch.adc_offset_mv + self._rng.gauss(0, self.cfg.read_noise_mv)
        ua = self._load_ua(ch) + self._rng.gauss(0, self.cfg.read_noise_ua)
        ramping = ch.enabled and abs(ch.setpoint - ch.target_mv) > 0.5
        return m.RailReading(channel, round(mv), round(ua), round(ch.setpoint), ch.enabled, ramping)


# ------------------------------------------------------------------------------------ loopback

class VirtualClock:
    """One clock for the whole simulated bench: the host's sleep, its reads and the MCU all use it."""

    def __init__(self) -> None:
        self.now_ms = 0

    def now(self) -> float:
        return self.now_ms / 1000.0


class Loopback:
    """A host byte stream wired to a ``McuEmulator`` through an ``InMemoryPipe`` on one virtual clock.

    Writing delivers bytes to the emulator at once. ``read`` with nothing pending advances virtual
    time 1 ms at a time, up to the timeout, until a byte arrives, so ack timeouts, heartbeats and ramps
    are exact and the test suite never sleeps. ``sleep`` and ``now`` plug into ``SerialBenchAdapter``.
    """

    def __init__(self, config: EmulatorConfig | None = None, *, record_trace: bool = False,
                 mcu_stream_wrapper: Callable[[ByteStream], ByteStream] | None = None) -> None:
        self.clock = VirtualClock()
        self.pipe = InMemoryPipe()
        host_end: _Endpoint = self.pipe.a
        mcu_end: _Endpoint = self.pipe.b
        mcu_stream: ByteStream = mcu_stream_wrapper(mcu_end) if mcu_stream_wrapper else mcu_end
        self.emulator = McuEmulator(mcu_stream, config, record_trace=record_trace)
        self.host_stream: _Endpoint = host_end
        mcu_end.on_write = self.emulator.pump
        host_end.on_idle = self._idle

    def advance_ms(self, ms: int) -> None:
        for _ in range(ms):
            self.clock.now_ms += 1
            self.emulator.tick(1)

    def _idle(self, timeout_s: float) -> None:
        for _ in range(max(1, round(timeout_s * 1000))):
            self.advance_ms(1)
            if self.host_stream.pending():
                return

    def sleep(self, seconds: float) -> None:
        self.advance_ms(max(0, round(seconds * 1000)))

    def now(self) -> float:
        return self.clock.now()
