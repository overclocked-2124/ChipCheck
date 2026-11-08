"""Bench acceptance check over the serial link (HLD 02 §18 tests 1 and 7, HLD 10 WP9).

    python -m activequal.tools.hardware_check --port /dev/ttyACM0               # no rail is energized
    python -m activequal.tools.hardware_check --port /dev/ttyACM0 --energize    # also test 7 (host loss)
    python -m activequal.tools.hardware_check --emulator --energize             # self-test, no hardware

``--energize`` drives the OLED rail to 3.3 V and then stops talking to the test controller, so run
it only with the reviewed dummy load or DUT connected and the E-stop in reach.
"""

from __future__ import annotations

import argparse
import json
import sys

from activequal.adapter.service.serial.host import HostConfig, SerialBenchAdapter
from activequal.adapter.service.serial.probes import run_probes


def emulated_adapter() -> SerialBenchAdapter:
    from activequal.adapter.service.serial.mcu_emulator import McuEmulator
    from activequal.adapter.service.serial.stream import InMemoryPipe
    pipe, clock = InMemoryPipe(), [0.0]
    mcu = McuEmulator(pipe.b)
    pipe.b.on_write = mcu.pump

    def advance(seconds: float) -> None:
        ms = max(1, int(seconds * 1000))
        clock[0] += ms / 1000
        mcu.tick(ms)
        mcu.pump()
    pipe.a.on_idle = advance
    return SerialBenchAdapter(pipe.a, HostConfig(), clock=lambda: clock[0], sleep=advance)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ActiveQual bench acceptance check")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--port", help="serial port of the test controller")
    source.add_argument("--emulator", action="store_true", help="run against the in-process MCU emulator")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--energize", action="store_true", help="also run the host-loss test (energizes a rail)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.emulator:
        adapter = emulated_adapter()
    else:
        from activequal.adapter.service.serial.stream import PySerialStream
        adapter = SerialBenchAdapter(PySerialStream(args.port, args.baud), HostConfig())
    try:
        results = run_probes(adapter, energize=args.energize)
    finally:
        adapter.stream.close()
    if args.json:
        print(json.dumps([r.__dict__ for r in results], indent=2))
    else:
        for r in results:
            print(f"{'PASS' if r.passed else 'FAIL'}  {r.name}: {r.detail}")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
