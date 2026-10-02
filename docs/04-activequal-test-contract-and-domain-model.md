# ActiveQual HLD 04: Test Contract and Domain Model

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

## 12. Decisions and Open Questions

This draft establishes the initial OLED demonstration as the working example, with small setup changes allowed. A campaign records the conditions it tested, separates requested inputs from measured values, and judges observable behavior against public requirements. Decision proposes conditions; Backend checks them against limits; Controller executes and measures them; the oracle classifies the evidence.

The following details remain open until the exact bench setup is confirmed:

- Which supply channels, measurement instruments, and peripherals will be used.
- The reviewed voltage, current, temperature, timing, and shutdown limits for those parts.
- Which signals the fixture can measure reliably and how their calibration is recorded.
- How much of the declared budget to reserve for discovery, confirmation, and minimization.
- Which additional small setup changes should be compared with the OLED example.

These values should be filled from the selected hardware and bench review, not guessed from the example. Keep earlier results tied to the setup that produced them.
