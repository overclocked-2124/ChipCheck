"""Parity check (HLD 01 CTX-09, HLD 10 WP8): full-stack campaigns must agree with the benchmark CLI.

The benchmark CLI is a fast path that drives the planner directly. Research numbers on hardware go through
the whole stack, so the two have to give the same discovery rates for the same planner, profile and budget.
This runs both and tests the difference with a two-proportion z-test.

    python -m activequal.tools.parity --profile B1w --planner tpe --budget 30 --campaigns 40
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass

from activequal.tools import benchmark
from activequal.tools.stack import SimulatedStack


@dataclass(frozen=True)
class Parity:
    profile: str
    planner: str
    budget: int
    campaigns: int
    cli_rate: float
    stack_rate: float
    z: float

    @property
    def difference(self) -> float:
        return self.stack_rate - self.cli_rate

    def agrees(self, z_limit: float = 3.0) -> bool:
        return abs(self.z) <= z_limit


def two_proportion_z(successes_a: int, n_a: int, successes_b: int, n_b: int) -> float:
    pooled = (successes_a + successes_b) / (n_a + n_b)
    spread = math.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    if spread == 0:
        return 0.0 if successes_a / n_a == successes_b / n_b else math.inf
    return (successes_a / n_a - successes_b / n_b) / spread


def stack_successes(profile: str, planner: str, budget: int, campaigns: int, base_seed: int) -> int:
    found = 0
    for index in range(campaigns):
        seed = benchmark._decision()[2](base_seed, index, f"parity-{profile}-{planner}")
        with SimulatedStack(profile, planner=planner, seed=seed, noise_seed=seed ^ 0x5A5A, discovery=budget,
                            verification=0, plan={"onConfirmed": "stop"}) as stack:
            stack.run()
            found += stack.episodes_to_first_failure() is not None
    return found


def cli_successes(profile: str, planner: str, budget: int, campaigns: int, base_seed: int) -> int:
    report = benchmark.run_benchmark([planner], [profile], campaigns, budget, base_seed, 8, 2.5, 1, checkpoints=(budget,))
    return report["cells"][0]["discovery"][str(budget)]["discovered"]


def check(profile: str, planner: str, budget: int, campaigns: int, base_seed: int = 7) -> Parity:
    cli = cli_successes(profile, planner, budget, campaigns, base_seed)
    stack = stack_successes(profile, planner, budget, campaigns, base_seed)
    return Parity(profile, planner, budget, campaigns, cli / campaigns, stack / campaigns,
                  two_proportion_z(stack, campaigns, cli, campaigns))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="B1w")
    parser.add_argument("--planner", default="tpe")
    parser.add_argument("--budget", type=int, default=30)
    parser.add_argument("--campaigns", type=int, default=40)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = check(args.profile, args.planner, args.budget, args.campaigns, args.seed)
    if args.json:
        print(json.dumps(result.__dict__ | {"agrees": result.agrees()}))
    else:
        print(f"{result.profile}/{result.planner} within {result.budget} episodes over {result.campaigns} campaigns: "
              f"benchmark CLI {result.cli_rate:.0%}, full stack {result.stack_rate:.0%}, z = {result.z:+.2f} "
              f"-> {'AGREE' if result.agrees() else 'DISAGREE'}")
    return 0 if result.agrees() else 1


if __name__ == "__main__":
    raise SystemExit(main())
