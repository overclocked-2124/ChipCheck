"""Independent safety validator for ChipCheck experiment configurations.

The safety validator operates independently of the optimizer.
No proposed configuration may reach the executor without validation.
"""

from __future__ import annotations

import logging
from typing import Any

from chipcheck.models import ExperimentContract, ExperimentConfig, ParamType

logger = logging.getLogger(__name__)


class SafetyValidationError(Exception):
    """Raised when a configuration fails safety validation."""
    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__(f"Safety validation failed: {'; '.join(reasons)}")


def validate_configuration(
    config: ExperimentConfig,
    contract: ExperimentContract,
) -> list[str]:
    """Validate an experiment configuration against the contract.

    Returns a list of rejection reasons (empty = valid).
    The optimizer cannot bypass this validator.
    """
    reasons = []
    params = config.parameters

    for pdef in contract.parameters:
        # Check conditional parameters
        if pdef.condition:
            parent_name = pdef.condition.get("parent")
            allowed_values = pdef.condition.get("values", [])
            parent_val = params.get(parent_name)
            if parent_val not in allowed_values:
                # Conditional parameter not active; skip validation but
                # ensure it's not present with an invalid value
                if pdef.name in params:
                    # It's fine to include inactive conditional params
                    pass
                continue

        if pdef.name not in params:
            if pdef.default is not None:
                continue  # Will use default
            if pdef.condition:
                continue  # Conditional and parent didn't match
            reasons.append(f"Missing required parameter: {pdef.name}")
            continue

        val = params[pdef.name]

        # Type checks
        if pdef.param_type == ParamType.CONTINUOUS:
            if not isinstance(val, (int, float)):
                reasons.append(f"Parameter '{pdef.name}': expected number, got {type(val).__name__}")
                continue
            if pdef.low is not None and val < pdef.low:
                reasons.append(f"Parameter '{pdef.name}': {val} < min {pdef.low}")
            if pdef.high is not None and val > pdef.high:
                reasons.append(f"Parameter '{pdef.name}': {val} > max {pdef.high}")
            if pdef.step is not None and pdef.step > 0 and pdef.low is not None:
                steps = (val - pdef.low) / pdef.step
                if abs(steps - round(steps)) > 1e-7:
                    reasons.append(f"Parameter '{pdef.name}': {val} not aligned to step {pdef.step} from {pdef.low}")

        elif pdef.param_type == ParamType.INTEGER:
            if not isinstance(val, int) or isinstance(val, bool):
                reasons.append(f"Parameter '{pdef.name}': expected integer, got {type(val).__name__}")
                continue
            if pdef.low is not None and val < pdef.low:
                reasons.append(f"Parameter '{pdef.name}': {val} < min {int(pdef.low)}")
            if pdef.high is not None and val > pdef.high:
                reasons.append(f"Parameter '{pdef.name}': {val} > max {int(pdef.high)}")
            if pdef.step is not None and pdef.step > 0:
                base = int(pdef.low) if pdef.low is not None else 0
                if (val - base) % int(pdef.step) != 0:
                    reasons.append(
                        f"Parameter '{pdef.name}': {val} not aligned to step {int(pdef.step)} from {base}"
                    )

        elif pdef.param_type == ParamType.BOOLEAN:
            if not isinstance(val, bool):
                reasons.append(f"Parameter '{pdef.name}': expected boolean, got {type(val).__name__}")

        elif pdef.param_type == ParamType.CATEGORICAL:
            if pdef.choices and val not in pdef.choices:
                reasons.append(
                    f"Parameter '{pdef.name}': '{val}' not in allowed values {pdef.choices}"
                )

    # Safety limits
    for sl in contract.safety_limits:
        val = params.get(sl.parameter)
        if val is not None:
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                reasons.append(
                    f"Safety limit '{sl.parameter}': non-numeric value '{val}'"
                )
                continue
            if sl.min_value is not None and val < sl.min_value:
                reasons.append(
                    f"Safety limit '{sl.parameter}': {val} < min {sl.min_value} — {sl.description}"
                )
            if sl.max_value is not None and val > sl.max_value:
                reasons.append(
                    f"Safety limit '{sl.parameter}': {val} > max {sl.max_value} — {sl.description}"
                )

    # Cross-parameter constraints
    for constraint in contract.constraints:
        try:
            if not eval(constraint.expression, {"__builtins__": {}}, params):
                reasons.append(
                    f"Constraint violated: {constraint.expression} — {constraint.description}"
                )
        except Exception as e:
            reasons.append(f"Constraint evaluation error: {constraint.expression} — {e}")

    if reasons:
        logger.warning("Configuration rejected: %s", reasons)

    return reasons

