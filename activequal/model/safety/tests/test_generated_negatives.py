"""Generated negatives (HLD 10 §4, PRD 14.3): unsafe executed candidates must be exactly zero.

Every candidate is invalid by construction: a randomly generated valid candidate with one to
three defects from the catalogue applied. The checker must approve none of them and must report
the code that each defect is designed to trigger.
"""

import dataclasses
import math
import random
import time
import unittest
from decimal import Decimal

from activequal.model.contract import parse_contract
from activequal.model.examples import oled_example_contract
from activequal.model.safety import check_candidate

CASES = 12000
SEED = 20261107
CAPS = frozenset({"supply.ch2", "supply.ch3", "dut", "mcu"})
HASH = "f" * 64


def build(**safety):
    raw = oled_example_contract()
    raw["safety"].update(safety)
    return parse_contract(raw, require_oracle=True)


def with_channel_limit(limit):
    raw = oled_example_contract()
    raw["safety"]["channels"]["supply.ch2"]["maxV"] = limit
    return parse_contract(raw, require_oracle=True)


BASE = with_channel_limit(3.4)                  # oledRailV may be requested up to 3.6 but only 3.4 is allowed
SLOW = build()
SLOW = dataclasses.replace(SLOW, controls={
    **SLOW.controls,
    "oledRailV": dataclasses.replace(SLOW.controls["oledRailV"], shutdown=3.3, slew_per_s_max=0.1),
    "sensorRailV": dataclasses.replace(SLOW.controls["sensorRailV"], shutdown=3.3, slew_per_s_max=0.1)})
TIME_CONTRACTS = {"EPISODE_TIME_BUDGET": build(maxEpisodeS=8), "SLEW_OR_RAMP_TOO_LONG": build(maxEpisodeS=7),
                  "DURATION_EXCEEDS_MAX": build(maxEpisodeS=1.5)}


def grid(low, high, step, rng):
    count = int((Decimal(str(high)) - Decimal(str(low))) / Decimal(str(step)))
    return float(Decimal(str(low)) + Decimal(str(step)) * rng.randint(0, count))


def valid_candidate(rng):
    workload = rng.choice(["idle", "oled_refresh", "sensor_read", "flash_write"])
    return {"oledRailV": grid(3.00, 3.40, 0.01, rng),
            "sensorRailV": grid(3.00, 3.54 if workload == "flash_write" else 3.60, 0.01, rng),
            "redLed": rng.random() < 0.5, "greenLed": rng.random() < 0.5, "workload": workload,
            "flashOffsetMs": rng.randint(0, 20) if workload == "flash_write" else 0,
            "dwellMs": 100 * rng.randint(2, 20)}


class Case:
    def __init__(self, rng):
        self.rng = rng
        self.contract = BASE
        self.conditions = valid_candidate(rng)
        self.kwargs = {"fixture_capabilities": CAPS, "contract_hash": HASH, "expected_hash": HASH}
        self.expected = []
        self.reserved = set()

    def take(self, *names):
        if self.reserved & set(names):
            return False
        self.reserved |= set(names)
        return True


NUMERIC = {"oledRailV": (3.00, 3.60, 0.01), "sensorRailV": (3.00, 3.60, 0.01), "flashOffsetMs": (0, 20, 1),
           "dwellMs": (200, 2000, 100)}
BAD_NUMBERS = [(True, "WRONG_TYPE"), (False, "WRONG_TYPE"), ("3.3", "WRONG_TYPE"), (None, "WRONG_TYPE"),
               (math.nan, "WRONG_TYPE"), (math.inf, "WRONG_TYPE"), (-math.inf, "WRONG_TYPE"),
               ([1], "WRONG_TYPE"), ({}, "WRONG_TYPE"), (10 ** 400, "VALUE_OUT_OF_RANGE"),
               (-(10 ** 400), "VALUE_OUT_OF_RANGE"), (2 ** 63, "VALUE_OUT_OF_RANGE"), (1e308, "VALUE_OUT_OF_RANGE")]


def d_out_of_range(case):
    name = case.rng.choice(sorted(NUMERIC))
    if not case.take(name):
        return False
    low, high, step = NUMERIC[name]
    gap = step * case.rng.randint(1, 50)
    value = high + gap if case.rng.random() < 0.5 else low - gap
    case.conditions[name] = round(value, 6) if isinstance(step, float) else int(value)
    case.expected.append("VALUE_OUT_OF_RANGE")
    return True


def d_off_grid(case):
    name = case.rng.choice(sorted(NUMERIC))
    if name == "flashOffsetMs" and case.conditions.get("workload") != "flash_write":
        return False   # keep the pattern single-purpose: an inactive control would also be reported
    if not case.take(name):
        return False
    low, high, step = NUMERIC[name]
    count = int((Decimal(str(high)) - Decimal(str(low))) / Decimal(str(step)))
    index = case.rng.randint(0, count - 1)
    offset = Decimal(str(step)) * Decimal(case.rng.choice(["0.5", "0.25", "0.001", "0.999"]))
    case.conditions[name] = float(Decimal(str(low)) + Decimal(str(step)) * index + offset)
    case.expected.append("OFF_STEP_GRID")
    return True


def d_wrong_type(case):
    kind = case.rng.choice(["numeric", "bool", "enum"])
    if kind == "numeric":
        name = case.rng.choice(sorted(NUMERIC))
        value, code = case.rng.choice(BAD_NUMBERS)
    elif kind == "bool":
        name = case.rng.choice(["redLed", "greenLed"])
        value, code = case.rng.choice([(0, "WRONG_TYPE"), (1, "WRONG_TYPE"), ("true", "WRONG_TYPE"),
                                       (None, "WRONG_TYPE"), (1.0, "WRONG_TYPE")])
    else:
        name = "workload"
        value, code = case.rng.choice([(5, "WRONG_TYPE"), (None, "WRONG_TYPE"), (True, "WRONG_TYPE"),
                                       (["idle"], "WRONG_TYPE")])
    if not case.take(name):
        return False
    case.conditions[name] = value
    case.expected.append(code)
    return True


def d_missing(case):
    name = case.rng.choice([key for key in sorted(valid_candidate(case.rng)) if key in case.conditions])
    if not case.take(name):
        return False
    del case.conditions[name]
    case.expected.append("MISSING_CONTROL")
    return True


def d_extra(case):
    key = case.rng.choice(["extra", "oledrailv", "OledRailV", "", "dwell_ms", 7, None])
    if key in case.conditions:
        return False
    case.conditions[key] = case.rng.choice([1, "x", None, True])
    case.expected.append("UNKNOWN_CONTROL")
    return True


def d_bad_enum(case):
    if not case.take("workload", "flashOffsetMs"):
        return False
    case.conditions["workload"] = case.rng.choice(["IDLE", "bogus", "", " idle", "flash-write", "oled_refresh "])
    case.conditions["flashOffsetMs"] = 0
    case.expected.append("NOT_IN_VALUES")
    return True


def d_inactive_not_nominal(case):
    if not case.take("workload", "flashOffsetMs"):
        return False
    case.conditions["workload"] = case.rng.choice(["idle", "oled_refresh", "sensor_read"])
    case.conditions["flashOffsetMs"] = case.rng.randint(1, 20)
    case.expected.append("INACTIVE_CONTROL_NOT_NOMINAL")
    return True


def d_forbidden(case):
    if not case.take("workload", "sensorRailV"):
        return False
    case.conditions["workload"] = "flash_write"
    case.conditions["sensorRailV"] = grid(3.55, 3.60, 0.01, case.rng)
    if "flashOffsetMs" not in case.reserved:
        case.conditions["flashOffsetMs"] = case.rng.randint(0, 20)
    case.expected.append("FORBIDDEN_COMBINATION")
    return True


def d_channel_limit(case):
    if not case.take("oledRailV"):
        return False
    case.conditions["oledRailV"] = grid(3.41, 3.60, 0.01, case.rng)
    case.expected.append("CHANNEL_VOLTAGE_LIMIT")
    return True


def d_capability(case):
    case.kwargs["fixture_capabilities"] = CAPS - {case.rng.choice(sorted(CAPS))}
    case.expected.append("CHANNEL_CAPABILITY_MISSING")
    return True


def d_stale(case):
    case.kwargs["expected_hash"] = "0" * 64
    case.expected.append("STALE_CONTRACT")
    return True


def d_time(case):
    code = case.rng.choice(sorted(TIME_CONTRACTS))
    if not case.take("oledRailV", "dwellMs", "workload", "flashOffsetMs") or case.contract is not BASE:
        return False
    case.contract = TIME_CONTRACTS[code]
    case.conditions["oledRailV"] = 3.6
    case.conditions["dwellMs"] = case.rng.choice([1100, 1200, 1500, 2000])
    case.expected.append(code)
    return True


def d_slew_step(case):
    if not case.take("oledRailV", "sensorRailV", "dwellMs", "workload", "flashOffsetMs") or case.contract is not BASE:
        return False
    case.contract = SLOW
    case.conditions["sensorRailV"] = 3.3
    case.conditions["oledRailV"] = 3.6
    case.conditions["dwellMs"] = case.rng.choice([200, 300, 400])
    case.kwargs["previous"] = {**case.conditions, "oledRailV": 3.0}
    case.expected.append("SLEW_OR_RAMP_TOO_LONG")
    return True


DEFECTS = [d_out_of_range, d_off_grid, d_wrong_type, d_missing, d_extra, d_bad_enum, d_inactive_not_nominal,
           d_forbidden, d_channel_limit, d_capability, d_stale, d_time, d_slew_step]


def generate(count, seed):
    rng = random.Random(seed)
    for _ in range(count):
        case = Case(rng)
        wanted = rng.choice([1, 1, 1, 2, 3])
        attempts = 0
        while len(case.expected) < wanted and attempts < 20:
            attempts += 1
            rng.choice(DEFECTS)(case)
        if not case.expected:
            case = Case(rng)
            d_out_of_range(case)
        yield case


class GeneratedNegativeTests(unittest.TestCase):
    def test_no_invalid_candidate_is_ever_approved(self):
        started = time.perf_counter()
        counts = {}
        total = 0
        for case in generate(CASES, SEED):
            decision = check_candidate(case.contract, case.conditions, **case.kwargs)
            total += 1
            self.assertFalse(decision.approved, (case.expected, case.conditions))
            missing = [code for code in case.expected if code not in decision.codes]
            self.assertEqual(missing, [], (case.conditions, case.kwargs, decision.violations))
            for code in case.expected:
                counts[code] = counts.get(code, 0) + 1
        elapsed = time.perf_counter() - started
        self.assertGreaterEqual(total, 10000)
        self.assertEqual(len(counts), 14, counts)   # every reason code except the UNEVALUABLE catch-all
        self.assertTrue(all(count >= 100 for count in counts.values()), counts)
        print(f"\n{total} generated negatives, 0 approved, {elapsed:.2f}s, per-code {dict(sorted(counts.items()))}")

    def test_valid_candidates_are_approved(self):
        rng = random.Random(SEED + 1)
        previous = None
        for _ in range(600):
            candidate = valid_candidate(rng)
            decision = check_candidate(BASE, candidate, fixture_capabilities=CAPS, contract_hash=HASH,
                                       expected_hash=HASH, previous=previous)
            self.assertTrue(decision.approved, (candidate, decision.violations))
            previous = candidate

    def test_generation_is_seeded(self):
        first = [(c.conditions, c.expected) for c in generate(50, 7)]
        second = [(c.conditions, c.expected) for c in generate(50, 7)]
        self.assertEqual(repr(first), repr(second))


if __name__ == "__main__":
    unittest.main()
