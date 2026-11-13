"""Data models for ChipCheck experiment contracts, results, and oracle outcomes."""

from __future__ import annotations

import enum
import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Parameter types
# ---------------------------------------------------------------------------

class ParamType(enum.Enum):
    CONTINUOUS = "continuous"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    CATEGORICAL = "categorical"


@dataclass
class ParameterDef:
    """Declarative definition of a single experiment parameter."""
    name: str
    param_type: ParamType
    # Continuous / Integer
    low: Optional[float] = None
    high: Optional[float] = None
    step: Optional[float] = None
    # Categorical
    choices: Optional[list] = None
    # Default / nominal
    default: Any = None
    # Conditional: parameter is active only when condition is met
    condition: Optional[dict] = None  # {"parent": "param_name", "values": [...]}
    description: str = ""


# ---------------------------------------------------------------------------
# Cross-parameter constraint
# ---------------------------------------------------------------------------

@dataclass
class Constraint:
    """A cross-parameter constraint expressed as a Python expression string."""
    expression: str
    description: str = ""


# ---------------------------------------------------------------------------
# Functional requirement
# ---------------------------------------------------------------------------

@dataclass
class FunctionalRequirement:
    """A single functional requirement with a threshold."""
    name: str
    metric: str           # field name in result measurements
    operator: str         # "<=", ">=", "<", ">", "=="
    threshold: float
    description: str = ""
    is_primary: bool = False


# ---------------------------------------------------------------------------
# Safety limit
# ---------------------------------------------------------------------------

@dataclass
class SafetyLimit:
    """A hard safety limit on a parameter or derived quantity."""
    parameter: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    description: str = ""


# ---------------------------------------------------------------------------
# Experiment contract
# ---------------------------------------------------------------------------

@dataclass
class ExperimentContract:
    """Full declarative experiment contract."""
    contract_id: str = ""
    version: str = "1.0"
    name: str = ""
    description: str = ""
    parameters: list[ParameterDef] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    requirements: list[FunctionalRequirement] = field(default_factory=list)
    safety_limits: list[SafetyLimit] = field(default_factory=list)
    required_measurements: list[str] = field(default_factory=list)
    budget: int = 100
    stopping_conditions: dict = field(default_factory=dict)

    def get_parameter(self, name: str) -> Optional[ParameterDef]:
        for p in self.parameters:
            if p.name == name:
                return p
        return None


# ---------------------------------------------------------------------------
# Experiment configuration
# ---------------------------------------------------------------------------

@dataclass
class ExperimentConfig:
    """A concrete experiment configuration to be executed."""
    experiment_id: int
    command: str = "RUN_TIMING_TEST"
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "experiment_id": self.experiment_id,
            "command": self.command,
            "parameters": self.parameters,
        }, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "ExperimentConfig":
        d = json.loads(s)
        return cls(
            experiment_id=d["experiment_id"],
            command=d.get("command", "RUN_TIMING_TEST"),
            parameters=d.get("parameters", {}),
        )


# ---------------------------------------------------------------------------
# Execution status
# ---------------------------------------------------------------------------

class ExecutionStatus(enum.Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


# ---------------------------------------------------------------------------
# Execution result
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    """Structured result from an experiment execution."""
    experiment_id: int
    status: ExecutionStatus
    results: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "experiment_id": self.experiment_id,
            "status": self.status.value,
            "results": self.results,
        }, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "ExecutionResult":
        d = json.loads(s)
        return cls(
            experiment_id=d["experiment_id"],
            status=ExecutionStatus(d["status"]),
            results=d.get("results", {}),
        )


# ---------------------------------------------------------------------------
# Oracle outcome
# ---------------------------------------------------------------------------

class OracleOutcome(enum.Enum):
    PASS = "PASS"
    DUT_FAILURE = "DUT_FAILURE"
    INVALID_EXPERIMENT = "INVALID_EXPERIMENT"
    INCONCLUSIVE = "INCONCLUSIVE"
    SAFETY_ABORT = "SAFETY_ABORT"


@dataclass
class OracleVerdict:
    """Full oracle evaluation of an experiment result."""
    outcome: OracleOutcome
    robustness: Optional[float] = None
    details: dict[str, Any] = field(default_factory=dict)
    requirement_margins: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Campaign record
# ---------------------------------------------------------------------------

@dataclass
class CampaignRecord:
    """A single experiment record in a campaign."""
    campaign_id: str
    experiment_id: int
    config: ExperimentConfig
    result: Optional[ExecutionResult] = None
    verdict: Optional[OracleVerdict] = None
    phase: str = "discovery"          # discovery, confirmation, boundary
    planner_type: str = "tpe"
    benchmark: str = ""
    seed: int = 0
    trial_index: int = 0
    timestamp: str = ""

