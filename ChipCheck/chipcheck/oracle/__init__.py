"""Measurement oracle and robustness calculator for ChipCheck.

The oracle evaluates experiment results and produces verdicts.
It is separate from the planner and the executor.

Oracle outcomes:
- PASS: All requirements satisfied with valid evidence
- DUT_FAILURE: At least one functional requirement violated with valid evidence
- INVALID_EXPERIMENT: Insufficient or invalid measurement data
- INCONCLUSIVE: Cannot determine pass/fail from available evidence
- SAFETY_ABORT: Experiment was aborted for safety reasons

Robustness convention:
  R > 0: PASS, positive margin
  R = 0: requirement boundary
  R < 0: requirement violation

For deadline: R_deadline = deadline_ms - max_read_execution_time_ms
"""

from __future__ import annotations

import logging
from typing import Optional

from chipcheck.models import (
    ExperimentContract, ExperimentConfig, ExecutionResult, ExecutionStatus,
    OracleOutcome, OracleVerdict, FunctionalRequirement,
)

logger = logging.getLogger(__name__)


def _evaluate_requirement(
    req: FunctionalRequirement,
    value: Optional[float],
) -> tuple[bool, Optional[float]]:
    """Evaluate a single requirement.

    Returns (satisfied, normalized_margin).
    Margin is positive when satisfied, negative when violated.
    """
    if value is None:
        return False, None

    threshold = req.threshold
    if threshold == 0:
        # Avoid division by zero in normalization
        norm = 1.0
    else:
        norm = abs(threshold)

    if req.operator == "<=":
        margin = (threshold - value) / norm
        satisfied = value <= threshold
    elif req.operator == ">=":
        margin = (value - threshold) / norm
        satisfied = value >= threshold
    elif req.operator == "<":
        margin = (threshold - value) / norm
        satisfied = value < threshold
    elif req.operator == ">":
        margin = (value - threshold) / norm
        satisfied = value > threshold
    elif req.operator == "==":
        margin = -abs(value - threshold) / norm if value != threshold else 0.0
        satisfied = value == threshold
    else:
        return False, None

    return satisfied, margin


def evaluate(
    result: ExecutionResult,
    contract: ExperimentContract,
    config: Optional[ExperimentConfig] = None,
) -> OracleVerdict:
    """Evaluate an experiment result against the contract requirements.

    Does NOT automatically treat FAILED status as a confirmed timing failure.
    Does NOT treat ABORTED as a normal functional failure.
    Missing or invalid measurement evidence is never classified as PASS.
    """
    # Handle ABORTED status
    if result.status == ExecutionStatus.ABORTED:
        return OracleVerdict(
            outcome=OracleOutcome.SAFETY_ABORT,
            robustness=None,
            details={"reason": "Experiment was aborted"},
        )

    measurements = result.results

    # Check for minimum valid data (measurement quality)
    # Only enforce sample count when total_samples is a required measurement
    # (e.g., ESP32 timing tests). Skip for binary-outcome domains (e.g., raspi pins).
    if "total_samples" in contract.required_measurements:
        total_samples = measurements.get("total_samples", 0)
        min_samples_threshold = 2
        for req in contract.requirements:
            if req.metric == "total_samples" and req.operator in (">=", ">"):
                min_samples_threshold = int(req.threshold)
                break

        if total_samples < min_samples_threshold:
            if result.status == ExecutionStatus.FAILED:
                return OracleVerdict(
                    outcome=OracleOutcome.INCONCLUSIVE,
                    robustness=None,
                    details={"reason": f"Insufficient samples ({total_samples} < {min_samples_threshold}); status FAILED"},
                )
            return OracleVerdict(
                outcome=OracleOutcome.INVALID_EXPERIMENT,
                robustness=None,
                details={"reason": f"Insufficient samples collected ({total_samples} < {min_samples_threshold})"},
            )

    # Check required measurements
    for field_name in contract.required_measurements:
        if field_name not in measurements:
            return OracleVerdict(
                outcome=OracleOutcome.INVALID_EXPERIMENT,
                robustness=None,
                details={"reason": f"Missing required measurement: {field_name}"},
            )

    # Evaluate all functional requirements
    all_satisfied = True
    has_primary_failure = False
    requirement_margins: dict[str, float] = {}
    details: dict = {"requirement_results": {}}

    for req in contract.requirements:
        threshold = req.threshold
        if (req.metric == "max_read_execution_time_ms" and config
                and "deadline_ms" in config.parameters):
            threshold = float(config.parameters["deadline_ms"])

        effective_req = FunctionalRequirement(
            name=req.name,
            metric=req.metric,
            operator=req.operator,
            threshold=threshold,
            description=req.description,
            is_primary=req.is_primary,
        )

        value = measurements.get(req.metric)
        satisfied, margin = _evaluate_requirement(effective_req, value)

        # Confirm consistency with missed_deadlines counter
        if req.is_primary or req.metric == "max_read_execution_time_ms":
            if measurements.get("missed_deadlines", 0) > 0:
                satisfied = False
                if margin is not None and margin >= 0:
                    margin = -0.01

        if margin is not None:
            requirement_margins[req.name] = margin

        details["requirement_results"][req.name] = {
            "metric": req.metric,
            "value": value,
            "threshold": threshold,
            "operator": req.operator,
            "satisfied": satisfied,
            "margin": margin,
        }

        if not satisfied:
            all_satisfied = False
            if req.is_primary:
                has_primary_failure = True

    # Calculate overall robustness as minimum normalized margin
    valid_margins = [m for m in requirement_margins.values() if m is not None]
    if valid_margins:
        robustness = min(valid_margins)
    else:
        robustness = None

    # Determine outcome
    if robustness is None:
        outcome = OracleOutcome.INCONCLUSIVE
    elif all_satisfied:
        outcome = OracleOutcome.PASS
    else:
        outcome = OracleOutcome.DUT_FAILURE

    return OracleVerdict(
        outcome=outcome,
        robustness=robustness,
        details=details,
        requirement_margins=requirement_margins,
    )


def calculate_robustness(
    result: ExecutionResult,
    contract: ExperimentContract,
    config: Optional[ExperimentConfig] = None,
) -> Optional[float]:
    """Calculate the overall signed robustness score.

    R > 0: all requirements satisfied (positive margin)
    R = 0: at requirement boundary
    R < 0: at least one requirement violated

    Returns None if insufficient data.
    """
    verdict = evaluate(result, contract, config=config)
    return verdict.robustness

