"""Raspberry Pi pin interaction simulator for ChipCheck.

Simulates a Raspberry Pi where certain combinations of LED pin voltages
cause a buzzer to malfunction. The failure region is a hyperrectangle
in the 3D voltage space that the planner must discover.

The planner does NOT know the failure region. It sees only:
  buzzer_working: 1 (pass) or 0 (fail)

This simulator can later be replaced by a real hardware executor
that talks to a Raspberry Pi over GPIO — without changing the planner.
"""

from __future__ import annotations

import random
from typing import Any, Optional

from chipcheck.models import ExperimentConfig, ExecutionResult, ExecutionStatus
from chipcheck.executor import ExperimentExecutor


class PinScenario:
    """A hidden failure scenario for the Raspberry Pi simulator.

    Defines a hyperrectangular failure region in the LED voltage space.
    When ALL LED voltages fall within their respective failure ranges
    simultaneously, the buzzer malfunctions.
    """

    def __init__(
        self,
        name: str,
        description: str,
        failure_region: dict[str, tuple[float, float]] | list[dict[str, tuple[float, float]]],
    ):
        self.name = name
        self.description = description
        # A scenario may have one box or several disjoint boxes. A box is an
        # AND across pins; the list of boxes is an OR across regions.
        self.failure_regions = (
            ([failure_region] if failure_region else [])
            if isinstance(failure_region, dict) else failure_region
        )


# ---------------------------------------------------------------------------
# Pre-built scenarios (ground truth is PRIVATE — planner never sees these)
# ---------------------------------------------------------------------------

RASPI_SCENARIOS = {
    "R1": PinScenario(
        name="R1",
        description="User's example: wide LED1, narrow LED2, medium LED3",
        failure_region={
            "led1_voltage": (1.1, 2.2),
            "led2_voltage": (2.1, 2.3),
            "led3_voltage": (1.7, 2.1),
        },
    ),
    "R2": PinScenario(
        name="R2",
        description="Wide failure region (easy to discover, good for demos)",
        failure_region={
            "led1_voltage": (0.8, 2.5),
            "led2_voltage": (1.0, 2.8),
            "led3_voltage": (0.5, 2.5),
        },
    ),
    "R3": PinScenario(
        name="R3",
        description="Small off-center cube (hard to discover)",
        failure_region={
            "led1_voltage": (2.5, 2.8),
            "led2_voltage": (0.5, 0.8),
            "led3_voltage": (2.8, 3.1),
        },
    ),
    "R4": PinScenario(
        name="R4",
        description="No-fault scenario (control — no failure region exists)",
        failure_region={},
    ),
    "R5": PinScenario(
        name="R5",
        description="Two disjoint LED 1 windows with the same LED 2/3 conditions",
        failure_region=[
            {"led1_voltage": (1.0, 1.4), "led2_voltage": (1.7, 2.2), "led3_voltage": (1.7, 2.1)},
            {"led1_voltage": (2.0, 2.4), "led2_voltage": (1.7, 2.2), "led3_voltage": (1.7, 2.1)},
        ],
    ),
}


def _in_failure_region(params: dict, scenario: PinScenario) -> bool:
    """Check if the given parameters fall within the failure region.

    Returns True (= failure) only when ALL parameters are simultaneously
    within their respective failure ranges.
    """
    return any(
        all(lo <= params.get(param_name, 0.0) <= hi
            for param_name, (lo, hi) in region.items())
        for region in scenario.failure_regions
    )


# Ground truth predicates — PRIVATE, used only for evaluation, never by planner
RASPI_GROUND_TRUTH = {
    name: (lambda params, sc=scenario: _in_failure_region(params, sc))
    for name, scenario in RASPI_SCENARIOS.items()
}


class RaspiPinSimulator(ExperimentExecutor):
    """Simulates Raspberry Pi pin interaction failures.

    The buzzer malfunctions (buzzer_working=0) when all LED voltages
    fall within the hidden failure hyperrectangle. Otherwise it works
    normally (buzzer_working=1).

    This simulator can be replaced by a real hardware executor that
    communicates with a Raspberry Pi without changing the planner.
    """

    def __init__(self, scenario: str | PinScenario = "R1", seed: int = 42):
        if isinstance(scenario, PinScenario):
            self.scenario = scenario
            self.scenario_name = scenario.name
        else:
            if scenario not in RASPI_SCENARIOS:
                raise ValueError(
                    f"Unknown scenario: {scenario}. "
                    f"Available: {list(RASPI_SCENARIOS.keys())}"
                )
            self.scenario = RASPI_SCENARIOS[scenario]
            self.scenario_name = scenario
        self.seed = seed
        self.rng = random.Random(seed)

    def get_name(self) -> str:
        return f"RaspiPinSimulator({self.scenario_name}, seed={self.seed})"

    def execute(self, config: ExperimentConfig) -> ExecutionResult:
        """Execute a simulated pin interaction test.

        Returns binary result: buzzer_working = 1 (pass) or 0 (fail).
        """
        params = config.parameters
        in_failure = _in_failure_region(params, self.scenario)
        buzzer_working = 0 if in_failure else 1

        return ExecutionResult(
            experiment_id=config.experiment_id,
            status=ExecutionStatus.COMPLETED,
            results={
                "led1_voltage": float(params.get("led1_voltage", 0.0)),
                "led2_voltage": float(params.get("led2_voltage", 0.0)),
                "led3_voltage": float(params.get("led3_voltage", 0.0)),
                "buzzer_working": buzzer_working,
            },
        )

