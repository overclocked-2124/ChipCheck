"""Bench acceptance probes over the serial link (HLD 02 §18 tests 1 and 7, HLD 10 WP9).

Each probe returns a ``ProbeResult``. Probes leave the test controller in its safe state, or report
that they could not. Only ``probe_host_loss`` energizes a rail; the CLI runs it only on request.
"""

from __future__ import annotations

from dataclasses import dataclass

from activequal.adapter.service.serial import messages as m
from activequal.adapter.service.serial.host import SerialBenchAdapter, _Fault
from activequal.adapter.service.serial.mcu_emulator import HOST_LOSS_MS

PROBE_TAG = 0x0000AC0E          # episode tag used by probes; never a real episode
SAFE_RAIL_MV = 100              # a rail below this counts as off


@dataclass(frozen=True)
class ProbeResult:
    name: str
    passed: bool
    detail: str


def _limits(max_mv: int, max_ua: int = 200_000, slew: int = 500) -> m.SetLimits:
    return m.SetLimits(5_000, (m.ChannelLimit(m.OLED_RAIL_CH, max_mv, max_ua, slew),))


def _arm(adapter: SerialBenchAdapter, max_mv: int) -> None:
    adapter._command(_limits(max_mv), tag=PROBE_TAG)
    adapter._command(m.LoadPlan(m.WORKLOAD_CODES["idle"], False, False, 0, 500, 100), tag=PROBE_TAG)


def _back_to_safe(adapter: SerialBenchAdapter) -> str | None:
    try:
        adapter._command(m.Shutdown(), tag=PROBE_TAG)
    except _Fault as fault:
        return fault.detail
    deadline = adapter._clock() + adapter.cfg.shutdown_timeout_s
    while True:                                      # wait for the shutdown ramp to finish
        health = adapter.health_check()
        if health.ok or adapter._clock() >= deadline:
            return None if health.ok else "; ".join(health.detail) or "not safe after shutdown"
        adapter._sleep(0.05)


def _rejected(adapter: SerialBenchAdapter, msg: object, reason: m.Reason) -> tuple[bool, str]:
    try:
        adapter._command(msg, tag=PROBE_TAG)
    except _Fault as fault:
        return reason.name in fault.detail, fault.detail
    return False, f"{type(msg).__name__} was accepted"


def probe_identity(adapter: SerialBenchAdapter) -> ProbeResult:
    health = adapter.health_check()
    if not health.ok:
        return ProbeResult("identity and safe state", False, "; ".join(health.detail) or "bench not ok")
    return ProbeResult("identity and safe state", True,
                       f"MCU firmware {health.mcu_firmware_sha256}, DUT firmware {health.dut_firmware_sha256}")


def probe_limits_rejected(adapter: SerialBenchAdapter, contract_max_mv: int = 3300,   # below the hardware max, so
                          # firmware that checks only the hardware max fails
                          hardware_max_mv: int = 3600) -> ProbeResult:
    """HLD 02 §18 test 1: the MCU refuses limits above its hardware maximum and setpoints above the limit.
    Nothing is energized: the rejected SET_RAIL never reaches ENABLE_RAIL."""
    name = "out-of-bounds setpoints rejected"
    try:
        ok_hw, hw = _rejected(adapter, _limits(hardware_max_mv + 100), m.Reason.OUT_OF_LIMITS)
        _arm(adapter, contract_max_mv)
        ok_sp, sp = _rejected(adapter, m.SetRail(m.OLED_RAIL_CH, contract_max_mv + 100, 500), m.Reason.OUT_OF_LIMITS)
        ok_slew, slew = _rejected(adapter, m.SetRail(m.OLED_RAIL_CH, 3300, 5_000), m.Reason.SLEW_EXCEEDED)
    except _Fault as fault:
        problem = _back_to_safe(adapter)
        return ProbeResult(name, False, f"probe failed: {fault.detail}" + (f"; {problem}" if problem else ""))
    problem = _back_to_safe(adapter)
    passed = ok_hw and ok_sp and ok_slew and problem is None
    return ProbeResult(name, passed, f"limits: {hw}; setpoint: {sp}; slew: {slew}" + (f"; {problem}" if problem else ""))


def probe_host_loss(adapter: SerialBenchAdapter, setpoint_mv: int = 3300) -> ProbeResult:
    """HLD 02 §18 test 7: energize one rail, go silent, and confirm the MCU returns it to shutdown."""
    name = "host silence returns the bench to shutdown"
    try:
        _arm(adapter, 3600)
        adapter._command(m.SetRail(m.OLED_RAIL_CH, setpoint_mv, 500), tag=PROBE_TAG)
        adapter._command(m.EnableRail(m.OLED_RAIL_CH), tag=PROBE_TAG)
    except _Fault as fault:
        adapter.emergency_shutdown()
        return ProbeResult(name, False, f"could not energize: {fault.detail}")
    adapter._sleep(1.5 * HOST_LOSS_MS / 1000 + 1.0)       # no frames at all: host loss plus the shutdown ramp
    adapter._poll(0.0)
    alerted = any(a.code is m.AlertCode.HOST_LOSS for a in adapter._pending_alerts)   # expected here
    adapter._cleanup = True                         # the HOST_LOSS alert is the evidence, not a fault
    try:
        rails = adapter._read_all()
    except _Fault as fault:
        return ProbeResult(name, False, f"no read-back after silence: {fault.detail}")
    finally:
        adapter._cleanup = False
    health = adapter.health_check()
    reading = rails.get(m.OLED_RAIL_CH)
    off = reading is not None and reading.mv < SAFE_RAIL_MV
    passed = alerted and off and adapter._state is m.State.SAFE and health.ok
    detail = (f"HOST_LOSS alert {'seen' if alerted else 'not seen'}, state {adapter._state.name}, "
              f"OLED rail {None if reading is None else reading.mv} mV")
    return ProbeResult(name, passed, detail)


def run_probes(adapter: SerialBenchAdapter, *, energize: bool = False) -> list[ProbeResult]:
    results = [probe_identity(adapter)]
    if not results[0].passed:
        return results
    results.append(probe_limits_rejected(adapter))
    if energize:
        results.append(probe_host_loss(adapter))
    return results
