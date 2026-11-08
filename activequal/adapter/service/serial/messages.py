"""Message set and payload layouts of the test-controller protocol (HLD 05 §9.2).

This module is the wire specification the firmware implements. All integers are little-endian and
fixed width; voltages are millivolts, currents are microamperes, times are milliseconds on the
sender's own clock (``t_ms`` is the MCU's uptime since power-up, u32, wraps after 49 days).
Channel ids: 1 = fixed DUT 3.3 V rail (monitor only), 2 = ``supply.ch2`` (OLED rail),
3 = ``supply.ch3`` (sensor rail). Payload sizes below are exact; any other length is a NACK(BAD_LENGTH).

Host -> MCU (type = u8)::

    0x01 HELLO       protocol u8 | host_caps u32                          (5)   resets seq tracking
    0x02 HEARTBEAT   host_ms u32                                          (4)
    0x03 SET_LIMITS  max_episode_ms u32 | count u8 | count x LIMIT        (5+13n)
                     LIMIT = channel u8 | max_mv u32 | max_ua u32 | slew_max_mv_per_s u32
    0x04 LOAD_PLAN   workload u8 | red u8 | green u8 | flash_offset_ms u16 | dwell_ms u32 |
                     observe_delay_ms u32 | episode_seed u32 | attempt u16   (19)
    0x05 SET_RAIL    channel u8 | target_mv u32 | slew_mv_per_s u32        (9)
    0x06 ENABLE_RAIL channel u8                                           (1)
    0x07 DISABLE_RAIL channel u8                                          (1)
    0x08 READ_ALL    (empty)                                              (0)
    0x09 EXECUTE     (empty)                                              (0)
    0x0A ABORT       (empty)                                              (0)
    0x0B SHUTDOWN    mode u8   0 = ORDERLY (ordered shutdown), 1 = CUTOFF (open the hardware
                     cutoff and latch lockout)                            (1)

MCU -> host::

    0x81 ACK         cmd_type u8 | cmd_seq u16 | state u8 | flags u8      (5)
    0x82 NACK        cmd_type u8 | cmd_seq u16 | reason u8 | state u8 | flags u8   (6)
    0x83 MEASUREMENT kind u8 | t_ms u32 | body
                       kind 1 RAILS: count u8 | count x RAIL
                           RAIL = channel u8 | mv i32 | ua i32 | setpoint_mv u32 | rflags u8
                           rflags bit0 enabled, bit1 ramping
                       kind 2 OBSERVATION: obs_id u8 | value_milli i32     (value x 1000, rounded)
    0x84 EVENT       code u8 | t_ms u32 | arg i32                          (9)
    0x85 STATUS      kind u8 | body
                       kind 1 IDENTITY: protocol u8 | fw_version u16 | mcu_fw_sha256 ascii[64] |
                                        dut_fw_sha256 ascii[64] | fixture_id ascii[16]
                                        (text fields NUL padded; 64 characters cover a hex SHA-256)
                       kind 2 LIMITS:   same body as SET_LIMITS (the read-back echo)
                       kind 3 COUNTERS: rx_errors u16 | rx_duplicates u16 | rx_gaps u16
    0x86 ALERT       code u8 | channel u8 | t_ms u32 | value i32 | limit i32   (14)
                       value/limit are mV for voltage, uA for current, milli-degC for temperature,
                       and 0 for the other codes.

``flags`` (ACK/NACK) bit0 E-stop pressed, bit1 locked out, bit2 cutoff open, bit3 hardware
watchdog healthy, bit4 DUT link healthy, bit5 instruments healthy.

Every host command gets exactly one ACK or NACK carrying the command's type and seq. A repeated
seq (a retry after a lost ACK) is not executed again: the MCU re-sends its cached ACK/NACK.
Replies to HELLO: ACK, then STATUS IDENTITY and STATUS COUNTERS. SET_LIMITS: ACK, then STATUS LIMITS
(read-back). READ_ALL: ACK, then MEASUREMENT RAILS. EXECUTE: ACK now; EVENTs and MEASUREMENT
OBSERVATIONs follow, ending with EVENT EXEC_DONE. ALERTs are unsolicited.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
from typing import Any

# --------------------------------------------------------------------------- type codes

HELLO, HEARTBEAT, SET_LIMITS, LOAD_PLAN, SET_RAIL, ENABLE_RAIL, DISABLE_RAIL = 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07
READ_ALL, EXECUTE, ABORT, SHUTDOWN = 0x08, 0x09, 0x0A, 0x0B
ACK, NACK, MEASUREMENT, EVENT, STATUS, ALERT = 0x81, 0x82, 0x83, 0x84, 0x85, 0x86

HOST_TYPES = frozenset(range(0x01, 0x0C))
MCU_TYPES = frozenset(range(0x81, 0x87))
NAMES = {HELLO: "HELLO", HEARTBEAT: "HEARTBEAT", SET_LIMITS: "SET_LIMITS", LOAD_PLAN: "LOAD_PLAN",
         SET_RAIL: "SET_RAIL", ENABLE_RAIL: "ENABLE_RAIL", DISABLE_RAIL: "DISABLE_RAIL", READ_ALL: "READ_ALL",
         EXECUTE: "EXECUTE", ABORT: "ABORT", SHUTDOWN: "SHUTDOWN", ACK: "ACK", NACK: "NACK",
         MEASUREMENT: "MEASUREMENT", EVENT: "EVENT", STATUS: "STATUS", ALERT: "ALERT"}

DUT_RAIL_CH, OLED_RAIL_CH, SENSOR_RAIL_CH = 1, 2, 3
PROGRAMMABLE_CHANNELS = (OLED_RAIL_CH, SENSOR_RAIL_CH)


class State(IntEnum):
    SAFE = 0            # outputs in shutdown state; ready for a new episode
    ARMED = 1           # limits programmed and plan loaded
    ENERGIZED = 2       # at least one programmable rail enabled
    EXECUTING = 3       # event template running
    COMPLETE = 4        # execution finished, results available, rails still on
    LOCKED_OUT = 5      # cutoff open; only a manual reset leaves this state
    SHUTTING_DOWN = 6   # ordered shutdown in progress; becomes SAFE when the rails reach the threshold


class Flag(IntFlag):
    ESTOP = 1
    LOCKED_OUT = 2
    CUTOFF_OPEN = 4
    WATCHDOG_OK = 8
    DUT_LINK_OK = 16
    INSTRUMENTS_OK = 32


class Reason(IntEnum):
    UNKNOWN_TYPE = 1
    BAD_LENGTH = 2
    BAD_VALUE = 3
    BAD_STATE = 4
    OUT_OF_LIMITS = 5
    LOCKED_OUT = 6
    NO_LIMITS = 7
    BAD_CHANNEL = 8
    SLEW_EXCEEDED = 9
    NO_PLAN = 10
    ESTOP_ACTIVE = 11
    BAD_VERSION = 12


class EventCode(IntEnum):
    RAIL_ENABLED = 1        # arg = channel
    RAIL_DISABLED = 2       # arg = channel
    EXEC_STARTED = 3
    OBSERVE_STARTED = 4
    EXEC_DONE = 5
    SHUTDOWN_COMPLETE = 6
    ABORTED = 7
    DUT_HEARTBEAT_LOST = 8
    DUT_RESET = 9
    SENSOR_NO_DATA = 10     # arg = obs_id that could not be captured
    HOST_LOSS_SHUTDOWN = 11
    CUTOFF_OPENED = 12


class AlertCode(IntEnum):
    OVERCURRENT = 1
    OVERVOLTAGE = 2
    ESTOP = 3
    HOST_LOSS = 4           # no valid frame for 1 s: outputs moved to shutdown (not a lockout)
    WATCHDOG = 5            # hardware watchdog expired (firmware lockup): cutoff and lockout
    OVERTEMP = 6
    SHUTDOWN_FAILED = 7     # a rail did not reach the shutdown threshold: cutoff and lockout
    EPISODE_TIMEOUT = 8     # max_episode_ms exceeded: cutoff and lockout


class ObsId(IntEnum):
    OLED_LATENCY_MS = 1
    MAX_HEARTBEAT_GAP_MS = 2
    RESET_COUNT = 3
    DUT_3V3_MIN_V = 4


OBS_NAMES = {ObsId.OLED_LATENCY_MS: "oledLatencyMs", ObsId.MAX_HEARTBEAT_GAP_MS: "maxHeartbeatGapMs",
             ObsId.RESET_COUNT: "resetCount", ObsId.DUT_3V3_MIN_V: "measuredDut3v3MinV"}
OBS_IDS = {name: oid for oid, name in OBS_NAMES.items()}
OBS_SCALE = 1000                                    # value_milli = round(value * 1000)

WORKLOAD_CODES = {"idle": 0, "oled_refresh": 1, "sensor_read": 2, "wifi_tx": 3, "flash_write": 4}
WORKLOAD_NAMES = {code: name for name, code in WORKLOAD_CODES.items()}

SHUTDOWN_ORDERLY, SHUTDOWN_CUTOFF = 0, 1
STATUS_IDENTITY, STATUS_LIMITS, STATUS_COUNTERS = 1, 2, 3
MEAS_RAILS, MEAS_OBSERVATION = 1, 2
RAIL_ENABLED, RAIL_RAMPING = 1, 2


class MessageError(ValueError):
    """A payload that does not match its layout; the receiver answers NACK or drops it."""


def _check(payload: bytes, size: int, name: str) -> None:
    if len(payload) != size:
        raise MessageError(f"{name}: payload is {len(payload)} bytes, expected {size}")


def _enum(enum_type: Any, value: int, name: str) -> Any:
    try:
        return enum_type(value)
    except ValueError:
        raise MessageError(f"{name}: invalid value {value}") from None


def _text(value: str, width: int, name: str) -> bytes:
    raw = value.encode("ascii")
    if len(raw) > width:
        raise MessageError(f"{name}: longer than {width} characters")
    return raw.ljust(width, b"\x00")


def _untext(raw: bytes) -> str:
    return raw.rstrip(b"\x00").decode("ascii", errors="replace")


# ----------------------------------------------------------------------------- host -> MCU

@dataclass(frozen=True)
class Hello:
    protocol: int = 1
    host_caps: int = 0
    TYPE = HELLO

    def pack(self) -> bytes:
        return struct.pack("<BI", self.protocol, self.host_caps)

    @classmethod
    def unpack(cls, p: bytes) -> "Hello":
        _check(p, 5, "HELLO")
        return cls(*struct.unpack("<BI", p))


@dataclass(frozen=True)
class Heartbeat:
    host_ms: int = 0
    TYPE = HEARTBEAT

    def pack(self) -> bytes:
        return struct.pack("<I", self.host_ms & 0xFFFFFFFF)

    @classmethod
    def unpack(cls, p: bytes) -> "Heartbeat":
        _check(p, 4, "HEARTBEAT")
        return cls(*struct.unpack("<I", p))


@dataclass(frozen=True)
class ChannelLimit:
    channel: int
    max_mv: int
    max_ua: int
    slew_max_mv_per_s: int


def _pack_limits(max_episode_ms: int, limits: tuple[ChannelLimit, ...]) -> bytes:
    if len(limits) > 8:
        raise MessageError("SET_LIMITS: at most 8 channels")
    out = struct.pack("<IB", max_episode_ms, len(limits))
    for lim in limits:
        out += struct.pack("<BIII", lim.channel, lim.max_mv, lim.max_ua, lim.slew_max_mv_per_s)
    return out


def _unpack_limits(p: bytes, name: str) -> tuple[int, tuple[ChannelLimit, ...]]:
    if len(p) < 5:
        raise MessageError(f"{name}: too short")
    max_episode_ms, count = struct.unpack("<IB", p[:5])
    _check(p, 5 + 13 * count, name)
    limits = tuple(ChannelLimit(*struct.unpack("<BIII", p[5 + 13 * i:18 + 13 * i])) for i in range(count))
    channels = [lim.channel for lim in limits]
    if len(set(channels)) != len(channels) or 0 in channels:
        raise MessageError(f"{name}: duplicate or zero channel id")
    return max_episode_ms, limits


@dataclass(frozen=True)
class SetLimits:
    max_episode_ms: int
    limits: tuple[ChannelLimit, ...]
    TYPE = SET_LIMITS

    def pack(self) -> bytes:
        return _pack_limits(self.max_episode_ms, self.limits)

    @classmethod
    def unpack(cls, p: bytes) -> "SetLimits":
        return cls(*_unpack_limits(p, "SET_LIMITS"))


@dataclass(frozen=True)
class LoadPlan:
    workload: int
    red_led: bool
    green_led: bool
    flash_offset_ms: int
    dwell_ms: int
    observe_delay_ms: int
    episode_seed: int = 0
    attempt: int = 0
    TYPE = LOAD_PLAN

    def pack(self) -> bytes:
        if self.workload not in WORKLOAD_NAMES:
            raise MessageError(f"LOAD_PLAN: unknown workload {self.workload}")
        return struct.pack("<BBBHIIIH", self.workload, int(self.red_led), int(self.green_led), self.flash_offset_ms,
                           self.dwell_ms, self.observe_delay_ms, self.episode_seed & 0xFFFFFFFF, self.attempt)

    @classmethod
    def unpack(cls, p: bytes) -> "LoadPlan":
        _check(p, 19, "LOAD_PLAN")
        workload, red, green, flash, dwell, delay, seed, attempt = struct.unpack("<BBBHIIIH", p)
        if workload not in WORKLOAD_NAMES or red > 1 or green > 1:
            raise MessageError("LOAD_PLAN: invalid workload or LED value")
        return cls(workload, bool(red), bool(green), flash, dwell, delay, seed, attempt)


@dataclass(frozen=True)
class SetRail:
    channel: int
    target_mv: int
    slew_mv_per_s: int
    TYPE = SET_RAIL

    def pack(self) -> bytes:
        return struct.pack("<BII", self.channel, self.target_mv, self.slew_mv_per_s)

    @classmethod
    def unpack(cls, p: bytes) -> "SetRail":
        _check(p, 9, "SET_RAIL")
        return cls(*struct.unpack("<BII", p))


@dataclass(frozen=True)
class EnableRail:
    channel: int
    TYPE = ENABLE_RAIL

    def pack(self) -> bytes:
        return struct.pack("<B", self.channel)

    @classmethod
    def unpack(cls, p: bytes) -> "EnableRail":
        _check(p, 1, "ENABLE_RAIL")
        return cls(p[0])


@dataclass(frozen=True)
class DisableRail:
    channel: int
    TYPE = DISABLE_RAIL

    def pack(self) -> bytes:
        return struct.pack("<B", self.channel)

    @classmethod
    def unpack(cls, p: bytes) -> "DisableRail":
        _check(p, 1, "DISABLE_RAIL")
        return cls(p[0])


@dataclass(frozen=True)
class ReadAll:
    TYPE = READ_ALL

    def pack(self) -> bytes:
        return b""

    @classmethod
    def unpack(cls, p: bytes) -> "ReadAll":
        _check(p, 0, "READ_ALL")
        return cls()


@dataclass(frozen=True)
class Execute:
    TYPE = EXECUTE

    def pack(self) -> bytes:
        return b""

    @classmethod
    def unpack(cls, p: bytes) -> "Execute":
        _check(p, 0, "EXECUTE")
        return cls()


@dataclass(frozen=True)
class Abort:
    TYPE = ABORT

    def pack(self) -> bytes:
        return b""

    @classmethod
    def unpack(cls, p: bytes) -> "Abort":
        _check(p, 0, "ABORT")
        return cls()


@dataclass(frozen=True)
class Shutdown:
    mode: int = SHUTDOWN_ORDERLY
    TYPE = SHUTDOWN

    def pack(self) -> bytes:
        return struct.pack("<B", self.mode)

    @classmethod
    def unpack(cls, p: bytes) -> "Shutdown":
        _check(p, 1, "SHUTDOWN")
        if p[0] not in (SHUTDOWN_ORDERLY, SHUTDOWN_CUTOFF):
            raise MessageError(f"SHUTDOWN: invalid mode {p[0]}")
        return cls(p[0])


# ----------------------------------------------------------------------------- MCU -> host

@dataclass(frozen=True)
class Ack:
    cmd_type: int
    cmd_seq: int
    state: State
    flags: Flag
    TYPE = ACK

    def pack(self) -> bytes:
        return struct.pack("<BHBB", self.cmd_type, self.cmd_seq, int(self.state), int(self.flags))

    @classmethod
    def unpack(cls, p: bytes) -> "Ack":
        _check(p, 5, "ACK")
        cmd, seq, state, flags = struct.unpack("<BHBB", p)
        return cls(cmd, seq, _enum(State, state, "ACK.state"), Flag(flags & 0x3F))


@dataclass(frozen=True)
class Nack:
    cmd_type: int
    cmd_seq: int
    reason: Reason
    state: State
    flags: Flag
    TYPE = NACK

    def pack(self) -> bytes:
        return struct.pack("<BHBBB", self.cmd_type, self.cmd_seq, int(self.reason), int(self.state), int(self.flags))

    @classmethod
    def unpack(cls, p: bytes) -> "Nack":
        _check(p, 6, "NACK")
        cmd, seq, reason, state, flags = struct.unpack("<BHBBB", p)
        return cls(cmd, seq, _enum(Reason, reason, "NACK.reason"), _enum(State, state, "NACK.state"),
                   Flag(flags & 0x3F))


@dataclass(frozen=True)
class RailReading:
    channel: int
    mv: int
    ua: int
    setpoint_mv: int
    enabled: bool
    ramping: bool


@dataclass(frozen=True)
class RailsMeasurement:
    t_ms: int
    rails: tuple[RailReading, ...]
    TYPE = MEASUREMENT

    def pack(self) -> bytes:
        out = struct.pack("<BIB", MEAS_RAILS, self.t_ms, len(self.rails))
        for r in self.rails:
            out += struct.pack("<BiiIB", r.channel, r.mv, r.ua, r.setpoint_mv,
                               (RAIL_ENABLED if r.enabled else 0) | (RAIL_RAMPING if r.ramping else 0))
        return out


@dataclass(frozen=True)
class Observation:
    t_ms: int
    obs_id: ObsId
    value: float                # engineering units (the wire carries value x 1000 as i32)
    TYPE = MEASUREMENT

    def pack(self) -> bytes:
        return struct.pack("<BIBi", MEAS_OBSERVATION, self.t_ms, int(self.obs_id), round(self.value * OBS_SCALE))


def unpack_measurement(p: bytes) -> RailsMeasurement | Observation:
    if len(p) < 6:
        raise MessageError("MEASUREMENT: too short")
    kind, t_ms = struct.unpack("<BI", p[:5])
    if kind == MEAS_RAILS:
        count = p[5]
        _check(p, 6 + 14 * count, "MEASUREMENT.rails")
        rails = []
        for i in range(count):
            ch, mv, ua, sp, fl = struct.unpack("<BiiIB", p[6 + 14 * i:20 + 14 * i])
            rails.append(RailReading(ch, mv, ua, sp, bool(fl & RAIL_ENABLED), bool(fl & RAIL_RAMPING)))
        return RailsMeasurement(t_ms, tuple(rails))
    if kind == MEAS_OBSERVATION:
        _check(p, 10, "MEASUREMENT.observation")
        obs_id, milli = struct.unpack("<Bi", p[5:])
        return Observation(t_ms, _enum(ObsId, obs_id, "MEASUREMENT.obs_id"), milli / OBS_SCALE)
    raise MessageError(f"MEASUREMENT: unknown kind {kind}")


@dataclass(frozen=True)
class Event:
    code: EventCode
    t_ms: int
    arg: int = 0
    TYPE = EVENT

    def pack(self) -> bytes:
        return struct.pack("<BIi", int(self.code), self.t_ms, self.arg)

    @classmethod
    def unpack(cls, p: bytes) -> "Event":
        _check(p, 9, "EVENT")
        code, t_ms, arg = struct.unpack("<BIi", p)
        return cls(_enum(EventCode, code, "EVENT.code"), t_ms, arg)


@dataclass(frozen=True)
class Alert:
    code: AlertCode
    channel: int
    t_ms: int
    value: int = 0
    limit: int = 0
    TYPE = ALERT

    def pack(self) -> bytes:
        return struct.pack("<BBIii", int(self.code), self.channel, self.t_ms, self.value, self.limit)

    @classmethod
    def unpack(cls, p: bytes) -> "Alert":
        _check(p, 14, "ALERT")
        code, ch, t_ms, value, limit = struct.unpack("<BBIii", p)
        return cls(_enum(AlertCode, code, "ALERT.code"), ch, t_ms, value, limit)


@dataclass(frozen=True)
class Identity:
    protocol: int
    fw_version: int
    mcu_fw_sha256: str
    dut_fw_sha256: str
    fixture_id: str

    def pack(self) -> bytes:
        return (struct.pack("<BBH", STATUS_IDENTITY, self.protocol, self.fw_version)
                + _text(self.mcu_fw_sha256, 64, "mcu_fw_sha256") + _text(self.dut_fw_sha256, 64, "dut_fw_sha256")
                + _text(self.fixture_id, 16, "fixture_id"))


@dataclass(frozen=True)
class LimitsReadback:
    max_episode_ms: int
    limits: tuple[ChannelLimit, ...]

    def pack(self) -> bytes:
        return bytes([STATUS_LIMITS]) + _pack_limits(self.max_episode_ms, self.limits)


@dataclass(frozen=True)
class Counters:
    rx_errors: int
    rx_duplicates: int
    rx_gaps: int

    def pack(self) -> bytes:
        return struct.pack("<BHHH", STATUS_COUNTERS, self.rx_errors & 0xFFFF, self.rx_duplicates & 0xFFFF,
                           self.rx_gaps & 0xFFFF)


def unpack_status(p: bytes) -> Identity | LimitsReadback | Counters:
    if not p:
        raise MessageError("STATUS: empty")
    kind, body = p[0], p[1:]
    if kind == STATUS_IDENTITY:
        _check(body, 3 + 64 + 64 + 16, "STATUS.identity")
        protocol, version = struct.unpack("<BH", body[:3])
        return Identity(protocol, version, _untext(body[3:67]), _untext(body[67:131]), _untext(body[131:147]))
    if kind == STATUS_LIMITS:
        return LimitsReadback(*_unpack_limits(body, "STATUS.limits"))
    if kind == STATUS_COUNTERS:
        _check(body, 6, "STATUS.counters")
        return Counters(*struct.unpack("<HHH", body))
    raise MessageError(f"STATUS: unknown kind {kind}")


_HOST_DECODERS = {HELLO: Hello, HEARTBEAT: Heartbeat, SET_LIMITS: SetLimits, LOAD_PLAN: LoadPlan, SET_RAIL: SetRail,
                  ENABLE_RAIL: EnableRail, DISABLE_RAIL: DisableRail, READ_ALL: ReadAll, EXECUTE: Execute,
                  ABORT: Abort, SHUTDOWN: Shutdown}
_MCU_DECODERS = {ACK: Ack, NACK: Nack, EVENT: Event, ALERT: Alert}


def decode_host_message(msg_type: int, payload: bytes) -> Any:
    """Parse a host -> MCU payload. Raises ``MessageError`` for a bad layout, ``KeyError`` for an unknown type."""
    return _HOST_DECODERS[msg_type].unpack(payload)


def decode_mcu_message(msg_type: int, payload: bytes) -> Any:
    """Parse an MCU -> host payload. Raises ``MessageError`` for a bad layout, ``KeyError`` for an unknown type."""
    if msg_type == MEASUREMENT:
        return unpack_measurement(payload)
    if msg_type == STATUS:
        return unpack_status(payload)
    return _MCU_DECODERS[msg_type].unpack(payload)
