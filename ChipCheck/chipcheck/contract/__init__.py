"""YAML contract loader and validator for ChipCheck experiment contracts."""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any

from chipcheck.models import (
    ExperimentContract, ParameterDef, ParamType, Constraint,
    FunctionalRequirement, SafetyLimit,
)


def _parse_param(d: dict) -> ParameterDef:
    """Parse a single parameter definition from YAML dict."""
    pt = ParamType(d["type"])
    return ParameterDef(
        name=d["name"],
        param_type=pt,
        low=d.get("low"),
        high=d.get("high"),
        step=d.get("step"),
        choices=d.get("choices"),
        default=d.get("default"),
        condition=d.get("condition"),
        description=d.get("description", ""),
    )


def load_contract(path: str | Path) -> ExperimentContract:
    """Load an experiment contract from a YAML file."""
    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    params = [_parse_param(p) for p in raw.get("parameters", [])]

    constraints = []
    for c in raw.get("constraints", []):
        constraints.append(Constraint(
            expression=c["expression"],
            description=c.get("description", ""),
        ))

    requirements = []
    for r in raw.get("requirements", []):
        requirements.append(FunctionalRequirement(
            name=r["name"],
            metric=r["metric"],
            operator=r["operator"],
            threshold=r["threshold"],
            description=r.get("description", ""),
            is_primary=r.get("is_primary", False),
        ))

    safety_limits = []
    for s in raw.get("safety_limits", []):
        safety_limits.append(SafetyLimit(
            parameter=s["parameter"],
            min_value=s.get("min_value"),
            max_value=s.get("max_value"),
            description=s.get("description", ""),
        ))

    sc = raw.get("stopping_conditions", {})

    return ExperimentContract(
        contract_id=raw.get("contract_id", ""),
        version=raw.get("version", "1.0"),
        name=raw.get("name", ""),
        description=raw.get("description", ""),
        parameters=params,
        constraints=constraints,
        requirements=requirements,
        safety_limits=safety_limits,
        required_measurements=raw.get("required_measurements", []),
        budget=raw.get("budget", 100),
        stopping_conditions=sc,
    )


def validate_contract(contract: ExperimentContract) -> list[str]:
    """Validate an experiment contract. Returns list of error messages (empty = valid)."""
    errors = []

    if not contract.contract_id:
        errors.append("Missing contract_id")
    if not contract.parameters:
        errors.append("No parameters defined")
    if contract.budget < 1:
        errors.append("Budget must be >= 1")

    param_names = set()
    for p in contract.parameters:
        if p.name in param_names:
            errors.append(f"Duplicate parameter name: {p.name}")
        param_names.add(p.name)

        if p.param_type in (ParamType.CONTINUOUS, ParamType.INTEGER):
            if p.low is None or p.high is None:
                errors.append(f"Parameter '{p.name}': continuous/integer must have low and high")
            elif p.low > p.high:
                errors.append(f"Parameter '{p.name}': low ({p.low}) > high ({p.high})")
            if p.param_type == ParamType.INTEGER:
                if p.low is not None and p.low != int(p.low):
                    errors.append(f"Parameter '{p.name}': integer low must be an integer")
                if p.high is not None and p.high != int(p.high):
                    errors.append(f"Parameter '{p.name}': integer high must be an integer")

        if p.param_type == ParamType.CATEGORICAL:
            if not p.choices or len(p.choices) < 1:
                errors.append(f"Parameter '{p.name}': categorical must have choices")

        if p.condition:
            parent = p.condition.get("parent")
            if parent and parent not in param_names:
                # Might be defined later, but we check for existence
                found = any(pp.name == parent for pp in contract.parameters)
                if not found:
                    errors.append(f"Parameter '{p.name}': condition parent '{parent}' not found")

    for r in contract.requirements:
        if r.operator not in ("<=", ">=", "<", ">", "=="):
            errors.append(f"Requirement '{r.name}': invalid operator '{r.operator}'")

    return errors

