"""ESP32 timing simulator for ChipCheck.

Implements the ExperimentExecutor interface with configurable synthetic
behavior and seeded randomness for reproducible experiments.

The simulator models:
- Requested vs actual sampling interval
- Sensor-reading execution duration (distinct from sampling interval)
- Timing jitter
- Deadline violations (based on individual read execution time, NOT interval)
- Failed sensor reads
- Experiment duration and maximum sample count
- Early termination when either upper bound is reached
- COMPLETED, FAILED, and ABORTED statuses

IMPORTANT TIMING SEMANTICS:
- Sampling interval: T_i = timestamp_i - timestamp_(i-1)
- Sensor-reading execution time: S_i = read_end_i - read_start_i
- Deadline miss: S_i > deadline_ms (NOT T_i > deadline_ms)
"""

from __future__ import annotations

import math
import random
from typing import Any, Optional, Callable

from chipcheck.models import ExperimentConfig, ExecutionResult, ExecutionStatus
from chipcheck.executor import ExperimentExecutor


class BenchmarkScenario:
    """Configurable benchmark scenario for the simulator.

    The benchmark defines how the simulator generates synthetic timing
    behavior. Ground truth failure predicates are PRIVATE to the simulator
    and evaluation layer — the planner never sees them.
    """

    def __init__(
        self,
        name: str,
        description: str,
        read_time_fn: Callable[[dict, int, random.Random], float],
        fail_read_fn: Optional[Callable[[dict, int, random.Random], bool]] = None,
        interval_noise_fn: Optional[Callable[[dict, int, random.Random], float]] = None,
        abort_fn: Optional[Callable[[dict, random.Random], bool]] = None,
    ):
        """
        Args:
            name: Benchmark identifier (e.g., "B1", "B2").
            description: Human-readable description.
            read_time_fn: (params, sample_index, rng) -> read execution time in ms.
            fail_read_fn: (params, sample_index, rng) -> True if read fails.
            interval_noise_fn: (params, sample_index, rng) -> noise added to interval in ms.
            abort_fn: (params, rng) -> True if experiment should abort.
        """
        self.name = name
        self.description = description
        self.read_time_fn = read_time_fn
        self.fail_read_fn = fail_read_fn or (lambda p, i, r: False)
        self.interval_noise_fn = interval_noise_fn or (lambda p, i, r: r.gauss(0, 0.1))
        self.abort_fn = abort_fn or (lambda p, r: False)


# ---------------------------------------------------------------------------
# Built-in benchmark scenarios (ground truth is private)
# ---------------------------------------------------------------------------

def _b1_read_time(params: dict, idx: int, rng: random.Random) -> float:
    """B1 — Gradual threshold failure.

    Sensor-reading execution time increases as sampling_interval_ms decreases.
    At very low intervals (< ~3ms), read time exceeds typical deadlines.
    """
    interval = params.get("sampling_interval_ms", 10)
    deadline = params.get("deadline_ms", 5)
    # Base read time scales inversely with interval
    base = 1.0 + (15.0 / max(interval, 1.0))
    noise = rng.gauss(0, 0.2)
    return max(0.1, base + noise)


def _b2_read_time(params: dict, idx: int, rng: random.Random) -> float:
    """B2 — Narrow failure region.

    Failure occurs only when sampling_interval_ms is in [7, 9].
    Outside that range, read times are normal.
    """
    interval = params.get("sampling_interval_ms", 10)
    base = 1.5 + rng.gauss(0, 0.15)
    # Narrow failure region: interval in [7, 9]
    if 7 <= interval <= 9:
        # Read time spikes dramatically
        spike = 6.0 + rng.gauss(0, 0.3)
        return max(0.1, spike)
    return max(0.1, base)


def _b3_read_time(params: dict, idx: int, rng: random.Random) -> float:
    """B3 — Conditional interaction failure.

    Failure requires ALL of:
    - sampling_interval_ms <= 10 (numerical)
    - sensor_type == "BME280" (categorical)
    - burst_mode == True or number_of_samples >= 400 (Boolean/scale condition)

    Each condition alone is insufficient.
    """
    interval = params.get("sampling_interval_ms", 10)
    sensor = params.get("sensor_type", "LDR")
    burst = params.get("burst_mode", False)
    n_samples = params.get("number_of_samples", 100)

    base = 1.5 + rng.gauss(0, 0.2)

    cond1 = interval <= 10
    cond2 = sensor == "BME280"
    cond3 = bool(burst) or (n_samples >= 400)

    if cond1 and cond2 and cond3:
        spike = 8.0 + rng.gauss(0, 0.5)
        return max(0.1, spike)

    return max(0.1, base)


def _b4_read_time(params: dict, idx: int, rng: random.Random) -> float:
    """B4 — No-fault benchmark.

    No legal configuration causes a functional failure.
    Read times are always well within deadline (typically ~0.2ms vs min deadline 1.0ms).
    """
    return max(0.05, 0.2 + rng.gauss(0, 0.03))


def _default_fail_read(params: dict, idx: int, rng: random.Random) -> bool:
    """Small probability of a failed read."""
    return rng.random() < 0.005


def _default_interval_noise(params: dict, idx: int, rng: random.Random) -> float:
    """Default interval noise: small Gaussian."""
    return rng.gauss(0, 0.3)


# Pre-built benchmark scenarios
BENCHMARKS = {
    "B1": BenchmarkScenario(
        name="B1",
        description="Gradual threshold failure: read time increases as sampling interval decreases",
        read_time_fn=_b1_read_time,
        fail_read_fn=_default_fail_read,
        interval_noise_fn=_default_interval_noise,
    ),
    "B2": BenchmarkScenario(
        name="B2",
        description="Narrow failure region: failure only when sampling_interval_ms in [7, 9]",
        read_time_fn=_b2_read_time,
        fail_read_fn=_default_fail_read,
        interval_noise_fn=_default_interval_noise,
    ),
    "B3": BenchmarkScenario(
        name="B3",
        description="Conditional interaction: failure requires interval<=5 AND BME280 AND samples>=400",
        read_time_fn=_b3_read_time,
        fail_read_fn=_default_fail_read,
        interval_noise_fn=_default_interval_noise,
    ),
    "B4": BenchmarkScenario(
        name="B4",
        description="No-fault benchmark: no legal configuration causes failure",
        read_time_fn=_b4_read_time,
        fail_read_fn=_default_fail_read,
        interval_noise_fn=_default_interval_noise,
    ),
}


# Ground truth predicates — PRIVATE, used only for evaluation, never by planner
def _ground_truth_b1(params: dict) -> bool:
    """B1: failure when interval < ~3.5 (read time > 5ms with typical deadline)."""
    interval = params.get("sampling_interval_ms", 10)
    deadline = params.get("deadline_ms", 5)
    expected_read = 1.0 + (15.0 / max(interval, 1.0))
    return expected_read > deadline


def _ground_truth_b2(params: dict) -> bool:
    """B2: failure when interval in [7, 9]."""
    interval = params.get("sampling_interval_ms", 10)
    deadline = params.get("deadline_ms", 5)
    return 7 <= interval <= 9  # spike ~6ms > deadline 5ms


def _ground_truth_b3(params: dict) -> bool:
    """B3: failure when interval<=5 AND BME280 AND samples>=400."""
    interval = params.get("sampling_interval_ms", 10)
    sensor = params.get("sensor_type", "LDR")
    n_samples = params.get("number_of_samples", 100)
    deadline = params.get("deadline_ms", 5)
    return interval <= 5 and sensor == "BME280" and n_samples >= 400


def _ground_truth_b4(params: dict) -> bool:
    """B4: never fails."""
    return False


GROUND_TRUTH = {
    "B1": _ground_truth_b1,
    "B2": _ground_truth_b2,
    "B3": _ground_truth_b3,
    "B4": _ground_truth_b4,
}


class ESP32TimingSimulator(ExperimentExecutor):
    """Simulates ESP32 sensor timing experiments.

    Conforms to the exact input/output contract specified for ChipCheck.
    Uses configurable benchmark scenarios and seeded randomness.
    """

    def __init__(self, benchmark: str = "B1", seed: int = 42):
        if benchmark not in BENCHMARKS:
            raise ValueError(f"Unknown benchmark: {benchmark}. Available: {list(BENCHMARKS.keys())}")
        self.benchmark = BENCHMARKS[benchmark]
        self.benchmark_name = benchmark
        self.seed = seed
        self.rng = random.Random(seed)

    def get_name(self) -> str:
        return f"ESP32TimingSimulator({self.benchmark_name}, seed={self.seed})"

    def execute(self, config: ExperimentConfig) -> ExecutionResult:
        """Execute a simulated timing experiment.

        Implements the exact termination rule:
            while successful_samples < number_of_samples
                  AND elapsed_time_ms < duration_ms:
                perform_sensor_reading()
        """
        params = config.parameters
        # Create a per-experiment RNG for reproducibility within a sequence
        exp_rng = random.Random(self.rng.randint(0, 2**32 - 1))

        # Check for abort condition
        if self.benchmark.abort_fn(params, exp_rng):
            return ExecutionResult(
                experiment_id=config.experiment_id,
                status=ExecutionStatus.ABORTED,
                results={
                    "requested_interval_ms": float(params.get("sampling_interval_ms", 10)),
                    "actual_average_interval_ms": None,
                    "min_interval_ms": None,
                    "max_interval_ms": None,
                    "average_jitter_ms": None,
                    "total_samples": 0,
                    "missed_deadlines": 0,
                    "failed_reads": 0,
                    "execution_time_ms": 0.0,
                    "average_read_execution_time_ms": None,
                    "max_read_execution_time_ms": None,
                },
            )

        sampling_interval_ms = float(params.get("sampling_interval_ms", 10))
        duration_ms = float(params.get("duration_ms", 5000))
        number_of_samples = int(params.get("number_of_samples", 500))
        deadline_ms = float(params.get("deadline_ms", 5))

        # Simulation uses microsecond-precision internally
        timestamps_us: list[float] = []  # Monotonic timestamps of successful reads
        read_exec_times_ms: list[float] = []  # Execution time of each successful read
        missed_deadlines = 0
        failed_reads = 0
        elapsed_us = 0.0
        successful_samples = 0
        sample_attempt = 0

        while (successful_samples < number_of_samples
               and elapsed_us < duration_ms * 1000.0):

            # Calculate when this reading starts
            if successful_samples == 0:
                read_start_us = elapsed_us
            else:
                # Next read starts after the requested interval from last timestamp
                interval_noise_ms = self.benchmark.interval_noise_fn(params, sample_attempt, exp_rng)
                target_interval_us = sampling_interval_ms * 1000.0
                actual_interval_us = target_interval_us + interval_noise_ms * 1000.0
                actual_interval_us = max(100.0, actual_interval_us)  # min 0.1ms
                read_start_us = timestamps_us[-1] + actual_interval_us

            # Check if we'd exceed duration
            if read_start_us >= duration_ms * 1000.0:
                break

            # Simulate the sensor read operation
            is_failed = self.benchmark.fail_read_fn(params, sample_attempt, exp_rng)
            read_exec_time_ms = self.benchmark.read_time_fn(params, sample_attempt, exp_rng)
            read_exec_time_us = read_exec_time_ms * 1000.0

            read_end_us = read_start_us + read_exec_time_us

            if is_failed:
                failed_reads += 1
                # Failed read: advance time but don't record a valid timestamp
                elapsed_us = read_end_us
            else:
                # Successful read
                timestamps_us.append(read_start_us)
                read_exec_times_ms.append(read_exec_time_ms)
                successful_samples += 1

                # Check deadline: S_i > deadline_ms (read execution time, NOT interval)
                if read_exec_time_ms > deadline_ms:
                    missed_deadlines += 1

                elapsed_us = read_end_us

            sample_attempt += 1

            # Safety: prevent infinite loops
            if sample_attempt > number_of_samples * 3:
                break

        # Calculate actual execution time
        execution_time_ms = elapsed_us / 1000.0

        # Calculate interval statistics (need at least 2 timestamps)
        if len(timestamps_us) >= 2:
            intervals_ms = [
                (timestamps_us[i] - timestamps_us[i - 1]) / 1000.0
                for i in range(1, len(timestamps_us))
            ]
            avg_interval = sum(intervals_ms) / len(intervals_ms)
            min_interval = min(intervals_ms)
            max_interval = max(intervals_ms)
            # Jitter: average absolute deviation from the average interval
            jitter = sum(abs(iv - avg_interval) for iv in intervals_ms) / len(intervals_ms)
        else:
            avg_interval = None
            min_interval = None
            max_interval = None
            jitter = None

        # Read execution time statistics
        if read_exec_times_ms:
            avg_read_exec = sum(read_exec_times_ms) / len(read_exec_times_ms)
            max_read_exec = max(read_exec_times_ms)
        else:
            avg_read_exec = None
            max_read_exec = None

        # Determine status
        if successful_samples == 0 and failed_reads > 0:
            status = ExecutionStatus.FAILED
        else:
            status = ExecutionStatus.COMPLETED

        return ExecutionResult(
            experiment_id=config.experiment_id,
            status=status,
            results={
                "requested_interval_ms": sampling_interval_ms,
                "actual_average_interval_ms": round(avg_interval, 4) if avg_interval is not None else None,
                "min_interval_ms": round(min_interval, 4) if min_interval is not None else None,
                "max_interval_ms": round(max_interval, 4) if max_interval is not None else None,
                "average_jitter_ms": round(jitter, 4) if jitter is not None else None,
                "total_samples": successful_samples,
                "missed_deadlines": missed_deadlines,
                "failed_reads": failed_reads,
                "execution_time_ms": round(execution_time_ms, 4),
                "average_read_execution_time_ms": round(avg_read_exec, 4) if avg_read_exec is not None else None,
                "max_read_execution_time_ms": round(max_read_exec, 4) if max_read_exec is not None else None,
            },
        )

