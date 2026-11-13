"""ChipCheck CLI — Main entry point.

Commands:
    validate-contract  Validate an experiment contract YAML file.
    run               Run a single campaign (TPE or Random).
    compare           Compare TPE vs Random on a benchmark.
    run-suite         Run comparison on all benchmarks.
    report            Show report for a campaign.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def resolve_path(p: str | Path) -> str:
    path_obj = Path(p)
    if path_obj.is_absolute() and path_obj.exists():
        return str(path_obj)
    if path_obj.exists():
        return str(path_obj.resolve())
    candidate = project_root / p
    if candidate.exists():
        return str(candidate.resolve())
    return str(path_obj.resolve())

from chipcheck.contract import load_contract, validate_contract
from chipcheck.campaign import run_campaign, CampaignResult
from chipcheck.evaluation import compare_planners, run_suite
from chipcheck.storage import CampaignStorage


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_validate_contract(args):
    """Validate an experiment contract."""
    contract = load_contract(resolve_path(args.contract))
    errors = validate_contract(contract)

    if errors:
        print(f"Contract validation FAILED ({len(errors)} errors):")
        for e in errors:
            print(f"  - {e}")
        return 1
    else:
        print(f"Contract '{contract.name}' is valid.")
        print(f"   ID: {contract.contract_id}")
        print(f"   Version: {contract.version}")
        print(f"   Parameters: {len(contract.parameters)}")
        print(f"   Requirements: {len(contract.requirements)}")
        print(f"   Constraints: {len(contract.constraints)}")
        print(f"   Budget: {contract.budget}")
        return 0


def cmd_run(args):
    """Run a single campaign."""
    contract = load_contract(resolve_path(args.contract))
    errors = validate_contract(contract)
    if errors:
        print(f"❌ Contract invalid: {errors}")
        return 1

    if contract.contract_id.startswith("raspi_"):
        # Raspberry Pi runs are console-first and keep campaign state in RAM.
        logging.getLogger("chipcheck.campaign").setLevel(logging.WARNING)
        result = run_campaign(
            contract=contract,
            planner_type=args.planner,
            benchmark=args.benchmark,
            budget=args.budget,
            seed=args.seed,
            output_dir=str(project_root),
            hardware_port=args.hardware_port,
            console_only=True,
            single_region_search=args.single_region,
            localize_pin_ranges=not args.skip_localization,
        )
        if result.first_failure_trial is None:
            print(f"No failing pin configuration found in {result.experiments_executed} tests.")
        else:
            failures = result.discovery_failures
            print(f"\nResult: {len(failures)} failing discovery tests; {result.experiments_executed} total tests including range probes.")
            if result.localized_regions:
                for index, region in enumerate(result.localized_regions, start=1):
                    ranges = ", ".join(
                        f"{name}={bounds[0]:.4f}..{bounds[1]:.4f}V"
                        for name, bounds in region.items()
                    )
                    print(f"  Failing region {index}: {ranges}")
            else:
                print("  Failure found, but no complete range was localized.")
    else:
        result = run_campaign(
            contract=contract,
            planner_type=args.planner,
            benchmark=args.benchmark,
            budget=args.budget,
            seed=args.seed,
            output_dir=resolve_path(args.output),
            hardware_port=args.hardware_port,
        )
        _print_result(result)
    return 0


def cmd_compare(args):
    """Compare TPE vs Random."""
    comparison = compare_planners(
        contract_path=resolve_path(args.contract),
        benchmark=args.benchmark,
        budget=args.budget,
        seeds=args.seeds,
        output_dir=resolve_path(args.output),
    )

    print(f"\n📊 Comparison complete for benchmark {args.benchmark}")
    print(f"   Seeds: {args.seeds}, Budget: {args.budget}")
    print(f"   Results saved to: {args.output}/")

    # Print summary
    for planner in ["tpe", "random"]:
        p = comparison[planner]
        print(f"\n  {planner.upper()}:")
        fdr = p["failure_discovery_rate"]
        print(f"    Discovery rate: {fdr['mean']:.1%}" if fdr['mean'] is not None else "    Discovery rate: N/A")
        etf = p["experiments_to_first_failure"]
        print(f"    Avg exp to 1st failure: {etf['mean']:.1f}" if etf['mean'] is not None else "    Avg exp to 1st failure: N/A")
        br = p["best_robustness"]
        print(f"    Best robustness: {br['mean']:.4f}" if br['mean'] is not None else "    Best robustness: N/A")

    return 0


def cmd_run_suite(args):
    """Run comparison on all benchmarks."""
    results = run_suite(
        contract_path=resolve_path(args.contract),
        budget=args.budget,
        seeds=args.seeds,
        output_dir=resolve_path(args.output),
    )

    print(f"\n📊 Full suite complete")
    print(f"   Results saved to: {args.output}/")

    for bm, comp in results.items():
        tpe_dr = comp["tpe"]["failure_discovery_rate"]["mean"]
        rand_dr = comp["random"]["failure_discovery_rate"]["mean"]
        print(f"\n  {bm}: TPE discovery={tpe_dr:.0%}, Random discovery={rand_dr:.0%}" if tpe_dr is not None else f"\n  {bm}: N/A")

    return 0


def cmd_report(args):
    """Show report for a campaign."""
    output_dir = resolve_path(args.output)
    db_path = str(Path(output_dir) / "chipcheck_results.db")
    try:
        storage = CampaignStorage(db_path)
    except Exception as e:
        print(f"❌ Cannot open database: {e}")
        return 1

    if args.campaign_id:
        campaign = storage.get_campaign(args.campaign_id)
        if not campaign:
            print(f"❌ Campaign '{args.campaign_id}' not found")
            return 1
        experiments = storage.get_campaign_experiments(args.campaign_id)
        confirmations = storage.get_campaign_confirmations(args.campaign_id)
        boundary = storage.get_campaign_boundary(args.campaign_id)
        rejected = storage.get_rejected_proposals(args.campaign_id)

        print(f"📋 Campaign: {args.campaign_id}")
        print(f"   Planner: {campaign['planner_type']}")
        print(f"   Benchmark: {campaign['benchmark']}")
        print(f"   Seed: {campaign['seed']}")
        print(f"   Budget: {campaign['budget']}")
        print(f"   Status: {campaign['status']}")
        print(f"   Experiments: {len(experiments)}")
        print(f"   Confirmations: {len(confirmations)}")
        print(f"   Boundary: {len(boundary)}")
        print(f"   Rejected: {len(rejected)}")

        # Show failures
        failures = [e for e in experiments if e.get("oracle_outcome") == "DUT_FAILURE"]
        if failures:
            print(f"\n   Failures found: {len(failures)}")
            for f in failures[:5]:
                print(f"     Trial {f['trial_index']}: robustness={f['robustness']:.4f}" if f.get('robustness') is not None else f"     Trial {f['trial_index']}: robustness=N/A")
    else:
        campaigns = storage.list_campaigns()
        if not campaigns:
            print("No campaigns found.")
            return 0
        print(f"📋 {len(campaigns)} campaign(s):")
        for c in campaigns:
            print(f"  {c['campaign_id']}  {c['planner_type']:6s}  {c['benchmark']:4s}  seed={c['seed']}  {c['status']}")

    storage.close()
    return 0


def _print_result(result: CampaignResult):
    """Print campaign result summary."""
    print(f"\n{'='*60}")
    print(f"Campaign: {result.campaign_id}")
    print(f"{'='*60}")
    print(f"  Planner:            {result.planner_type.upper()}")
    print(f"  Benchmark:          {result.benchmark}")
    print(f"  Seed:               {result.seed}")
    print(f"  Budget:             {result.budget}")
    print(f"  Experiments run:    {result.experiments_executed}")
    print(f"  Valid observations: {result.valid_observations}")
    print(f"  Invalid attempts:   {result.invalid_attempts}")
    print(f"  Rejected proposals: {result.rejected_proposals}")
    print(f"  Best robustness:    {result.best_robustness}")

    if result.first_failure_trial is not None:
        print(f"\n  ⚠️  First failure at trial:  {result.first_failure_trial}")
        print(f"  Experiments to 1st failure: {result.experiments_to_first_failure}")
        print(f"  Total failures discovered:  {len(result.discovery_failures)}")

        if result.confirmation_results:
            print(f"\n  Confirmation replays:      {len(result.confirmation_results)}")
            print(f"  Reproduction rate:         {result.reproduction_rate:.0%}" if result.reproduction_rate is not None else "  Reproduction rate: N/A")
            print(f"  Confirmed failures:        {result.confirmed_failures}")

        if result.boundary_experiments > 0:
            print(f"\n  Boundary experiments:      {result.boundary_experiments}")
            print(f"  Best |R| at boundary:      {result.boundary_best_abs_robustness}")
            if result.nearest_pass_robustness is not None:
                print(f"  Nearest PASS robustness:   {result.nearest_pass_robustness:.4f}")
            if result.nearest_fail_robustness is not None:
                print(f"  Nearest FAIL robustness:   {result.nearest_fail_robustness:.4f}")
    else:
        print(f"\n  ✅ No failures discovered within budget")

    print(f"\n  Deadline misses (total):   {result.total_deadline_misses}")
    print(f"  Failed reads (total):      {result.total_failed_reads}")


def main():
    parser = argparse.ArgumentParser(
        prog="chipcheck",
        description="ChipCheck — Adaptive Experiment Selection and Timing-Test Engine",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # validate-contract
    p_val = subparsers.add_parser("validate-contract", help="Validate experiment contract")
    p_val.add_argument("--contract", default="contracts/esp32_timing.yaml",
                       help="Path to contract YAML")

    # run
    p_run = subparsers.add_parser("run", help="Run a single campaign")
    p_run.add_argument("--contract", default="contracts/esp32_timing.yaml")
    p_run.add_argument("--benchmark", default="B1", choices=["B1", "B2", "B3", "B4", "R1", "R2", "R3", "R4", "R5"])
    p_run.add_argument("--planner", default="tpe", choices=["tpe", "random"])
    p_run.add_argument("--budget", type=int, default=40,
                       help="Discovery budget (default: 40); Raspberry Pi range probes run afterward")
    p_run.add_argument("--seed", type=int, default=42)
    p_run.add_argument("--output", default="output")
    p_run.add_argument("--hardware-port", default=None,
                       help="Serial port for a Raspberry Pi test controller (e.g. COM4); omit for simulation")
    p_run.add_argument("--single-region", action="store_true",
                       help="Stop at the first failure and binary-search one contiguous region; skips other fault windows")
    p_run.add_argument("--skip-localization", action="store_true",
                       help="Do not run additional pin-range probes after discovery")

    # compare
    p_cmp = subparsers.add_parser("compare", help="Compare TPE vs Random")
    p_cmp.add_argument("--contract", default="contracts/esp32_timing.yaml")
    p_cmp.add_argument("--benchmark", default="B1", choices=["B1", "B2", "B3", "B4"])
    p_cmp.add_argument("--budget", type=int, default=100)
    p_cmp.add_argument("--seeds", type=int, default=10)
    p_cmp.add_argument("--output", default="output")

    # run-suite
    p_suite = subparsers.add_parser("run-suite", help="Run all benchmarks")
    p_suite.add_argument("--contract", default="contracts/esp32_timing.yaml")
    p_suite.add_argument("--budget", type=int, default=100)
    p_suite.add_argument("--seeds", type=int, default=10)
    p_suite.add_argument("--output", default="output")

    # report
    p_rep = subparsers.add_parser("report", help="Show campaign report")
    p_rep.add_argument("--campaign-id", default=None)
    p_rep.add_argument("--output", default="output")

    args = parser.parse_args()
    setup_logging(args.verbose if hasattr(args, 'verbose') else False)

    if args.command is None:
        parser.print_help()
        return 1

    commands = {
        "validate-contract": cmd_validate_contract,
        "run": cmd_run,
        "compare": cmd_compare,
        "run-suite": cmd_run_suite,
        "report": cmd_report,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main() or 0)

