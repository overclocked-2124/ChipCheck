# ActiveQual HLD 04: Test Contract and Domain Model

**Project:** ActiveQual: AI-Driven Adaptive Physical Testing for Embedded Systems  
**Document type:** High-Level Design  
**Status:** Initial draft for team review  
**Depends on:** HLD 01, HLD 02, HLD 03

## 1. Purpose and Scope

### 1.1 Purpose

This document defines the **test contract and shared domain model** used to plan, validate, execute, and interpret ActiveQual experiments.

The test contract specifies which inputs and sequences are allowed, what evidence an experiment must collect, and how that evidence determines its outcome. These shared definitions make tests reproducible and allow results from different test-selection algorithms to be compared consistently.

The contract connects four services:

- **Decision Service** uses experiment history, the approved test domain, planner configuration, and remaining budget to select a candidate and explain its selection.
- **Agent Service** coordinates the campaign, manages its budget, schedules confirmation and minimization, and submits candidates for approval.
- **Backend Service** validates candidates against the approved contract and records approved episodes.
- **Controller Service** checks each approved episode against the connected fixture and current bench conditions before execution.

A selected candidate requires approval and bench validation before it can be executed.

### 1.2 Scope

This document defines:

- Test controls, their types, units, ranges, and tolerances.
- Legal combinations, constraints, and event sequences.
- Required observations, measurement quality, and experiment history.
- Requirements and rules for classifying experiment outcomes.
- Contract identity, versioning, approval, and hardware/firmware compatibility.
- Safety limits, shutdown conditions, budgets, and stopping rules.
- The domain inputs and outputs exchanged during candidate selection and approval.

A complete OLED example will show how these definitions work together.

This model provides the foundation for **Doc 05’s APIs and protocols** and **Doc 06’s selection algorithms and evaluation methods**. Execution state transitions remain defined in Doc 03, while storage design is covered by Doc 08.

## 2. Core Experiment and Ownership

For the initial demonstration, one campaign runs up to 30 experiments on the ESP32-S3 display-sensor setup. Each experiment applies a chosen combination of OLED voltage, LED states, and workload, then records the measurements and result.

- **Decision** chooses the next combination using previous results.
- **Agent** manages the run and its experiment budget.
- **Backend** checks the proposed combination against the test limits and records results.
- **Controller** applies the combination, collects measurements, and returns the setup to its safe state.
- **Oracle** checks whether the measured behavior meets the requirements.

We record both the requested voltage and the measured voltage. Decision receives the measurements and outcomes; the demo’s hidden fault trigger remains separate.

## 3. Test Setup and Limits

Before starting a campaign, we define the setup and the conditions that can be tested:

- **Setup:** the DUT, firmware, connected peripherals, and available controls.
- **Inputs:** which controls Decision can vary, their allowed values, and any combinations to avoid.
- **Measurements:** what we collect during each experiment.
- **Requirements:** how those measurements determine whether the test passes or fails.
- **Safety:** limits that must hold during execution and how the setup returns to a safe state.

Decision uses this definition to choose experiments. Backend checks proposed inputs against the limits, and Controller checks that the connected setup can execute them.

We record the setup used for each experiment. If hardware, firmware, or wiring changes, we update the affected controls, limits, and requirements before continuing. Earlier results remain linked to their original setup so we can judge whether they are still comparable.

The OLED demo is our first example of this definition. Other small setup changes should fit without redesigning the model.

## 4. Test Inputs and Controls

Inputs are the values and actions the bench can set for one experiment. Decision chooses among the controls available on the current setup.

| Control | Example | What we define |
|---|---|---|
| Rail voltage | OLED supply voltage | Unit, allowed range, and adjustment step |
| LED state | Red and green LEDs | Allowed states and combinations |
| Workload | OLED refresh | Available operations |
| Timing | Workload duration or delay | Unit, allowed values, and action order |

The exact values belong to the test setup. Changing a peripheral or supply may change the available controls or their limits.

One **candidate** combines these choices into an experiment—for example, a voltage setting, LED states, and a workload to run for a specified duration. Controls that Decision cannot change remain at their defined settings.

Backend checks the candidate against the test limits. Controller applies it and records what happened.

**Requested inputs and measured conditions are kept separately.** A requested voltage tells us what we tried to apply; the measured voltage tells us what the DUT actually experienced.

## 5. Legal Combinations and Sequences

An experiment must use allowed input values **and** an allowed combination of actions. The test definition records any restrictions required by the current setup.

For each experiment, we define:

- **Combinations:** which controls can be used together and which combinations must be avoided.
- **Order:** when to apply settings, start the workload, collect measurements, and restore the safe state.
- **Timing:** any required settling time, workload duration, or delay between actions.

For an OLED test, this could mean establishing the starting state, applying the selected voltage and LED settings, waiting for the required settling time, running the refresh workload, collecting results, and returning to the safe state. The actual order depends on the setup.

Backend checks the proposed combination and sequence. Controller checks the bench conditions before execution.

**An allowed experiment can still reveal a DUT failure.** These restrictions protect the setup; they must not exclude the failing conditions we are trying to discover. The demo’s hidden fault trigger remains separate from Decision’s inputs.

## 6. Observations and Experiment History

Each experiment records what we asked the bench to do, what it measured, and how the DUT responded.

| Record | Examples |
|---|---|
| Requested inputs | Voltage setting, LED states, workload, and timing |
| Measured conditions | Actual rail voltage and current, where supported |
| DUT response | Display latency, heartbeat gaps, and reset count, where available |
| Measurement quality | Missing readings, timeouts, or disconnected instruments |
| Result | The classified outcome and its supporting reason |

Controller collects the observations. Backend stores them with the requested inputs and the setup used for that experiment.

If a required reading is missing or an instrument disconnects, we record that explicitly. **Missing evidence cannot be treated as a pass.** A timeout’s meaning depends on whether the DUT failed to respond or the measurement itself failed.

Together, these records form the campaign’s **experiment history**. Agent supplies the relevant history to Decision when requesting the next candidate.

Decision receives measured results and public requirements. The demo’s hidden fault trigger remains separate. When the setup changes, each result stays linked to its original setup so we can judge whether earlier results are still comparable.

## 7. Requirements, Oracles, and Outcomes

A **requirement** states what the DUT should do under the tested conditions. For example, the display should refresh within a specified time. The test definition supplies the actual limit.

The **oracle** checks the recorded evidence against these requirements using consistent rules. It evaluates observable behavior; the demo’s hidden fault trigger stays separate.

| Outcome | Meaning |
|---|---|
| `PASS` | Required measurements are usable and the experiment met its requirements. |
| `DUT_FAILURE` | Valid evidence shows a requirement was violated—for example, a missed display update or an unexpected reset. |
| `INVALID_EXPERIMENT` | Requested conditions were not achieved, or required measurements were missing or unreliable. |
| `SAFETY_ABORT` | A safety condition stopped the experiment. |

Each outcome includes a reason and the measurements supporting it. A safety abort is recorded separately from a discovered DUT failure.

A timeout needs context: a DUT failing to respond can violate a requirement, while an instrument failing to report can make the experiment invalid.

**A pass applies only to the conditions tested.** If a campaign finds no failures, its conclusion is “no failure found within the tested conditions and budget.”

## 8. Safety Limits and Shutdown Conditions

Safety limits are defined for the selected board, peripherals, and bench. They cover the electrical and operating limits that matter to that setup, such as rail voltage, current, temperature, and episode duration where these are monitored. The Decision Service may choose inputs only within those limits.

A run must not start if a required safety measurement or protection is unavailable. Reviewed hardware limits still apply when they are not continuously monitored.

Backend checks a proposed experiment before it becomes executable. Controller checks the connected setup and instrument limits again before applying power, and monitors the available measurements during the run. Instrument protection, the test-controller watchdog, and the physical E-stop provide protection independent of the planner and host software.

At the end of a normal experiment, Controller stops the workload and returns signals and rails to the setup’s reviewed safe state in the required order. This order must account for peripherals that could be back-powered; “turn every rail off” is not a universal rule. Controller confirms the safe state and records the result.

A safety trip interrupts normal execution, causes the relevant outputs to be cut off, and places the bench in lockout for review and manual reset. This differs from the routine safe return after an ordinary experiment.

## 9. Budgets and Stopping Conditions

Each campaign has a declared limit on physical experiments and, where needed, elapsed time. The PRD’s OLED demonstration uses a 30-experiment budget; other campaigns may use a different limit suited to the run.

Agent tracks the remaining budget and stops requesting experiments when it is exhausted. The campaign record includes every physical attempt, including invalid experiments and runs used for confirmation or minimization, so these do not become uncounted retries. Proposals rejected before reaching the bench are recorded separately from executed experiments.

A campaign also stops when the researcher ends it, a safety event places the bench in lockout, required measurements repeatedly become unavailable, or no candidate fits the test limits. Any confirmation or minimization work must fit within the declared campaign budget or be started as a separately recorded run.

The stopping rule says when the system has run out of permission or useful evidence to continue. It does not mean that untested conditions passed.

## 10. Decision Service Input and Output

Agent supplies Decision with the information needed to choose the next experiment:

- the controls and sequences allowed by the current test setup;
- public DUT requirements;
- relevant previous experiments, measurements, and outcomes;
- planner settings and remaining campaign budget.

Decision returns one proposed combination of control values and workload actions, with a short reason for choosing it. This is a **candidate**, not an instruction to operate the bench. The candidate must pass Backend’s limit checks and Controller’s live setup checks before execution.

Decision sees measured evidence and public requirements. It does not receive the seeded OLED fault trigger, and it cannot approve its own candidate or command instruments. Agent handles campaign coordination and supplies new results for the next selection.

## 11. Worked OLED Example

The first worked example uses the PRD’s ESP32-S3 display-sensor setup. The reviewed definition lists an OLED supply range, red and green LED states, an OLED-refresh workload, and a display-latency requirement. The OLED rail range in the PRD example is 3.00–3.60 V; the public display requirement is a frame latency no greater than 120 ms. The board’s main supply remains at its approved nominal setting.

For one experiment, Decision selects an allowed OLED voltage, an allowed LED configuration, and the OLED-refresh workload. Backend checks the proposed combination. Controller applies it, records the requested and measured rail values, captures display latency and any available heartbeat or reset observations, then returns the bench to its safe state.

The oracle compares usable measurements with the public requirements. A measured latency over the requirement can show a DUT failure; a missing measurement or a rail that did not reach the requested condition may make the experiment invalid. The hidden seeded trigger is not given to Decision or used by the oracle. The result depends on the observed behavior in the actual run.

## 12. Ratified Contract Schema (v2)

**ActiveQual decision:** Test contracts use the structured v2 schema below. Free-text requirements, observations, and forbidden combinations are not accepted. The contract is stored as canonical JSON, and its hash is computed over that canonical form. Values shown are the OLED example, not approved limits.

```json
{
  "contractVersion": 2,
  "setup": {"dut": "esp32s3-oled-demo", "firmwareSha256": "…", "fixture": "bench-A", "fixtureRev": "A"},
  "controls": {
    "oledRailV": {"type": "continuous", "unit": "V", "min": 3.00, "max": 3.60, "step": 0.01, "nominal": 3.30,
                  "shutdown": 0.0, "slewPerSMax": 0.5, "bind": {"target": "supply.ch2", "action": "setVoltage"}},
    "redLed":    {"type": "boolean", "nominal": false, "bind": {"target": "dut", "action": "LED RED"}},
    "workload":  {"type": "categorical", "values": ["idle", "oled_refresh", "sensor_read", "flash_write"],
                  "nominal": "idle", "bind": {"target": "dut", "action": "WORKLOAD"}},
    "flashOffsetMs": {"type": "integer", "unit": "ms", "min": 0, "max": 20, "step": 1, "nominal": 0,
                      "activeWhen": {"control": "workload", "eq": "flash_write"}, "bind": {"target": "mcu", "action": "flashOffset"}},
    "dwellMs":   {"type": "duration", "unit": "ms", "min": 200, "max": 2000, "step": 100, "nominal": 500}
  },
  "forbidden": [{"all": [{"control": "workload", "eq": "flash_write"}, {"control": "sensorRailV", "gte": 3.55}]}],
  "observations": {
    "oledLatencyMs":     {"unit": "ms", "source": "firmware", "reduction": "max",
                          "requiredWhen": {"control": "workload", "eq": "oled_refresh"}, "uncertainty": 2.5},
    "maxHeartbeatGapMs": {"unit": "ms", "source": "firmware", "reduction": "max_gap", "required": true, "uncertainty": 5},
    "resetCount":        {"unit": "count", "source": "mcu", "reduction": "count", "required": true},
    "measuredOledRailV": {"unit": "V", "source": "instrument", "reduction": "mean", "required": true, "uncertainty": 0.005}
  },
  "requirements": [
    {"id": "latency",   "metric": "oledLatencyMs",     "op": "<=",    "limit": 120, "nominal": 31},
    {"id": "heartbeat", "metric": "maxHeartbeatGapMs", "op": "<=",    "limit": 500, "nominal": 200},
    {"id": "reset",     "metric": "resetCount",        "op": "exact", "limit": 0},
    {"id": "rail_band", "metric": "measuredOledRailV", "op": "band",  "lo": 3.135, "hi": 3.465, "nominal": 3.30}
  ],
  "validity": [{"metric": "measuredOledRailV", "tracks": "oledRailV", "tolerance": 0.03}],
  "scoring": {"planner": "normalized_min", "verdict": "guard_banded"},
  "safety": {"channels": {"supply.ch2": {"maxA": 0.2, "maxV": 3.6}}, "maxTempC": 60, "maxEpisodeS": 10},
  "templates": [],
  "campaign": {"budget": 30, "seed": 42, "plan": "default_v1"}
}
```

### 12.1 Field rules

| Field | Rule |
|---|---|
| Control `type` | `continuous`, `integer`, `duration`, `boolean`, or `categorical`. Numeric controls declare `min`, `max`, `step`, and a `nominal` inside the range and on the step grid. |
| `activeWhen` | A control applies only while its predicate holds. While inactive it is held at `nominal`. Dependencies must not form a cycle. |
| `bind` | Maps a control to an adapter target and action. This is the fixture-specific part; every target must exist on the registered fixture. |
| Predicates | `forbidden`, `activeWhen`, and `requiredWhen` share one form: `{"control", <op>}` with `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, or `in`. A `forbidden` rule is `{"all": [...]}`; any matching rule rejects the candidate. |
| `observations` | Each declares its `unit`, `source` (`firmware`, `mcu`, `instrument`, `optical`), `reduction`, whether it is required, and its measurement `uncertainty`. |
| `requirements` | `op` is `<=`, `>=`, `exact`, or `band`. `nominal` sets the scale for the planner margin (§13). |
| `validity` | Conditions for a trustworthy experiment. A failed validity rule gives `INVALID_EXPERIMENT`, never `DUT_FAILURE`. Rail tracking is a validity rule, not a requirement. |
| `templates` | Reserved for ordered event sequences in a later version. |

Changing any field creates a new contract version and invalidates the arm state (HLD 03 §6.2). Results stay linked to the contract version that produced them.

**Example limits:** the OLED rail range in the example may sit partly below the SSD1306's specified supply, and many breakout modules add a regulator that changes what the controller sees. Take limits from the selected parts (HLD 02 §19.1).

**Implementation status:** The Decision Service reads `controls`, `activeWhen`, and `forbidden` from this schema. Backend validation, the Oracle, and the console do not yet consume it.

## 13. Robustness and Verdict

**ActiveQual decision:** The Oracle runs in the Backend Service (HLD 01) and uses two separate calculations. Option A gives the planner a continuous signal. Option B decides the outcome.

**Option A — normalized headroom (planner signal).** Each applicable requirement gives a margin clipped to [−1, +1]:

| `op` | Margin |
|---|---|
| `<=` | `(limit − x) / (limit − nominal)` |
| `>=` | `(x − limit) / (nominal − limit)` |
| `band` | `min(x − lo, hi − x) / min(nominal − lo, hi − nominal)` |
| `exact` | `+1` if equal, otherwise `−1` |

Robustness is the minimum margin across applicable requirements, following signal temporal logic conjunction. A requirement that was not exercised, such as display latency during `idle`, is left out of the minimum. Per-requirement margins are stored with the episode so planners can model each one.

**Option B — guard-banded verdict (outcome).** With `U` the declared measurement uncertainty, a `<=` requirement passes when `x ≤ limit − U`, fails when `x > limit + U`, and is inconclusive in between; other operators apply the same rule to each bound. This follows the guard-banding decision rules used by calibration and test laboratories (ILAC-G8 / ISO/IEC 17025). An inconclusive episode may be replayed under the campaign plan; if it remains inconclusive it is recorded as `INVALID_EXPERIMENT` with an inconclusive reason.

A missing required observation always produces `INVALID_EXPERIMENT`, never a margin. Classification follows the order in HLD 03 §15.1.

**Open decision:** Who sets each requirement's `nominal` and each observation's `uncertainty`. `U` must come from calibration of the selected bench, not from this example.

## 14. Campaign Phase Plan

**ActiveQual decision:** The campaign plan is part of the contract (`campaign.plan`) so it is reviewed and versioned with the limits.

```json
"plan": {
  "discoveryBudget": 30, "verificationBudget": 16,
  "init": {"minFraction": 0.2, "maxFraction": 0.35, "design": "pairwise+sobol", "include": ["nominal", "corners"]},
  "explore": {"forcedEveryN": 5},
  "confirm": {"maxReplays": 3, "confirmIfFails": 2},
  "minimize": {"order": "discrete_then_continuous", "bracket": "expand_then_bisect"},
  "onConfirmed": "stop",
  "stop": {"consecutiveInvalid": 3, "noFeasibleCandidate": true}
}
```

1. **Coverage.** A pairwise covering array over the categorical and Boolean controls, with nominal and corner values folded into its rows and Sobol points for continuous values. Size is the larger of the array and 20% of the discovery budget, capped at 35%.
2. **Adaptive hunting.** The selected planner proposes the remaining discovery episodes. Repeated rejection of its candidates stops the campaign with a visible planner-failure reason.
3. **Verification**, started only by a guard-banded failure. Replay up to three times: two failures confirm, two initial passes mark the failure transient, a split result is decided by the third replay. Then return each non-nominal control to `nominal` one at a time, keeping changes that preserve the failure, and bracket each remaining continuous control by expanding outward until a pass and then bisecting. When the verification budget runs out, the interval is reported at its achieved resolution.

Every physical episode counts against its pool, including invalid and inconclusive ones; rejected candidates do not. Tests-to-first-failure is measured on the discovery pool only, so every planner receives the same verification treatment. Reports state the total episodes used, not only the discovery budget. With `onConfirmed: "continue"`, the confirmed region is excluded from later proposals by Decision so the planner looks for a distinct failure.

**Recommended, pending review:**

- `forcedEveryN` applies equally to every adaptive planner and is fixed before comparison runs, or is removed.
- Baselines (random, grid) run without the coverage phase; a separate "coverage then random" run isolates the effect of the coverage phase.

**Evidence since ratification (HLD 06 §4 and §7), pending a team decision:**

- Forced exploration never improved discovery in simulation and was significantly worse on one benchmark. Recommendation: remove `forcedEveryN`.
- The pairwise coverage phase gave small, non-significant gains on two benchmarks and was significantly worse on one (25% vs 35% discovery within 30 episodes). Recommendation: make coverage an optional setting, off by default.
- Minimizing toward nominal cannot show that a condition already at its nominal value is necessary (for example, green LED off). Recommendation: add one necessity probe per such discrete control, at a cost of about one episode each.
- A 16-episode verification budget was enough for a narrow failure window but ran out for wider windows. Recommendation: 24 episodes.

## 15. Decisions and Open Questions

This draft establishes the initial OLED demonstration as the working example, with small setup changes allowed. A campaign records the conditions it tested, separates requested inputs from measured values, and judges observable behavior against public requirements. Decision proposes conditions; Backend checks them against limits; Controller executes and measures them; the Oracle in Backend classifies the evidence.

The following details remain open until the exact bench setup is confirmed:

- Which supply channels, measurement instruments, and peripherals will be used.
- The reviewed voltage, current, temperature, timing, and shutdown limits for those parts.
- Which signals the fixture can measure reliably and how their calibration is recorded.
- The exact discovery and verification budgets for each campaign; §14 fixes the structure and defaults, not the bench-specific values.
- Each requirement's `nominal` and each observation's measurement `uncertainty` (§13).
- Which additional small setup changes should be compared with the OLED example.

These values should be filled from the selected hardware and bench review, not guessed from the example. Keep earlier results tied to the setup that produced them.
