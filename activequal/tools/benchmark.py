"""Benchmark CLI: planner comparison on the simulated profiles (HLD 06 §3, HLD 10 WP3).

Each campaign is driven through the real ``propose()`` exactly as the Agent will call it: one
candidate per call (``count=1``), the full history fed back on every call as
``{"outcome", "conditions", "robustness"}``, discovery being the first guard-banded failure.
This is a fast path; research numbers on hardware go through the full stack (HLD 10 §5.3).

    python -m activequal.tools.benchmark --planners random,tpe --profiles B1w,B2 --campaigns 100 --budget 50
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any

from activequal.adapter.service.simulator import PROFILE_NAMES, SimulatedBenchAdapter
from activequal.adapter.service.types import ApprovedEpisode, RawBenchCapture

LATENCY_LIMIT_MS = 120.0
LATENCY_NOMINAL_MS = 31.0
UNCERTAINTY_MS = 5.0           # U for oledLatencyMs (HLD 06 §6: U = 2 sigma)
RAIL_TOLERANCE_V = 0.03        # validity rule of the HLD 04 §12 example
DEFAULT_CHECKPOINTS = (30, 50)


def benchmark_contract(budget: int) -> dict[str, Any]:
    """The 1,220-point space of HLD 06 §3 as a v2 contract: rail, two LEDs, five workloads."""
    from activequal.model.examples import oled_example_contract
    contract = oled_example_contract()
    controls = contract["controls"]
    for name in ("sensorRailV", "flashOffsetMs", "dwellMs"):
        del controls[name]
    controls["workload"]["values"] = ["idle", "oled_refresh", "sensor_read", "wifi_tx", "flash_write"]
    contract["forbidden"] = []
    contract["campaign"]["budget"] = budget
    return contract


# ------------------------------------------------------------------ scoring

def latency_margin(latency_ms: float) -> float:
    """HLD 04 §13 Option A for the single ``<=`` 120 ms requirement, nominal 31 ms, clipped to [-1, 1].

    Stand-in: the Oracle (WP2, ``activequal.service.oracle``) replaces this once the benchmark is
    driven through the full stack.
    """
    return max(-1.0, min(1.0, (LATENCY_LIMIT_MS - latency_ms) / (LATENCY_LIMIT_MS - LATENCY_NOMINAL_MS)))


def reset_margin(reset_count: float) -> float:
    """Option A for ``exact`` 0: +1 if equal, otherwise -1."""
    return 1.0 if reset_count == 0 else -1.0


def judge(capture: RawBenchCapture, requested: dict[str, Any],
          uncertainty_ms: float = UNCERTAINTY_MS) -> tuple[str, float | None]:
    """Outcome and planner robustness for one capture (HLD 03 §15.1 order, HLD 04 §13 Option B).

    A latency over limit + U or any reset is ``DUT_FAILURE``; a latency within U of the limit is
    inconclusive and recorded as ``INVALID_EXPERIMENT`` (no replay here). Latency is judged only
    when it was observed (workload oled_refresh).
    """
    if capture.trip is not None:
        return "SAFETY_ABORT", None
    if not capture.rail_settled or abs(capture.measured_rail_v.get("oledRailV", math.inf)
                                       - float(requested["oledRailV"])) > RAIL_TOLERANCE_V:
        return "INVALID_EXPERIMENT", None
    required = ["maxHeartbeatGapMs", "resetCount", "measuredDut3v3MinV"]
    if requested["workload"] == "oled_refresh":
        required.append("oledLatencyMs")
    if capture.missing_observations or any(name not in capture.observations for name in required):
        return "INVALID_EXPERIMENT", None
    margins = [reset_margin(capture.observations["resetCount"])]
    failed = capture.observations["resetCount"] != 0
    inconclusive = False
    if "oledLatencyMs" in capture.observations:
        latency = capture.observations["oledLatencyMs"]
        margins.append(latency_margin(latency))
        failed = failed or latency > LATENCY_LIMIT_MS + uncertainty_ms
        inconclusive = LATENCY_LIMIT_MS - uncertainty_ms < latency <= LATENCY_LIMIT_MS + uncertainty_ms
    if failed:
        return "DUT_FAILURE", min(margins)
    if inconclusive:
        return "INVALID_EXPERIMENT", None
    return "PASS", min(margins)


# ---------------------------------------------------------------- campaigns

def _decision() -> tuple[Any, Any, Any]:
    from activequal.decision.service.decision import propose
    from activequal.decision.service.planners import PLANNER_REGISTRY
    from activequal.decision.service.planners.base import step_seed
    return propose, PLANNER_REGISTRY, step_seed


def run_campaign(planner: str, profile: str, campaign: int, budget: int, base_seed: int = 42,
                 warmup: int = 8, sigma_ms: float = 2.5) -> int | None:
    """Run one campaign; return the 1-based episode of the first guard-banded failure, or None.

    Seeds are derived by hashing (``step_seed``), not consecutive integers, so campaigns do not
    share random streams. The campaign and noise seeds do not depend on the planner, so planners
    face identical noise in the same campaign slot.
    """
    propose, _, step_seed = _decision()
    campaign_seed = step_seed(base_seed, campaign, f"campaign:{profile}")
    adapter = SimulatedBenchAdapter(profile, noise_seed=step_seed(base_seed, campaign, f"noise:{profile}"),
                                    latency_sigma_ms=sigma_ms)
    contract = benchmark_contract(budget)
    history: list[dict[str, Any]] = []
    for step in range(budget):
        response = propose({"contract": contract, "method": planner, "seed": campaign_seed, "count": 1,
                            "warmupTrials": warmup, "history": history})
        if not response["tests"]:
            return None                       # planner has nothing new to propose
        conditions = response["tests"][0]["conditions"]
        episode = ApprovedEpisode(f"{profile}-{campaign}-{step}", 1, "benchmark", "simulator", conditions, 500,
                                  step_seed(campaign_seed, step, "episode"))
        outcome, robustness = judge(adapter.apply_and_measure(episode), conditions)
        if outcome == "DUT_FAILURE":
            return step + 1
        history.append({"outcome": outcome, "conditions": conditions, "robustness": robustness})
    return None


def _task(args: tuple[str, str, int, int, int, int, float]) -> tuple[str, str, int | None]:
    planner, profile, campaign, budget, seed, warmup, sigma = args
    return planner, profile, run_campaign(planner, profile, campaign, budget, seed, warmup, sigma)


# ---------------------------------------------------------------- statistics

def wilson(successes: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def summarize(found: list[int | None], budget: int, checkpoints: tuple[int, ...]) -> dict[str, Any]:
    n = len(found)
    rates = {}
    for point in checkpoints:
        hits = sum(1 for item in found if item is not None and item <= point)
        low, high = wilson(hits, n)
        rates[str(point)] = {"discovered": hits, "rate": hits / n if n else 0.0, "ci95": [low, high]}
    # Median over all campaigns with undiscovered ones as censored at the budget; None if fewer than half found.
    discovered = sorted(item for item in found if item is not None)
    median = statistics.median(discovered) if n and len(discovered) * 2 > n else None
    return {"campaigns": n, "budget": budget, "discovery": rates, "medianEpisodesToFirstFailure": median,
            "medianAmongDiscovered": statistics.median(discovered) if discovered else None}


def run_benchmark(planners: list[str], profiles: list[str], campaigns: int, budget: int, seed: int = 42,
                  warmup: int = 8, sigma_ms: float = 2.5, workers: int = 1,
                  checkpoints: tuple[int, ...] = DEFAULT_CHECKPOINTS) -> dict[str, Any]:
    points = tuple(sorted({p for p in checkpoints if p <= budget} or {budget}))
    tasks = [(planner, profile, c, budget, seed, warmup, sigma_ms)
             for planner in planners for profile in profiles for c in range(campaigns)]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
            results = list(pool.map(_task, tasks, chunksize=max(1, len(tasks) // (workers * 8))))
    else:
        results = [_task(task) for task in tasks]
    cells: dict[tuple[str, str], list[int | None]] = {}
    for planner, profile, found in results:
        cells.setdefault((planner, profile), []).append(found)
    return {"seed": seed, "sigmaMs": sigma_ms, "budget": budget, "campaigns": campaigns, "warmupTrials": warmup,
            "checkpoints": list(points),
            "cells": [{"planner": planner, "profile": profile, **summarize(cells[(planner, profile)], budget, points)}
                      for planner in planners for profile in profiles]}


def format_table(report: dict[str, Any]) -> str:
    points = [str(p) for p in report["checkpoints"]]
    head = f"{'profile':<8}{'planner':<9}" + "".join(f"{'found<=' + p:>26}" for p in points) + f"{'median ep':>11}"
    lines = [f"campaigns/cell={report['campaigns']} budget={report['budget']} seed={report['seed']} "
             f"sigma={report['sigmaMs']} ms (rate, Wilson 95% interval)", head]
    for cell in sorted(report["cells"], key=lambda c: (c["profile"], c["planner"])):
        text = ""
        for p in points:
            item = cell["discovery"][p]
            text += f"{item['rate'] * 100:>8.1f}% [{item['ci95'][0] * 100:4.1f}-{item['ci95'][1] * 100:4.1f}]".rjust(26)
        median = cell["medianEpisodesToFirstFailure"]
        lines.append(f"{cell['profile']:<8}{cell['planner']:<9}{text}{'>half' if median is None else median:>11}")
    return "\n".join(lines)


# Planners that cannot run without per-campaign configuration (operator-chosen candidates).
NEEDS_CONFIG = frozenset({"manual"})


def main(argv: list[str] | None = None) -> int:
    _, registry, _ = _decision()
    parser = argparse.ArgumentParser(prog="python -m activequal.tools.benchmark", description=__doc__.splitlines()[0])
    parser.add_argument("--campaigns", type=int, default=100)
    parser.add_argument("--budget", type=int, default=50)
    parser.add_argument("--planners", help=f"comma list; default all registered except gp and manual ({', '.join(registry)})")
    parser.add_argument("--include-gp", action="store_true", help="also run the slow gp planner (needs torch)")
    parser.add_argument("--profiles", default=",".join(PROFILE_NAMES))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=8, help="TPE/GP startup trials")
    parser.add_argument("--sigma-ms", type=float, default=2.5, help="latency noise sigma")
    parser.add_argument("--json", action="store_true", help="print JSON instead of the table")
    args = parser.parse_args(argv)

    planners = [p.strip() for p in args.planners.split(",")] if args.planners else \
        [name for name in registry if name not in NEEDS_CONFIG and (name != "gp" or args.include_gp)]
    profiles = [p.strip() for p in args.profiles.split(",")]
    for name in planners:
        if name not in registry:
            parser.error(f"unknown planner {name!r}; registered: {', '.join(registry)}")
    for name in profiles:
        if name.upper() not in {p.upper() for p in PROFILE_NAMES}:
            parser.error(f"unknown profile {name!r}; choose from {', '.join(PROFILE_NAMES)}")
    if args.campaigns < 1 or args.budget < 1 or args.workers < 1:
        parser.error("--campaigns, --budget and --workers must be positive")
    profiles = [next(p for p in PROFILE_NAMES if p.upper() == name.upper()) for name in profiles]

    started = time.monotonic()
    report = run_benchmark(planners, profiles, args.campaigns, args.budget, args.seed, args.warmup, args.sigma_ms,
                           args.workers)
    report["elapsedS"] = round(time.monotonic() - started, 1)
    print(json.dumps(report, indent=2) if args.json else format_table(report) + f"\nelapsed {report['elapsedS']} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
