"""Experiment executor interface and ESP32 timing simulator for ChipCheck.

The executor interface is generic. The ESP32TimingSimulator is the first
concrete implementation for simulated experiments.
"""

from __future__ import annotations

import abc
from chipcheck.models import ExperimentConfig, ExecutionResult


class ExperimentExecutor(abc.ABC):
    """Abstract experiment executor interface.

    A future ESP32 serial executor can implement this interface to replace
    the simulator without modifying the adaptive planner.
    """

    @abc.abstractmethod
    def execute(self, config: ExperimentConfig) -> ExecutionResult:
        """Execute an experiment and return a structured result.

        Args:
            config: Experiment configuration with parameters.

        Returns:
            Structured execution result with measurements.
        """
        ...

    @abc.abstractmethod
    def get_name(self) -> str:
        """Return the name of this executor."""
        ...

