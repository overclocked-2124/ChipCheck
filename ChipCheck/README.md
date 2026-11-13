# ChipCheck — Generic Adaptive Experiment Selection and Timing-Test Engine

ChipCheck is a research-grade, adaptive experiment-selection engine designed to discover failure-inducing operating conditions and characterize safety boundaries in embedded systems under tight experimental budgets.

The initial concrete experiment domain focuses on **ESP32 sensor timing tests**, evaluating sampling intervals, sensor-reading execution times, timing jitter, and deadline compliance.

---

## Table of Contents

1. [Research Objective](#1-research-objective)
2. [Architecture and Separation of Responsibilities](#2-architecture-and-separation-of-responsibilities)
3. [Adaptive Testing vs. Random Baseline](#3-adaptive-testing-vs-random-baseline)
   - [Tree-structured Parzen Estimator (TPE)](#tree-structured-parzen-estimator-tpe)
   - [Random Baseline](#random-baseline)
   - [Clarification on Uncertainty and Acquisition](#clarification-on-uncertainty-and-acquisition)
4. [Declarative Experiment Contracts](#4-declarative-experiment-contracts)
5. [PC-to-ESP32 Protocols & Data Models](#5-pc-to-esp32-protocols--data-models)
   - [Input Protocol (PC -> ESP32)](#input-protocol-pc---esp32)
   - [Output Protocol (ESP32 -> PC)](#output-protocol-esp32---pc)
   - [Early Termination Semantics](#early-termination-semantics)
6. [Critical Timing Semantics](#6-critical-timing-semantics)
   - [A. Sampling Interval vs. B. Sensor-Reading Execution Time](#a-sampling-interval-vs-b-sensor-reading-execution-time)
   - [Formulas: Average Interval and Jitter](#formulas-average-interval-and-jitter)
   - [Deadline Miss Definition](#deadline-miss-definition)
7. [Measurement Oracle & Robustness Calculation](#7-measurement-oracle--robustness-calculation)
   - [Oracle Verdicts](#oracle-verdicts)
   - [Signed Robustness Metric](#signed-robustness-metric)
8. [ESP32 Timing Simulator & Synthetic Benchmarks](#8-esp32-timing-simulator--synthetic-benchmarks)
   - [B1: Gradual Threshold Failure](#b1-gradual-threshold-failure)
   - [B2: Narrow Failure Region](#b2-narrow-failure-region)
   - [B3: Conditional Interaction Failure](#b3-conditional-interaction-failure)
   - [B4: No-Fault Benchmark](#b4-no-fault-benchmark)
9. [Failure Confirmation & Boundary Mapping](#9-failure-confirmation--boundary-mapping)
10. [Independent Safety Validator](#10-independent-safety-validator)
11. [Storage Architecture](#11-storage-architecture)
12. [Command-Line Interface (CLI)](#12-command-line-interface-cli)
13. [Running Tests](#13-running-tests)
14. [Adding New Experiment Domains](#14-adding-new-experiment-domains)
15. [Replacing Simulator with Real Hardware (USB Serial)](#15-replacing-simulator-with-real-hardware-usb-serial)
16. [Current Limitations](#16-current-limitations)

---

## 1. Research Objective

In embedded hardware-software systems, exhaustive parameter sweeps are prohibited by physical wear, test duration, and thermal stabilization constraints. Traditional random or grid testing often fails to find narrow bug windows or complex multi-variable faults.

ChipCheck investigates:
> *"Can an adaptive, uncertainty-aware testing framework discover failure-inducing operating conditions and hardware-software interaction faults more efficiently than conventional testing approaches under the same experimental budget?"*

The engine focuses on two primary phases:
1. **Failure Discovery**: Rapidly navigating mixed continuous/discrete parameter spaces to discover experiment configurations that violate timing or functional requirements.
2. **Boundary Mapping**: Refining passing/failing contours around discovered faults to characterize the transition boundary where failure probabilities change.

---

## 2. Architecture and Separation of Responsibilities

ChipCheck enforces strict separation between its core components:

```
┌──────────────────────────────────────────────────────────────┐
│                    Campaign Orchestrator                     │
│  Coordinates Exploration -> Discovery -> Confirm -> Boundary│
└───────┬──────────────────────┬───────────────────────┬───────┘
        │                      │                       │
        ▼                      ▼                       ▼
┌──────────────┐       ┌──────────────┐        ┌──────────────┐
│ Experiment   │       │ Independent  │        │ Experiment   │
│ Planner      │       │ Safety       │        │ Executor     │
│ (TPE/Random) │       │ Validator    │        │ (Sim/Serial) │
└───────▲──────┘       └───────┬──────┘        └───────┬──────┘
        │                      │                       │
        │                      ▼                       ▼
        │              ┌──────────────┐        ┌──────────────┐
        │              │  Execution   │───────▶│ Measurement  │
        │              │  Gate        │        │ Oracle       │
        │              └──────────────┘        └───────┬──────┘
        │                                              │
        └────────────── Robustness Score ──────────────┘
```

- **Planner**: Generates trial proposals based solely on declarative contract definitions and previous valid observations. It has **no knowledge** of the simulator's internal failure equations or hidden ground truth.
- **Safety Validator**: Completely independent from the optimizer. Every candidate configuration must be validated against type bounds, step alignments, categorical choices, and cross-parameter constraints. No invalid proposal ever reaches the executor.
- **Executor Interface**: An abstract base class (`ExperimentExecutor`) that executes an `ExperimentConfig` and returns an `ExecutionResult`.
- **Simulator**: Emulates ESP32 microsecond-level hardware timer behavior, executing sensor reads, jitter, read delays, and early terminations.
- **Oracle & Robustness Calculator**: Evaluates measurements against contract requirements, distinguishing measurement quality from device functional failure.
- **Storage**: SQLite-backed persistence recording contracts, configurations, execution traces, oracle verdicts, confirmations, and boundary points.

---

## 3. Adaptive Testing vs. Random Baseline

### Tree-structured Parzen Estimator (TPE)
ChipCheck employs Optuna's **TPESampler** for adaptive experiment selection. TPE models probability densities $p(x|y)$ over candidate configurations conditioned on whether their observed robustness $y = R(x)$ falls above or below a quantile threshold $\gamma$:
- $\ell(x) = p(x | R(x) < y^*)$ (density of configurations leading to lower robustness / failure)
- $g(x) = p(x | R(x) \ge y^*)$ (density of configurations leading to passing/safe behavior)

TPE samples candidate points that maximize the ratio $\ell(x) / g(x)$, biasing exploration towards failure-inducing regions.

### Random Baseline
To evaluate whether adaptive testing provides measurable efficiency gains, ChipCheck includes an identical baseline using **RandomSampler**. Both planners share:
- The exact same contract and parameter distributions
- Identical initial nominal and random exploration seeds
- Identical evaluation budget and execution cost accounting
- Identical confirmation replay counts and boundary allocation

### Clarification on Uncertainty and Acquisition
TPE is an empirical kernel density estimator. It is **not** a Gaussian Process surrogate and does **not** explicitly compute calibrated posterior predictive variances or Bayesian acquisition functions (such as Expected Improvement with epistemic uncertainty decomposition). Small sample sizes (<15 trials) result in near-uniform initial exploration.

---

## 4. Declarative Experiment Contracts

Contracts are authored in YAML (`contracts/esp32_timing.yaml`). They declare the search space, requirements, and constraints without hardcoding anything into the optimizer:

```yaml
contract_id: "esp32_timing_v1"
version: "1.0"
name: "ESP32 Sensor Timing Test"

parameters:
  - name: sampling_interval_ms
    type: integer
    low: 1
    high: 100
    step: 1
    default: 10

  - name: duration_ms
    type: integer
    low: 100
    high: 30000
    step: 100
    default: 5000

  - name: sensor_type
    type: categorical
    choices: ["LDR", "BME280", "DHT22", "MPU6050"]
    default: "LDR"

  - name: number_of_samples
    type: integer
    low: 10
    high: 1000
    step: 10
    default: 500

  - name: deadline_ms
    type: integer
    low: 1
    high: 50
    step: 1
    default: 5

constraints:
  - expression: "duration_ms >= sampling_interval_ms * 2"
    description: "Duration must allow at least 2 samples"
  - expression: "number_of_samples >= 2"
    description: "Must request at least 2 samples"
  - expression: "deadline_ms <= sampling_interval_ms"
    description: "Deadline must not exceed sampling interval"

requirements:
  - name: deadline_compliance
    metric: max_read_execution_time_ms
    operator: "<="
    threshold: 5.0
    is_primary: true
```

---

## 5. PC-to-ESP32 Protocols & Data Models

### Input Protocol (PC -> ESP32)
Transmitted over USB Serial formatted as newline-delimited JSON (NDJSON):
```json
{
  "experiment_id": 101,
  "command": "RUN_TIMING_TEST",
  "parameters": {
    "sampling_interval_ms": 10,
    "duration_ms": 5000,
    "sensor_type": "LDR",
    "number_of_samples": 500,
    "deadline_ms": 5
  }
}
```

### Output Protocol (ESP32 -> PC)
Returned by the device as a single JSON line:
```json
{
  "experiment_id": 101,
  "status": "COMPLETED",
  "results": {
    "requested_interval_ms": 10.0,
    "actual_average_interval_ms": 10.3,
    "min_interval_ms": 9.8,
    "max_interval_ms": 11.2,
    "average_jitter_ms": 0.4,
    "total_samples": 450,
    "missed_deadlines": 1,
    "failed_reads": 2,
    "execution_time_ms": 5000.0,
    "average_read_execution_time_ms": 1.5,
    "max_read_execution_time_ms": 5.8
  }
}
```

### Early Termination Semantics
Both `number_of_samples` and `duration_ms` act as upper bounds. The experiment halts immediately when **either** limit is reached:
```
while successful_samples < number_of_samples AND elapsed_time_ms < duration_ms:
    perform_sensor_reading()
```

---

## 6. Critical Timing Semantics

### A. Sampling Interval vs. B. Sensor-Reading Execution Time
A critical embedded systems distinction is enforced:
- **Sampling Interval ($T_i$)**: The elapsed time between consecutive sample start timestamps:
  $$T_i = t_i - t_{i-1}$$
- **Sensor-Reading Execution Time ($S_i$)**: The duration taken by the ADC/I2C/SPI hardware peripheral to complete a single read operation:
  $$S_i = t_{\text{read\_end}, i} - t_{\text{read\_start}, i}$$

> **Important**: A deadline miss is defined strictly as:
> $$S_i > T_{\text{deadline}}$$
> **DO NOT** confuse $T_i > T_{\text{deadline}}$ as a deadline miss! A device can execute with a completely normal 10ms sampling interval and low jitter, yet fail its 5ms deadline if an individual sensor read stalled for 8ms.

### Formulas: Average Interval and Jitter
For $N \ge 2$ successful sample timestamps:
- **Average Sampling Interval**:
  $$\bar{T} = \frac{1}{N - 1} \sum_{i=2}^N T_i$$
- **Average Jitter**:
  $$J = \frac{1}{N - 1} \sum_{i=2}^N |T_i - \bar{T}|$$

If $N < 2$, average interval and jitter are returned as `null` (never causing division by zero).

---

## 7. Measurement Oracle & Robustness Calculation

### Oracle Verdicts
The oracle evaluates results into 5 mutually exclusive outcomes:
- `PASS`: All functional requirements met with valid statistical evidence.
- `DUT_FAILURE`: Device Under Test violated one or more functional requirements.
- `INVALID_EXPERIMENT`: Insufficient measurement samples ($N < 5$) or corrupted telemetry.
- `INCONCLUSIVE`: Execution failed without providing sufficient evidence.
- `SAFETY_ABORT`: Execution was terminated by safety limits.

### Signed Robustness Metric
Robustness $R(x)$ indicates the operating margin:
- $R(x) > 0$: Passing configuration with positive margin.
- $R(x) = 0$: Operating precisely at the requirement boundary.
- $R(x) < 0$: Requirement violation (failure).

For individual sensor-reading deadlines:
$$R_{\text{deadline}} = \frac{T_{\text{deadline}} - \max_i(S_i)}{T_{\text{deadline}}}$$

Overall robustness across multiple requirements is the minimum normalized margin:
$$R(x) = \min_k \left( \text{margin}_k \right)$$

---

## 8. ESP32 Timing Simulator & Synthetic Benchmarks

ChipCheck includes 4 synthetic benchmarks with private ground truth:
1. **B1 — Gradual Threshold Failure**: High sampling rates (low intervals < 3.5ms) cause read execution times to scale inversely, violating deadlines gradually.
2. **B2 — Narrow Failure Region**: Hardware resonance or buffer lockup triggers deadline misses exclusively when `sampling_interval_ms` $\in [7, 9]$. Regions on either side pass cleanly.
3. **B3 — Conditional Interaction Failure**: Fault occurs only when multiple conditions intersect simultaneously (`interval <= 10` AND `sensor == "BME280"` AND `number_of_samples >= 400`).
4. **B4 — No-Fault Benchmark**: Clean operating behavior where no legal configuration fails. Verifies that ChipCheck correctly reports zero failures within budget without false alarms.

---

## 9. Failure Confirmation & Boundary Mapping

### Failure Confirmation
When a `DUT_FAILURE` is identified:
1. The exact configuration parameters are frozen.
2. Replayed $k$ times (default: 5 replays) against the DUT.
3. Calculates the reproduction rate:
   $$\text{Rate} = \frac{\text{Reproduced Failures}}{k}$$
   Distinguishes deterministic bugs (100%) from intermittent race conditions.
4. All confirmation replays count against the campaign budget.

### Boundary Mapping
Triggered after a confirmed failure:
- Initializes a dedicated secondary Optuna study minimizing $|R(x)|$.
- Seeds the study using discovered passing and failing points.
- Narrows the gap between the nearest passing and nearest failing configurations, characterizing the boundary transition interval.

---

## 10. Independent Safety Validator

Operates as a strict barrier between the planner and executor. Validates:
- Parameter types (integer, float, categorical, boolean)
- Upper and lower numerical bounds
- Integer step alignments
- Categorical membership
- Cross-parameter expressions (e.g. `duration_ms >= sampling_interval_ms * 2`)
- Safety bounds

Any rejected proposal is logged in SQLite (`rejected_proposals`) and reported back to the optimizer as `PRUNED`, preventing invalid hardware stress.

---

## 11. Storage Architecture

An embedded SQLite database (`output/chipcheck_results.db`) stores:
- `campaigns`: Campaign ID, contract, planner, benchmark, budget, seed, status.
- `experiments`: Trial indices, parameters, JSON payloads, execution status, oracle outcomes, robustness, and timing metrics.
- `confirmations`: Replay outcomes and reproduction rates.
- `boundary_results`: Boundary mapping points and $|R(x)|$ metrics.
- `rejected_proposals`: Full rejection reason logs.

---

## 12. Command-Line Interface (CLI)

### Validate Contract
```bash
python main.py validate-contract
```

### Run TPE Discovery Campaign
```bash
python main.py run --benchmark B1 --planner tpe --budget 50 --seed 42
```

### Run Random Baseline Campaign
```bash
python main.py run --benchmark B1 --planner random --budget 50 --seed 42
```

### Compare TPE vs. Random Across Seeds
```bash
python main.py compare --benchmark B1 --budget 40 --seeds 5
```

### Run Full Suite (All Benchmarks B1-B4)
```bash
python main.py run-suite --budget 40 --seeds 3
```

### Raspberry Pi Pin Interaction Demo (simulator)
Run these from the `ChipCheck` directory. The contract proposes one three-pin
voltage configuration at a time; the executor returns `buzzer_working`, then
the planner uses that result to choose the next configuration.

```bash
python main.py validate-contract --contract contracts/raspi_pins.yaml
python main.py run --contract contracts/raspi_pins.yaml --benchmark R2 --planner tpe --budget 40 --seed 42
```

`R1` is much narrower; use a larger discovery budget to give it a good chance
of finding the fault before range localization, for example:

```bash
python main.py run --contract contracts/raspi_pins.yaml --benchmark R1 --planner tpe --budget 1000 --seed 42 --single-region
```

Available simulated scenarios are `R1`–`R5`: `R1` matches the example ranges,
`R2` is a broad failure box, `R3` is narrow, `R4` has no fault, and `R5` has
two disjoint failure windows for LED 1. For a baseline, run the same command
with `--planner random`.

For Raspberry Pi runs, the CLI prints each tested voltage tuple and the
buzzer's pass/fail result immediately. Campaign databases are temporary and
removed at exit; no report or output files are created.

After discovering a failing configuration, the CLI scans adjacent 8-bit codes
on each pin while holding the other two at the failing values. It reports the
inclusive failing voltage ranges and counts these boundary probes in the total
test count. The `--budget` value controls discovery tests; localization probes
are additional. Each separate failure window must first be discovered.

Use `--single-region` when you expect one contiguous failure box. It stops
discovery at the first failure and uses binary search for the six edges, but
does not search for other disconnected windows. For seeded R1 with seed 42,
this reduced the observed run from 1,135 to 251 tests while returning the same
voltage ranges.

For a physical controller, install `pyserial` and pass its serial port:

```bash
python -m pip install pyserial
python main.py run --contract contracts/raspi_pins.yaml --benchmark R2 --planner tpe --budget 40 --hardware-port COM4
```

The controller protocol is newline-delimited JSON. ChipCheck sends one request
at a time, for example `{"experiment_id":1,"command":"RUN_PIN_TEST","parameters":{"led1_voltage":1.65,"led2_voltage":2.2,"led3_voltage":1.9}}`.
Reply with the same `experiment_id`, `status:"COMPLETED"`, and
`results:{"buzzer_working":0}` (or `1`). A missing/malformed response is
treated as an invalid execution, never as a DUT failure. The Raspberry Pi
simulator is used when `--hardware-port` is omitted.

TPE supports this binary feedback, but narrow/disconnected failure regions
have no gradient; compare against Random and consider a space-filling initial
design when those regions are the target. The localized ranges assume a stable,
axis-aligned failure box around the failing point. Each additional disjoint
failure window needs its own discovered failing point.

### Inspect Stored Campaign Reports
```bash
# List all campaigns
python main.py report

# View detailed campaign results
python main.py report --campaign-id <CAMPAIGN_ID>
```

---

## 13. Running Tests

The test suite covers 51 unit and integration test cases:
```bash
python -m unittest discover -s tests -v
```

Tests verify:
- Contract loading and schema validation
- Safety rejection of out-of-range, bad-type, and step-misaligned inputs
- Cross-parameter constraint validation
- Average interval and jitter mathematical accuracy
- Read execution time deadline violation logic ($S_i > T_{\text{deadline}}$)
- Handling of insufficient timestamps ($N < 2$)
- Dual termination conditions (duration vs. sample count)
- Robustness margin sign conventions
- Failure confirmation and replay counting
- Boundary mapping optimization
- Synthetic benchmarks B1, B2, B3, and B4
- Replay reproducibility with seeded RNG

---

## 14. Adding New Experiment Domains

To adapt ChipCheck to a new domain (e.g. power rail stress, BLE latency, flash wear):
1. **Create a Contract YAML**: Define parameters, ranges, safety limits, and functional requirements.
2. **Implement `ExperimentExecutor`**:
   ```python
   from chipcheck.executor import ExperimentExecutor

   class PowerSupplyExecutor(ExperimentExecutor):
       def execute(self, config: ExperimentConfig) -> ExecutionResult:
           # Send voltage/frequency commands to instruments
           ...
   ```
3. Run campaigns through the existing orchestrator without modifying the TPE optimizer.

---

## 15. Replacing Simulator with Real Hardware (USB Serial)

The interface `ESP32SerialExecutor` in `chipcheck/executor/serial_executor.py` is pre-designed for drop-in physical integration:
1. Connect ESP32 over USB (`COMx` or `/dev/ttyUSBx`).
2. Flash firmware matching the newline-delimited JSON specification.
3. Instantiate `ESP32SerialExecutor(port="COM3", baudrate=115200)`.
4. Communication timeouts, parity errors, and serial frame drops are handled safely as `INVALID_EXPERIMENT`, preserving test station integrity.

---

## 16. Current Limitations

1. **Simulated Experiments**: Currently executed against high-fidelity synthetic benchmark models; physical serial execution requires physical ESP32 flashing.
2. **Acquisition Function**: Uses TPE's quantile density estimation rather than a customized Bayesian Active Learning model.
3. **Delta Debugging**: Failure confirmation evaluates reproduction rates; full automated parameter delta-debugging minimization can be added in a future update.

---
*ChipCheck — Built with Python 3.13 & Optuna.*
