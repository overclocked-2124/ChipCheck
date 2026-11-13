#!/usr/bin/env python3
"""Physical GPIO demo for ChipCheck's seeded Raspberry Pi pin-failure search.

This drives three LEDs with PWM and an active buzzer with a Pi GPIO. The
failure is intentionally injected in this Python program; it is not a model of
an electrical fault inside Raspberry Pi hardware. See docs/IMPLEMENTATION_CONTEXT_AND_HARDWARE_INTEGRATION.md.
"""

from __future__ import annotations

import argparse
import time

import optuna
from optuna.samplers import TPESampler


# BCM numbering. Standard 40-pin header physical positions are in the wiring
# guide. gpiozero uses BCM numbering by default.
LED_PINS = {
    "led1": 17,
    "led2": 27,
    "led3": 22,
}
BUZZER_PIN = 23
VOLTAGE_STEP_V = 3.3 / 255

# Inclusive 8-bit code intervals derived from the synthetic voltage boxes.
# Each outer list entry is one complete failure box; all three pin intervals
# in a box must match at once.
SCENARIOS: dict[str, list[dict[str, tuple[int, int]]]] = {
    "R1": [{"led1": (85, 170), "led2": (163, 177), "led3": (132, 162)}],
    "R2": [{"led1": (62, 193), "led2": (78, 216), "led3": (39, 193)}],
    "R3": [{"led1": (194, 216), "led2": (39, 61), "led3": (217, 239)}],
    "R4": [],
}


def is_injected_failure(codes: dict[str, int], boxes: list[dict[str, tuple[int, int]]]) -> bool:
    """Return whether this demo's software-seeded fault should silence the buzzer."""
    return any(
        all(low <= codes[name] <= high for name, (low, high) in box.items())
        for box in boxes
    )


class GpioFixture:
    """Drive the LEDs and buzzer using gpiozero on a Raspberry Pi."""

    def __init__(self, settle_seconds: float, beep_seconds: float,
                 boxes: list[dict[str, tuple[int, int]]]):
        try:
            from gpiozero import Buzzer, PWMLED
        except ImportError as exc:
            raise SystemExit(
                "gpiozero is required on the Raspberry Pi. Install it with: "
                "sudo apt install python3-gpiozero"
            ) from exc

        self.leds = {
            name: PWMLED(pin, frequency=1000, initial_value=0)
            for name, pin in LED_PINS.items()
        }
        self.buzzer = Buzzer(BUZZER_PIN, active_high=True, initial_value=False)
        self.settle_seconds = settle_seconds
        self.beep_seconds = beep_seconds
        self.boxes = boxes

    def execute(self, codes: dict[str, int], phase: str, test_number: int) -> bool:
        """Set PWM LED levels, run the seeded buzzer behavior, and print the outcome."""
        for name, led in self.leds.items():
            led.value = codes[name] / 255.0
        time.sleep(self.settle_seconds)

        failed = is_injected_failure(codes, self.boxes)
        if failed:
            self.buzzer.off()
        else:
            self.buzzer.on()
        time.sleep(self.beep_seconds)
        self.buzzer.off()

        values = " ".join(
            f"{name}={codes[name]} ({codes[name] / 255.0:.1%} PWM)"
            for name in LED_PINS
        )
        result = "FAIL (buzzer silenced)" if failed else "PASS (buzzer beeped)"
        print(f"[{phase} {test_number:04d}] {values} -> {result}", flush=True)
        return failed

    def close(self) -> None:
        self.buzzer.off()
        self.buzzer.close()
        for led in self.leds.values():
            led.off()
            led.close()


def localize_single_box(
    fixture: GpioFixture,
    anchor: dict[str, int],
    next_test: int,
) -> tuple[dict[str, tuple[int, int]], int]:
    """Binary-search each edge of a single contiguous seeded failure box."""
    region: dict[str, tuple[int, int]] = {}

    for name in LED_PINS:
        edges: list[int] = []
        for endpoint in (0, 255):
            fail_code = anchor[name]
            pass_code = endpoint
            probe = dict(anchor)
            probe[name] = pass_code
            endpoint_failed = fixture.execute(probe, "BOUNDARY", next_test)
            next_test += 1

            if endpoint_failed:
                edges.append(pass_code)
                continue

            while abs(fail_code - pass_code) > 1:
                mid = (fail_code + pass_code) // 2
                probe = dict(anchor)
                probe[name] = mid
                if fixture.execute(probe, "BOUNDARY", next_test):
                    fail_code = mid
                else:
                    pass_code = mid
                next_test += 1
            edges.append(fail_code)

        region[name] = (min(edges), max(edges))

    return region, next_test


def print_region(region: dict[str, tuple[int, int]]) -> None:
    print("\nLocalized seeded failure region (8-bit PWM codes):")
    for name, (low, high) in region.items():
        low_duty = low / 255 * 100
        high_duty = high / 255 * 100
        low_equiv = low * VOLTAGE_STEP_V
        high_equiv = high * VOLTAGE_STEP_V
        print(
            f"  {name}: code {low}..{high}, duty {low_duty:.1f}..{high_duty:.1f}% "
            f"(PWM-average equivalent {low_equiv:.4f}..{high_equiv:.4f} V)"
        )
    print("All three intervals must hold simultaneously for this injected fault.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="R2",
                        help="Software-injected fault box (R2 is broad and quick to demo)")
    parser.add_argument("--trials", type=int, default=200,
                        help="Maximum TPE discovery tests before giving up")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--settle-ms", type=float, default=100)
    parser.add_argument("--beep-ms", type=float, default=200)
    parser.add_argument("--no-localize", action="store_true",
                        help="Drive GPIO and search only; do not run boundary probes")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.trials < 1:
        raise SystemExit("--trials must be at least 1")
    fixture = GpioFixture(args.settle_ms / 1000, args.beep_ms / 1000,
                          SCENARIOS[args.scenario])
    print(f"GPIO demo: scenario={args.scenario}, TPE discovery limit={args.trials}")
    print("This demo injects the failure in Python; it does not test a Pi wiring fault.")
    print(f"LED BCM pins: {LED_PINS}; active buzzer BCM pin: {BUZZER_PIN}")

    study = optuna.create_study(
        direction="minimize",
        sampler=TPESampler(seed=args.seed, n_startup_trials=min(20, args.trials)),
    )
    anchor: dict[str, int] | None = None
    test_number = 1
    try:
        for _ in range(args.trials):
            trial = study.ask()
            codes = {
                name: trial.suggest_int(name, 0, 255)
                for name in LED_PINS
            }
            failed = fixture.execute(codes, "TEST", test_number)
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

        region, test_number = localize_single_box(fixture, anchor, test_number)
        print_region(region)
        print(f"Total GPIO output trials: {test_number - 1}")
        return 0
    finally:
        fixture.close()


if __name__ == "__main__":
    raise SystemExit(main())
