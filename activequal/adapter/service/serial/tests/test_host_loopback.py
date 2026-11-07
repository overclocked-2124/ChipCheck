"""SerialBenchAdapter against the MCU emulator over an in-memory pipe, on a virtual clock."""

from __future__ import annotations

import unittest

from activequal.adapter.service.serial.host import HostConfig, SerialBenchAdapter
from activequal.adapter.service.serial.mcu_emulator import EmulatorConfig, McuEmulator
from activequal.adapter.service.serial.stream import InMemoryPipe
from activequal.adapter.service.types import ApprovedEpisode


class Loop:
    """Host on ``pipe.a``, emulator on ``pipe.b``; sleeping or waiting for bytes advances both."""

    def __init__(self, **emu: object) -> None:
        pipe = InMemoryPipe()
        self.t = 0.0
        self.mcu = McuEmulator(pipe.b, EmulatorConfig(**emu))
        pipe.b.on_write = self.mcu.pump
        pipe.a.on_idle = self._advance
        self.host = SerialBenchAdapter(pipe.a, HostConfig(), clock=lambda: self.t, sleep=self._advance)

    def _advance(self, seconds: float) -> None:
        ms = max(1, int(seconds * 1000))
        self.t += ms / 1000
        self.mcu.tick(ms)
        self.mcu.pump()


def episode(**over: object) -> ApprovedEpisode:
    cond = {"oledRailV": 3.3, "sensorRailV": 3.3, "oledRailTrimV": 0.0}
    cond.update(over)
    return ApprovedEpisode("ep-1", 1, "h" * 64, "bench-A", cond, 600, 7)


class HostLoopbackTests(unittest.TestCase):
    def test_health_check_reports_fixture(self) -> None:
        loop = Loop()
        health = loop.host.health_check()
        self.assertTrue(health.ok, health)

    def test_nominal_episode_returns_measurements(self) -> None:
        loop = Loop()
        loop.host.health_check()
        capture = loop.host.apply_and_measure(episode())
        self.assertTrue(capture.shutdown_confirmed)
        self.assertIsNone(capture.trip)
        self.assertAlmostEqual(capture.measured_rail_v["oledRailV"], 3.3, delta=0.05)

    def test_emulated_overcurrent_cuts_off(self) -> None:
        loop = Loop()
        loop.host.health_check()
        loop.mcu.inject_load(2, 250_000)
        capture = loop.host.apply_and_measure(episode())
        self.assertTrue(capture.cutoff_engaged)
        self.assertIsNotNone(capture.trip)
        self.assertTrue(loop.mcu.locked_out)     # a cutoff needs a manual reset before the next episode


if __name__ == "__main__":
    unittest.main()
