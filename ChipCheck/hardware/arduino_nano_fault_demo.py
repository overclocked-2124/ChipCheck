#!/usr/bin/env python3
"""Run ChipCheck's seeded failure search with a classic Arduino Nano over USB."""

from __future__ import annotations

import argparse
import time

import optuna
import serial
from optuna.samplers import TPESampler


SCENARIOS = {"R1": 1, "R2": 2, "R3": 3, "R4": 4}
PARAMETERS = ("led1", "led2", "led3")
TEST_RANGE_V = 3.3


class Nano:
    def __init__(self, port: str, baud: int, timeout: float):
        self.serial = serial.Serial(port, baudrate=baud, timeout=timeout,
                                    write_timeout=timeout)
        # Opening a Nano serial port commonly resets the board. Give its bootloader
        # time, discard boot chatter, then actively handshake with the sketch.
        time.sleep(2.0)
        self.serial.reset_input_buffer()
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            self.serial.write(b"H\n")
            self.serial.flush()
            reply = self.serial.readline().decode("ascii", errors="replace").strip()
            if reply == "READY":
                return
        self.serial.close()
        raise RuntimeError("Nano did not answer READY; check port, sketch, and 115200 baud")

    def execute(self, test_id: int, scenario: int, codes: dict[str, int]) -> bool:
        payload = f"T,{test_id},{scenario},{codes['led1']},{codes['led2']},{codes['led3']}\n"
        self.serial.write(payload.encode("ascii"))
        self.serial.flush()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            reply = self.serial.readline().decode("ascii", errors="replace").strip()
            if not reply:
                continue
            fields = reply.split(",")
            if len(fields) == 3 and fields[0] == "R":
                try:
                    response_id = int(fields[1])
                except ValueError:
                    continue
                if response_id != test_id or fields[2] not in ("P", "F"):
                    continue
                return fields[2] == "F"
            if reply.startswith("ERR,"):
                raise RuntimeError(f"Nano rejected test {test_id}: {reply}")
        raise TimeoutError(f"No valid result from Nano for test {test_id}")

    def close(self) -> None:
        if self.serial.is_open:
            self.serial.close()


def run_one(nano: Nano, scenario: int, codes: dict[str, int], phase: str,
            test_number: int) -> bool:
    failed = nano.execute(test_number, scenario, codes)
    shown = " ".join(
        f"{name}={codes[name] * TEST_RANGE_V / 255:.4f}V-eq "
        f"(code {codes[name]}, {codes[name] / 255:.1%} scale)"
                     for name in PARAMETERS)
    result = ("FAIL (buzzer silent; Nano status LED on)" if failed else
              "PASS (buzzer beeped; Nano status LED off)")
    print(f"[{phase} {test_number:04d}] {shown} -> {result}", flush=True)
    return failed


def localize_single_box(nano: Nano, scenario: int, anchor: dict[str, int],
                        next_test: int) -> tuple[dict[str, tuple[int, int]], int]:
    region: dict[str, tuple[int, int]] = {}
    for name in PARAMETERS:
        edges: list[int] = []
        for endpoint in (0, 255):
            fail_code, pass_code = anchor[name], endpoint
            probe = dict(anchor)
            probe[name] = endpoint
            if run_one(nano, scenario, probe, "BOUNDARY", next_test):
                edges.append(endpoint)
            else:
                while abs(fail_code - pass_code) > 1:
                    midpoint = (fail_code + pass_code) // 2
                    probe = dict(anchor)
                    probe[name] = midpoint
                    if run_one(nano, scenario, probe, "BOUNDARY", next_test):
                        fail_code = midpoint
                    else:
                        pass_code = midpoint
                    next_test += 1
                edges.append(fail_code)
            next_test += 1
        region[name] = (min(edges), max(edges))
    return region, next_test


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Nano USB serial port, e.g. COM4 or /dev/ttyUSB0")
    parser.add_argument("--scenario", choices=SCENARIOS, default="R2")
    parser.add_argument("--trials", type=int, default=200, help="Maximum discovery tests")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--no-localize", action="store_true")
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials must be at least 1")

    nano = Nano(args.port, args.baud, timeout=1.0)
    print(f"Arduino Nano demo: scenario={args.scenario}, discovery limit={args.trials}")
    print("Scale: 0..3.3 V PWM-average equivalent on the 3.3 V Nano.")
    print("The sketch injects the failure in software; PWM is not steady analog voltage.")
    study = optuna.create_study(
        direction="minimize",
        sampler=TPESampler(seed=args.seed, n_startup_trials=min(20, args.trials)),
    )
    anchor: dict[str, int] | None = None
    test_number = 1
    try:
        for _ in range(args.trials):
            trial = study.ask()
            codes = {name: trial.suggest_int(name, 0, 255) for name in PARAMETERS}
            failed = run_one(nano, SCENARIOS[args.scenario], codes, "TEST", test_number)
            study.tell(trial, -1.0 if failed else 0.0)
            test_number += 1
            if failed:
                anchor = codes
                break

        if anchor is None:
            print(f"No injected failure found in {args.trials} tests.")
            return 1
        if args.no_localize:
            print(f"Injected failure found at codes: {anchor}")
            return 0

        region, test_number = localize_single_box(
            nano, SCENARIOS[args.scenario], anchor, test_number
        )
        print("\nLocalized seeded failure region (3.3 V-equivalent PWM scale; all ranges must match):")
        for name, (low, high) in region.items():
            low_v = low * TEST_RANGE_V / 255
            high_v = high * TEST_RANGE_V / 255
            print(f"  {name}: {low_v:.4f}..{high_v:.4f} V-equivalent "
                  f"(codes {low}..{high})")
        print(f"Total Nano tests, including boundary probes: {test_number - 1}")
        return 0
    finally:
        nano.close()


if __name__ == "__main__":
    raise SystemExit(main())
