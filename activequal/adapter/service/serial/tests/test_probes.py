"""Acceptance probes against the MCU emulator, including a faulty emulator that must fail them."""

from __future__ import annotations

import unittest

from activequal.adapter.service.serial import mcu_emulator
from activequal.adapter.service.serial.probes import probe_host_loss, probe_limits_rejected, run_probes
from activequal.adapter.service.serial.tests.test_host_loopback import Loop


class ProbeTests(unittest.TestCase):
    def test_all_probes_pass_on_a_correct_controller(self) -> None:
        loop = Loop()
        results = run_probes(loop.host, energize=True)
        self.assertEqual([r.passed for r in results], [True, True, True], results)
        self.assertLess(loop.mcu.true_voltage_mv(2), 100)

    def test_a_controller_that_accepts_any_setpoint_fails(self) -> None:
        loop = Loop()
        loop.host.health_check()
        loop.mcu.cfg.hardware.max_mv = 10_000        # firmware bug: hardware maximum not enforced
        self.assertFalse(probe_limits_rejected(loop.host).passed)

    def test_a_controller_without_host_loss_shutdown_fails(self) -> None:
        loop = Loop()
        loop.host.health_check()
        original = mcu_emulator.HOST_LOSS_MS
        mcu_emulator.HOST_LOSS_MS = 10**9                # firmware bug: host-loss watchdog never fires
        try:
            result = probe_host_loss(loop.host)
        finally:
            mcu_emulator.HOST_LOSS_MS = original
        self.assertFalse(result.passed, result)
        loop.host.emergency_shutdown()


if __name__ == "__main__":
    unittest.main()
