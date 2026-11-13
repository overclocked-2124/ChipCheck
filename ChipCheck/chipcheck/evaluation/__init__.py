"""Evaluation and comparison module for ChipCheck campaigns.

Compares TPE and Random planners on identical benchmarks.
Generates CSV/JSON outputs and readable Markdown reports.
"""

from __future__ import annotations

import csv
import json
import logging
import statistics
from pathlib import Path
from typing import Optional

from chipcheck.campaign import CampaignResult, run_campaign
from chipcheck.contract import load_contract
from chipcheck.executor.simulator import GROUND_TRUTH

logger = logging.getLogger(__name__)


def compare_planners(
    contract_path: str,
    benchmark: str = "B1",
    budget: int = 100,
    seeds: list[int] | int = 10,
    confirmation_replays: int = 5,
    output_dir: str = "output",
) -> dict:
    """Run TPE and Random on the same benchmark with multiple seeds.

    Returns comparison dictionary.
    """
    if isinstance(seeds, int):
        seed_list = list(range(seeds))
    else:
        seed_list = seeds

    contract = load_contract(contract_path)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    tpe_results: list[CampaignResult] = []
    random_results: list[CampaignResult] = []

    for seed in seed_list:
        logger.info("Running seed %d / %d...", seed + 1, len(seed_list))

        # TPE campaign
        tpe_result = run_campaign(
            contract=contract,
            planner_type="tpe",
            benchmark=benchmark,
            budget=budget,
            seed=seed,
            confirmation_replays=confirmation_replays,
            db_path=str(Path(output_dir) / "chipcheck_results.db"),
            output_dir=output_dir,
        )
        tpe_results.append(tpe_result)

        # Random campaign
        random_result = run_campaign(
            contract=contract,
            planner_type="random",
            benchmark=benchmark,
            budget=budget,
            seed=seed,
            confirmation_replays=confirmation_replays,
            db_path=str(Path(output_dir) / "chipcheck_results.db"),
            output_dir=output_dir,
        )
        random_results.append(random_result)

    comparison = _build_comparison(tpe_results, random_results, benchmark, budget)

    # Save outputs
    _save_csv(tpe_results, random_results, Path(output_dir) / f"comparison_{benchmark}.csv")
    _save_json(comparison, Path(output_dir) / f"comparison_{benchmark}.json")
    _save_markdown_report(comparison, tpe_results, random_results,
                          Path(output_dir) / f"report_{benchmark}.md", benchmark, budget)

    return comparison


def _build_comparison(
    tpe_results: list[CampaignResult],
    random_results: list[CampaignResult],
    benchmark: str,
    budget: int,
) -> dict:
    """Build comparison statistics."""
    def _stats(values: list, label: str = "") -> dict:
        valid = [v for v in values if v is not None]
        if not valid:
            return {"mean": None, "median": None, "std": None, "values": values}
        return {
            "mean": statistics.mean(valid),
            "median": statistics.median(valid),
            "std": statistics.stdev(valid) if len(valid) > 1 else 0.0,
            "values": values,
        }

    def _extract(results: list[CampaignResult], attr: str) -> list:
        return [getattr(r, attr) for r in results]

    comparison = {
        "benchmark": benchmark,
        "budget": budget,
        "seeds": len(tpe_results),
        "tpe": {
            "failure_discovery_rate": _stats([
                1 if r.first_failure_trial is not None else 0 for r in tpe_results
            ]),
            "experiments_to_first_failure": _stats(
                _extract(tpe_results, "experiments_to_first_failure")
            ),
            "best_robustness": _stats(_extract(tpe_results, "best_robustness")),
            "confirmed_failures": _stats(_extract(tpe_results, "confirmed_failures")),
            "reproduction_rate": _stats(_extract(tpe_results, "reproduction_rate")),
            "valid_observations": _stats(_extract(tpe_results, "valid_observations")),
            "invalid_attempts": _stats(_extract(tpe_results, "invalid_attempts")),
            "boundary_experiments": _stats(_extract(tpe_results, "boundary_experiments")),
            "boundary_best_abs_robustness": _stats(
                _extract(tpe_results, "boundary_best_abs_robustness")
            ),
            "experiments_executed": _stats(_extract(tpe_results, "experiments_executed")),
        },
        "random": {
            "failure_discovery_rate": _stats([
                1 if r.first_failure_trial is not None else 0 for r in random_results
            ]),
            "experiments_to_first_failure": _stats(
                _extract(random_results, "experiments_to_first_failure")
            ),
            "best_robustness": _stats(_extract(random_results, "best_robustness")),
            "confirmed_failures": _stats(_extract(random_results, "confirmed_failures")),
            "reproduction_rate": _stats(_extract(random_results, "reproduction_rate")),
            "valid_observations": _stats(_extract(random_results, "valid_observations")),
            "invalid_attempts": _stats(_extract(random_results, "invalid_attempts")),
            "boundary_experiments": _stats(_extract(random_results, "boundary_experiments")),
            "boundary_best_abs_robustness": _stats(
                _extract(random_results, "boundary_best_abs_robustness")
            ),
            "experiments_executed": _stats(_extract(random_results, "experiments_executed")),
        },
    }

    return comparison


def _save_csv(
    tpe_results: list[CampaignResult],
    random_results: list[CampaignResult],
    path: Path,
) -> None:
    """Save comparison results to CSV."""
    fields = [
        "planner", "seed", "campaign_id", "experiments_executed",
        "first_failure_trial", "experiments_to_first_failure",
        "best_robustness", "confirmed_failures", "reproduction_rate",
        "valid_observations", "invalid_attempts", "rejected_proposals",
        "boundary_experiments", "boundary_best_abs_robustness",
        "total_deadline_misses", "total_failed_reads",
    ]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for r in tpe_results:
            writer.writerow({
                "planner": "TPE",
                "seed": r.seed,
                "campaign_id": r.campaign_id,
                "experiments_executed": r.experiments_executed,
                "first_failure_trial": r.first_failure_trial,
                "experiments_to_first_failure": r.experiments_to_first_failure,
                "best_robustness": r.best_robustness,
                "confirmed_failures": r.confirmed_failures,
                "reproduction_rate": r.reproduction_rate,
                "valid_observations": r.valid_observations,
                "invalid_attempts": r.invalid_attempts,
                "rejected_proposals": r.rejected_proposals,
                "boundary_experiments": r.boundary_experiments,
                "boundary_best_abs_robustness": r.boundary_best_abs_robustness,
                "total_deadline_misses": r.total_deadline_misses,
                "total_failed_reads": r.total_failed_reads,
            })

        for r in random_results:
            writer.writerow({
                "planner": "Random",
                "seed": r.seed,
                "campaign_id": r.campaign_id,
                "experiments_executed": r.experiments_executed,
                "first_failure_trial": r.first_failure_trial,
                "experiments_to_first_failure": r.experiments_to_first_failure,
                "best_robustness": r.best_robustness,
                "confirmed_failures": r.confirmed_failures,
                "reproduction_rate": r.reproduction_rate,
                "valid_observations": r.valid_observations,
                "invalid_attempts": r.invalid_attempts,
                "rejected_proposals": r.rejected_proposals,
                "boundary_experiments": r.boundary_experiments,
                "boundary_best_abs_robustness": r.boundary_best_abs_robustness,
                "total_deadline_misses": r.total_deadline_misses,
                "total_failed_reads": r.total_failed_reads,
            })


def _save_json(comparison: dict, path: Path) -> None:
    with open(path, "w") as f:
        json.dump(comparison, f, indent=2, default=str)


def _save_markdown_report(
    comparison: dict,
    tpe_results: list[CampaignResult],
    random_results: list[CampaignResult],
    path: Path,
    benchmark: str,
    budget: int,
) -> None:
    """Generate a readable Markdown comparison report."""
    lines = [
        f"# ChipCheck Comparison Report — Benchmark {benchmark}",
        "",
        "> **NOTE**: All results are from a *synthetic simulator*.",
        "> Do not interpret these as real hardware measurements.",
        "",
        f"- **Benchmark**: {benchmark}",
        f"- **Budget**: {budget} experiments per campaign",
        f"- **Seeds**: {len(tpe_results)}",
        "",
        "## Summary",
        "",
        "| Metric | TPE (mean ± std) | Random (mean ± std) |",
        "|--------|-------------------|---------------------|",
    ]

    metrics = [
        ("Failure discovery rate", "failure_discovery_rate"),
        ("Experiments to first failure", "experiments_to_first_failure"),
        ("Best robustness", "best_robustness"),
        ("Confirmed failures", "confirmed_failures"),
        ("Reproduction rate", "reproduction_rate"),
        ("Valid observations", "valid_observations"),
        ("Boundary experiments", "boundary_experiments"),
        ("Boundary best |R|", "boundary_best_abs_robustness"),
    ]

    for label, key in metrics:
        tpe_s = comparison["tpe"][key]
        rand_s = comparison["random"][key]
        tpe_str = _fmt_stat(tpe_s)
        rand_str = _fmt_stat(rand_s)
        lines.append(f"| {label} | {tpe_str} | {rand_str} |")

    lines.extend([
        "",
        "## Interpretation",
        "",
        "- **Failure discovery rate**: Fraction of seeds where at least one DUT_FAILURE was found.",
        "- **Experiments to first failure**: How many experiments were needed to discover the first failure.",
        "  Lower is better for adaptive testing.",
        "- **Best robustness**: Most negative value indicates strongest failure found.",
        "- **Reproduction rate**: Fraction of confirmation replays that reproduced the failure.",
        "",
        "## Limitations",
        "",
        "- Results are from a synthetic simulator with known failure equations.",
        "- TPE uses density estimation, not calibrated uncertainty.",
        "- Statistical significance is not claimed without further analysis.",
        "- Small seed counts may not capture full variance.",
        "",
        "---",
        "*Generated by ChipCheck v0.1.0*",
    ])

    with open(path, "w") as f:
        f.write("\n".join(lines))


def _fmt_stat(s: dict) -> str:
    if s["mean"] is None:
        return "N/A"
    if s["std"] is not None and s["std"] > 0:
        return f"{s['mean']:.3f} ± {s['std']:.3f}"
    return f"{s['mean']:.3f}"


def run_suite(
    contract_path: str,
    budget: int = 100,
    seeds: int = 10,
    output_dir: str = "output",
) -> dict:
    """Run comparison on all benchmarks."""
    results = {}
    for bm in ["B1", "B2", "B3", "B4"]:
        logger.info("=== Running suite: Benchmark %s ===", bm)
        bm_dir = str(Path(output_dir) / bm)
        results[bm] = compare_planners(
            contract_path=contract_path,
            benchmark=bm,
            budget=budget,
            seeds=seeds,
            output_dir=bm_dir,
        )

    # Save combined report
    _save_suite_report(results, Path(output_dir) / "suite_report.md", budget, seeds)

    return results


def _save_suite_report(results: dict, path: Path, budget: int, seeds: int) -> None:
    lines = [
        "# ChipCheck Full Suite Report",
        "",
        "> All results are from a synthetic simulator.",
        "",
        f"- **Budget**: {budget} per campaign",
        f"- **Seeds**: {seeds}",
        "",
    ]

    for bm, comp in results.items():
        lines.extend([
            f"## Benchmark {bm}",
            "",
            f"**{GROUND_TRUTH.get(bm, lambda p: 'unknown').__doc__}**" if bm in GROUND_TRUTH else "",
            "",
            "| Metric | TPE | Random |",
            "|--------|-----|--------|",
        ])
        for label, key in [
            ("Discovery rate", "failure_discovery_rate"),
            ("Exp to 1st failure", "experiments_to_first_failure"),
            ("Best robustness", "best_robustness"),
            ("Confirmed failures", "confirmed_failures"),
        ]:
            tpe_s = comp["tpe"].get(key, {})
            rand_s = comp["random"].get(key, {})
            lines.append(f"| {label} | {_fmt_stat(tpe_s)} | {_fmt_stat(rand_s)} |")
        lines.append("")

    lines.append("---\n*Generated by ChipCheck v0.1.0*")

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines))

