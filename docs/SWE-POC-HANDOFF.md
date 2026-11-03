# ChipCheck / ActiveQual — SWE Handoff: Software-First POC, Plug-and-Play Algorithms, and Hardware Integration

**Status:** Engineering Handoff & Pre-Implementation Guide  
**Target Audience:** Software Engineering (SWE) Lead / Teammate & Coding Agents  
**Goal:** Build a complete **Software-First Proof of Concept (POC)** with a simulated hardware bench so we can rapidly evaluate multiple test-selection algorithms and validate the end-to-end control loop before physical hardware integration.

---

## 1. Executive Summary & Why This Document Exists

We want to build and validate the entire **ChipCheck (ActiveQual)** software pipeline immediately—without waiting on physical breadboards, RP2040 wiring, or ESP32 firmware. To do that, we need a **pure-software POC** where a deterministic/stochastic **Hardware Bench Simulator** stands in for the physical instruments and Device Under Test (DUT).

However, **an AI coding agent cannot be turned loose on the repository today without human architectural sign-off first.** Right now, the repository contains conflicting architectural directions across documents and code, plus several unauthored specs (HLDs 05–10).

This handoff document covers:
1. **Current Repo State:** What is already built vs. what is missing.
2. **Decisions the SWE Teammate Must Make First:** Concrete calls and spec docs you must write/update before instructing an agent to write the code.
3. **Known Bugs & Algorithmic Pitfalls in Current Code:** Specific issues in `activequal/decision/service/decision.py` and the seeded fault design that must be fixed.
4. **Plug-and-Play Algorithm Architecture:** How to structure the Decision/Planner interface so we can swap algorithms (Random, Grid, Multivariate TPE, GP Bayesian Optimization, Staged Coverage + Minimization) with zero changes to the orchestrator.
5. **Zero-Friction Hardware Integration Boundary:** How to structure the Controller/Adapter layer so the Hardware Team can swap out the Software Simulator for real RP2040 + ESP32 serial hardware later by changing a single adapter class.

---

## 2. Current Repository Inventory (What Exists Today)

### 2.1 Documentation (`docs/`)
| File | Status | Summary |
|---|---|---|
| `docs/adaptive-hardware-fuzzing-prd.md` | Complete | Full Product Requirements Document (PRD). |
| `docs/00-activequal-hld-document-map.md` | Approved | Index of HLDs 00–10 and ownership rules. |
| `docs/01-activequal-system-context-and-platform-boundaries.md` | Approved | Defines service boundaries (Console, BFF, Backend, Agent, Decision, Controller, Adapter). **Note:** Claims Kotlin/JVM + JPA + Liquibase stack. |
| `docs/02-activequal-hardware-architecture.md` | Approved | Physical bench setup, 3 programmable rails, RP2040 test controller, ESP32 DUT, safety interlocks. |
| `docs/03-activequal-episode-execution-and-safety-state-machine.md` | Initial Draft | Campaign lifecycle (`DRAFT` → `ARMED` → `RUNNING` → `COMPLETED`/`LOCKED_OUT`) and episode states/outcomes (`PASS`, `DUT_FAILURE`, `INVALID_EXPERIMENT`, `SAFETY_ABORT`). |
| `docs/04-activequal-test-contract-and-domain-model.md` | Initial Draft | Conceptual domain model for contracts, controls, observations, requirements, and outcomes. |
| `docs/05` through `docs/10` | **Missing (`Planned`)** | APIs/Protocols (05), Adaptive Search Math (06), Security/Deployment (07), Persistence (08), Console UX (09), Verification Plan (10) are not written yet. |
| `docs/SIMPLIFIED-PLAN.md` & `docs/SOLUTIONS.md` | Proposal | Alternative lightweight proposal (~300-line Python orchestrator + FastAPI + SQLite + Optuna + text serial protocol). |
| `Documnentation on Algorithm/ChipCheck_Algorithm_and_ML_Methodology.docx` | Reference | 1-page methodology summary describing the 6-step loop and Optuna TPE. |

### 2.2 Implemented Code (`activequal/`)
1. **Console UI (`activequal/console/ui/`):**
   - Next.js (React 19 + TypeScript) 5-step Setup Wizard (`src/components/setup-wizard.tsx`).
   - Collects setup metadata, primary rail (`railMin`, `railMax`, `railStep`), optional second rail (`sensorRail`), LED options (`on`/`off`), workloads, safety bounds, and budget.
   - Calls `/api/proposals` (`src/app/api/proposals/route.ts`) to preview candidate tests.
   - *Limitation:* Only previews 3 static proposals; cannot arm a campaign, stream live episodes, display scatter/timeline plots, or show a counterexample report.
2. **Console BFF (`activequal/console/bff/`):**
   - Node.js + TypeScript gRPC service (`service/src/server.ts`) implementing `PreviewProposedTests` from `api/proto/chipcheck/console/v1/console.proto`.
   - Forwards requests over HTTP POST to `http://127.0.0.1:8001/v1/proposals` (Decision Service).
3. **Decision Service (`activequal/decision/service/`):**
   - Python HTTP server (`decision.py`) + unit tests (`tests/test_decision.py`).
   - Uses Optuna (`TPESampler`, `RandomSampler`, `GridSampler`) to propose candidate test conditions given a setup and past history.
4. **Missing Services (0% Implemented in Code):**
   - **Backend Service** (contract storage, campaign/episode persistence, safety kernel approval).
   - **Agent Service** (campaign loop coordinator, budget tracker, confirmation & minimization scheduler).
   - **Oracle / Scorer** (deterministic evaluation of telemetry against requirements + normalized robustness calculation).
   - **Controller & Adapter Service** (episode execution state machine + Simulated Bench Adapter / Serial Hardware Adapter).

---

## 3. Critical Decisions the Human SWE Must Lock Down First

Before prompting an AI agent to build the rest of the POC, you **must resolve the following 5 ambiguities** by writing a short specification (e.g., `docs/SOFTWARE-POC-SPEC.md`) and updating `AGENTS.md`.

### Decision 1: Resolve the Tech Stack Contradiction
Right now:
- **HLD 01** says: *"backend, agent, decision, controller, and adapter services use Kotlin/JVM; persistence uses JPA and Liquibase."*
- **SIMPLIFIED-PLAN.md** says: *"Python + FastAPI + SQLite."*
- **Actual repo code** is: *Next.js UI + TypeScript gRPC BFF + Python HTTP Decision Service.*

**What you need to decide and document:**
- **Option A (Recommended for fast POC & ML iteration):** Keep Next.js UI + TypeScript BFF, and build the **Backend, Agent, Safety Kernel, Oracle, Controller, and Hardware Simulator in Python** (either as well-isolated modules/services with SQLite persistence or gRPC/HTTP endpoints matching the HLD boundaries). Update `AGENTS.md` and HLD 01 to explicitly state that Python is the blessed implementation language for the POC backend/bench services.
- **Option B (Strict HLD 01 compliance):** Build Backend, Agent, Controller, and Adapter in Kotlin/JVM with gRPC/Protobuf, JPA, and Liquibase, keeping Python strictly for the Decision Service. (If choosing this, document the exact Gradle/Maven multi-module layout and Postgres/H2 config for the agent).

### Decision 2: Replace Free-Text Rules with a Structured Contract Schema
In `console.proto` and `setup-wizard.tsx` today, three critical fields are plain free-text strings:
- `observations` (e.g., `"OLED frame latency, heartbeat gap, reset count"`)
- `requirement` (e.g., `"frame_latency_ms <= 120"`)
- `forbidden_combinations` (e.g., `"red_led == on and workload == flash_write"`)

In fact, `decision.py` currently throws an error if `forbiddenCombinations` is non-empty (`"free-text forbidden combinations cannot be enforced by Decision; use a reviewed structured contract"`).

**What you need to define:**
Write down the exact JSON/Protobuf/YAML schema for:
1. **Structured Requirements:**
   ```json
   {
     "maxOledLatencyMs": 120.0,
     "maxHeartbeatGapMs": 500.0,
     "maxResetCount": 0
   }
   ```
2. **Structured Forbidden Combinations:** Predicate list or key-value exclusion rules (e.g., `[{"redLed": "on", "workload": "flash_write"}]`) that both the Safety Kernel and Decision Service can evaluate deterministically.
3. **Structured Telemetry / Observations:** Exact numeric fields returned by an episode (`measuredRailVolts`, `measuredSensorRailVolts`, `measuredCurrentMa`, `oledLatencyMs`, `maxHeartbeatGapMs`, `resetCount`, `bootReason`, `dataQuality`).

### Decision 3: Lock the Normalized Robustness Math (Oracle Spec)
In `SIMPLIFIED-PLAN.md`, the draft scorer computes raw unnormalized differences (`120 - max_lat`, `500 - max_gap`, `-1000 * resets`) and takes `min(scores)`.
- **Why that breaks ML:** Raw milliseconds (`500`) and millivolts (`30`) have completely different scales. Whichever requirement has the largest numerical unit dominates `min()`, and workloads that don't exercise the OLED appear artificially "safer."

**What you need to specify:**
Define the normalized robustness formula in your spec so every requirement margin is dimensionless in $[-1, +1]$:
$$m_{\text{latency}} = \frac{L_{\max} - L_{\text{measured}}}{L_{\max}}, \quad m_{\text{heartbeat}} = \frac{G_{\max} - G_{\text{measured}}}{G_{\max}}$$
$$m_{\text{reset}} = \begin{cases} +1.0 & \text{if } \text{resets} = 0 \\ -1.0 \times \text{resets} & \text{if } \text{resets} > 0 \end{cases}$$
$$\text{robustness} = \min\left(m_{\text{latency}},\, m_{\text{heartbeat}},\, m_{\text{reset}}\right)$$
- $\text{robustness} \ge 0 \implies \text{PASS}$
- $\text{robustness} < 0 \implies \text{DUT\_FAILURE}$
- Also pass the individual margin dictionary `{"latency": m_lat, "heartbeat": m_hb, "reset": m_rst}` in the episode record so multi-output or GP planners can model each requirement separately.

### Decision 4: Specify the Software Simulator & Seeded Fault Benchmarks
To test whether our adaptive algorithms actually beat Random and Grid, the Software Simulator needs well-defined synthetic physics and fault modes.

**Crucial finding on Fault A (`SIMPLIFIED-PLAN.md`):**
In `SIMPLIFIED-PLAN.md`, Fault A only adds latency when *all* conditions match simultaneously (`oled_rail_v` $\in [3.20, 3.30]$, `red_led == on`, `green_led == off`, `workload == oled_refresh`). Everywhere else, latency is a flat ~31 ms.
- At $0.01\text{ V}$ steps ($81$ voltage steps $\times 4$ LED states $\times 5$ workloads $= 1620$ states), the fault island is only $11 / 1620 \approx 0.68\%$ of the space.
- Because the response surface is **completely flat** outside that $0.68\%$ island, *no optimizer has a gradient to follow* until it stumbles onto the island by pure luck (~29% chance in 50 random trials).

**What you need to specify for the Simulator (`SimulatedBenchAdapter`):**
Define 4 selectable benchmark profiles (selectable via CLI and UI):
1. **`B1_GRADIENT_FAULT` (Smooth/Degrading Interaction Fault):**
   - Models realistic hardware margin degradation: when `workload == oled_refresh`, as `oled_rail_v` approaches the sensitive window ($3.25\text{ V}$), I²C/charge-pump timing degrades smoothly, and turning `red_led == on` or `green_led == off` amplifies the voltage droop / task contention.
   - This gives a true continuous gradient across voltage and partial discrete states, while only crossing the failure threshold ($>120\text{ ms}$) inside the target combination ($3.22\text{–}3.28\text{ V}$ + `red=on` + `green=off` + `oled_refresh`).
2. **`B2_CLIFF_FAULT` (Binary Island / Hard Reset Fault):**
   - Instant watchdog/brownout reset (`resetCount = 1`) only inside `oled_rail_v` $\in [3.15, 3.18]\text{ V}$, `sensor_rail_v` $\ge 3.40\text{ V}$, `workload == sensor_read`. Zero pre-failure warning outside the island. Serves as an honest stress test / negative result baseline.
3. **`B3_CLEAN_NO_FAULT` (Honest Negative Benchmark):**
   - Nominal behavior + Gaussian measurement noise ($\sigma_V = 2\text{ mV}$, $\sigma_{\text{lat}} = 2.5\text{ ms}$). Verifies the system reports `"No counterexample found within budget"` with zero false positives.
4. **`B4_INSTRUMENT_GLITCH` (Safety & Invalid Experiment Test):**
   - Deterministically injects an overcurrent trip (`SAFETY_ABORT` → `LOCKED_OUT`) or dropped UART telemetry (`INVALID_EXPERIMENT`) on specific trigger conditions to test state machine recovery.

### Decision 5: Define the Campaign Stage & Minimization Policy
Specify how the **Agent Service** allocates a campaign budget (e.g., $B = 30$ or $50$ episodes):
1. **Phase 1 — Initial Space-Filling / Pairwise Coverage ($N_{\text{init}} \approx 8\text{–}10$ episodes):** Cover nominal point, voltage corners, pairwise discrete combinations, and Sobol/LHS voltages.
2. **Phase 2 — Adaptive Hunting:** Query the active Decision Planner (`tpe`, `gp_bo`, `random`, `grid`) until a `DUT_FAILURE` is observed or budget is exhausted.
3. **Phase 3 — Confirmation & Minimization (Triggered on first `DUT_FAILURE`):**
   - **Confirm:** Immediately replay the failing candidate $K=2$ times. If it does not reproduce, log as transient/flaky and resume Phase 2.
   - **Minimize Discrete Conditions:** One by one, flip each active discrete setting back to its nominal default (`red_led -> off`, `green_led -> off`, `sensor_rail -> nominal`) and run an episode to check if the failure still occurs.
   - **Bracket Voltage Boundary:** Probe $\pm 0.02\text{ V}$ / $\pm 0.05\text{ V}$ around the failing voltage to report the failure interval $[V_{\text{low}}, V_{\text{high}}]$.

---

## 4. Bugs in Current `decision.py` That Must Be Fixed

When your SWE teammate or agent updates `activequal/decision/service/decision.py`, make sure they fix these specific issues discovered during code review:

1. **Univariate TPE ignores parameter interactions:**
   - Currently: `optuna.samplers.TPESampler(seed=seed, n_startup_trials=warmup)`
   - Fix: Pass `multivariate=True, group=True, constant_liar=True` so TPE models joint voltage + LED + workload interactions and diversifies batch proposals.
2. **Stateless `RandomSampler(seed=seed)` replay exhaustion bug:**
   - Because `decision.py` is stateless and recreates `RandomSampler(seed=seed)` on every HTTP call, it generates the exact same pseudorandom sequence from index 0 every time, skipping items in `seen`.
   - Worse, the loop stops at `attempts < max(50, count * 50)`. When `count=1` and `len(history) >= 50`, all 50 attempts are consumed re-drawing the first 50 historical points, and `propose()` returns **0 candidates**!
   - Fix: Advance the RNG seed by `seed + len(history)` or pass replayed trials into the study before drawing, and scale `max_attempts` with `len(seen) + max(50, count * 50)`.
3. **`INVALID_EXPERIMENT` and `SAFETY_ABORT` are not added to `seen`:**
   - Lines 139–140 skip `INVALID_EXPERIMENT` and `SAFETY_ABORT` before `seen.add(_key(params))`. As a result, a deterministic planner can propose the exact same invalid or unsafe point on every subsequent turn, burning the entire campaign budget.
   - Fix: Always add `INVALID_EXPERIMENT` and `SAFETY_ABORT` conditions to `seen` so they are never re-proposed, while still excluding them from `study.add_trial()` (or marking them as pruned/failed trials).

---

## 5. Designing the Plug-and-Play Algorithm Architecture

We want to compare multiple algorithms side-by-side without touching the Agent, Backend, Controller, or UI.

### 5.1 Standard Planner Plugin Interface
Refactor `activequal/decision/service/` so every algorithm implements a single clean Python protocol / abstract base class:

```python
from typing import Protocol, Any

class PlannerPlugin(Protocol):
    name: str

    def propose(
        self,
        domain: SearchDomain,
        history: list[EpisodeRecord],
        count: int,
        seed: int,
        config: dict[str, Any],
    ) -> list[CandidateProposal]:
        """
        Pure function / stateless interface:
        Given the legal contract domain and all prior episode records
        (including PASS, DUT_FAILURE, INVALID_EXPERIMENT, SAFETY_ABORT),
        return up to `count` unvisited candidate proposals with human-readable reasons.
        """
        ...
```

### 5.2 Recommended Directory Layout for `activequal/decision/service/`
```text
activequal/decision/service/
├── decision.py                  # HTTP/gRPC server + request validation + plugin router
├── domain.py                    # SearchDomain, EpisodeRecord, CandidateProposal dataclasses
├── planners/
│   ├── __init__.py              # PLANNER_REGISTRY = {"random": ..., "grid": ..., "tpe": ..., ...}
│   ├── base.py                  # PlannerPlugin protocol + common deduplication helpers
│   ├── random_planner.py        # Uniform random baseline (with proper seed progression)
│   ├── grid_planner.py          # Deterministic grid baseline
│   ├── coverage_planner.py      # Sobol / Latin Hypercube + Pairwise discrete covering array
│   ├── tpe_planner.py           # Optuna Multivariate + Group TPE
│   ├── gp_bo_planner.py         # Gaussian Process Bayesian Optimization (Optuna GPSampler / scikit-learn GP)
│   └── staged_hybrid_planner.py # Stage 1: Coverage -> Stage 2: GP/TPE -> Stage 3: Boundary/Minimization
└── tests/
    ├── test_decision.py
    └── test_planners_benchmark.py # Fast 50-seed comparison across B1, B2, B3
```

### 5.3 Why This Makes Experimentation Effortless
- To test a brand-new algorithm (e.g., Random Forest surrogate, Upper Confidence Bound, or Active Level-Set Estimation for boundary mapping where $\text{acquisition}(x) = \beta \sigma(x) - |\mu(x)|$), an engineer just drops a 60-line file into `planners/` and registers its key in `PLANNER_REGISTRY`.
- Both the **Web Console** (`method` dropdown) and the **Headless Benchmark CLI** can select any registered planner by name.

---

## 6. Designing the Hardware Integration Boundary (Simulator Now, Hardware Later)

The Hardware Team is building:
1. **RP2040 Instrument Controller** over USB Serial (`115200` baud) speaking the line-oriented ASCII protocol in `docs/SIMPLIFIED-PLAN.md` (`SET OLED <V>`, `SET SENSOR <V>`, `READ ALL`, `ENABLE/DISABLE`, `SHUTDOWN`, `PING`).
2. **ESP32-S3 DUT** over USB Serial (`115200` baud) accepting workload/LED commands (`LED RED ON`, `WORKLOAD OLED_REFRESH`, `RESET`) and streaming telemetry every 200 ms (`HB <ms>`, `OLED_LAT <ms>`, `BOOT_REASON <reason>`).

### 6.1 The `BenchAdapter` Abstraction
Everything above the Adapter Service (Console, BFF, Backend, Agent, Decision, Safety Kernel, Oracle, Controller State Machine) must **never know whether it is talking to the Software Simulator or physical USB serial ports.**

Define one narrow hardware boundary interface in the Controller/Adapter layer:

```python
from typing import Protocol

class BenchAdapter(Protocol):
    def health_check(self) -> BenchHealth:
        """Verify RP2040 watchdog, E-stop status, and DUT connection."""
        ...

    def apply_and_measure(self, episode: ApprovedEpisode) -> RawBenchCapture:
        """
        1. Verify safe starting state (0V / idle)
        2. Set programmable rail voltages & read back actual voltages/currents
        3. Set discrete states (red LED, green LED)
        4. Trigger workload and collect telemetry over episode duration
        5. Execute safe shutdown sequence (return rails/workloads to safe state)
        6. Return RawBenchCapture (measured voltages, currents, heartbeat timestamps,
           OLED latencies, reset events, and any hardware alerts)
        """
        ...

    def emergency_shutdown(self) -> None:
        """Immediate `SHUTDOWN` command to RP2040 + de-energize all rails."""
        ...
```

### 6.2 Three Implementations of `BenchAdapter`
1. **`InMemorySimulatedAdapter` (For fast POC & 100-seed ML benchmarks):**
   - Runs in $<1\text{ ms}$ per episode (no `sleep()` delays).
   - Implements the synthetic physics models (`B1_GRADIENT_FAULT`, `B2_CLIFF_FAULT`, `B3_CLEAN_NO_FAULT`, `B4_INSTRUMENT_GLITCH`).
2. **`LoopbackSerialMockAdapter` (For testing the serial driver before hardware arrives):**
   - Uses Python `pty` / `pyserial` `loop://` virtual serial ports to speak the exact ASCII text protocol (`SET OLED 3.24\n` → `OK OLED 3.238\n`, `HB 200\n`, `OLED_LAT 248\n`).
   - Proves out serial parsing, timeouts, malformed line handling, and watchdog keepalives in software.
3. **`PhysicalSerialBenchAdapter` (For the Hardware Team handoff):**
   - Opens `/dev/ttyACM0` (RP2040) and `/dev/ttyUSB0` (ESP32) via `pyserial`.
   - Activated via a single environment variable: `CHIPCHECK_BENCH_MODE=serial` (vs `CHIPCHECK_BENCH_MODE=sim`).

---

## 7. Step-by-Step Checklist for the SWE Teammate

Before handing implementation over to a coding agent, complete these steps:

- [ ] **Step 1: Decide the Backend Language (Python vs. Kotlin)**
  - If Python (recommended), update `AGENTS.md` and add a note at the top of `docs/01-activequal-system-context-and-platform-boundaries.md` clarifying that the 12-week POC implements Backend/Agent/Controller/Adapter in Python alongside the existing Next.js UI and TypeScript BFF.
- [ ] **Step 2: Author `docs/SOFTWARE-POC-SPEC.md` (or HLDs 05 & 06)**
  - Lock down the JSON/Proto schemas for structured requirements, forbidden combinations, normalized robustness scoring, and the 4 simulator benchmark profiles (`B1`–`B4`).
- [ ] **Step 3: Prompt the Coding Agent in 4 Clean Milestones**
  - **Milestone 1 (Decision & Planner Plugins + Simulator):** Fix the 3 bugs in `decision.py`, extract the `PlannerPlugin` interface, add `tpe_multivariate`, `coverage`, and `gp_bo` planners, and build `InMemorySimulatedAdapter` + a fast CLI benchmark script (`run_benchmarks.py`) that proves adaptive planners beat Random/Grid on `B1`.
  - **Milestone 2 (Safety Kernel, Oracle, Agent Loop & Persistence):** Implement the deterministic Safety Kernel, normalized Oracle scorer, Agent campaign loop (Discovery → Replay Confirmation → Counterexample Minimization), and SQLite campaign store.
  - **Milestone 3 (Serial Protocol Driver & Loopback Tests):** Implement `PhysicalSerialBenchAdapter` and `LoopbackSerialMockAdapter` matching the ASCII serial protocol in `SIMPLIFIED-PLAN.md` so the Hardware Team has a ready-to-run CLI test harness (`test_hardware_bench.py`) for their breadboard.
  - **Milestone 4 (Live Console UI Integration):** Extend the Next.js UI and TypeScript BFF to start a simulated or physical campaign, stream episode results live, plot Voltage vs. Robustness, and display the final Minimized Counterexample Report.
