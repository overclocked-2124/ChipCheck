# ActiveQual HLD 10: Verification and Implementation Plan

**Project:** ActiveQual: AI-Driven Adaptive Physical Testing for Embedded Systems  
**Document type:** High-Level Design  
**Status:** Initial draft for team review  
**Depends on:** HLDs 01–09

## 1. Purpose

This document defines how ActiveQual is built and verified within the 12-week proof of concept: the test layers, each service's definition of done, the order of work, the integration gates, and the kill criteria. Weeks are relative to the project start, which is not yet fixed (§9).

## 2. Current state

| Area | State |
|---|---|
| Decision Service | Built: contract v2 domain, planner registry (`tpe`, `gp`, `random`, `grid`), fixes and property tests (21 tests) |
| Console | Setup wizard and proposal preview via Next.js server routes; no campaign flow |
| Backend, Agent, Oracle, safety kernel | Not started |
| Controller, Adapter, simulator adapter | Not started |
| Test-controller and DUT firmware | Not started |
| Hardware | Parts and limits open (HLD 02) |

## 3. Test layers

| Layer | What it proves | Runs on |
|---|---|---|
| L0 Unit and property tests | Contract validation, safety rules, Oracle math, planner invariants | Every commit (laptop or cloud CI) |
| L1 Simulator campaigns | End-to-end control loop against the in-memory bench; planner comparisons with hundreds of campaigns | CI and cloud containers |
| L2 Loopback serial | Framing, CRC, duplicate detection, timeouts, malformed frames (HLD 05 §9) | CI with a virtual serial pair |
| L3 Dummy-load hardware | Rail accuracy, limits, cutoff, watchdog, E-stop, host loss (HLD 02 §18) | Bench, no DUT |
| L4 DUT acceptance | Workloads, heartbeat, oracle detection, trace alignment, 100 nominal episodes | Bench with DUT |
| L5 Research campaigns | Pre-registered comparisons (HLD 06) | Bench, supervised blocks |

The control plane and the simulator need no hardware, so L0–L2 can run in cloud containers and CI. Only the bench process needs the lab machine (HLD 01 §2.1).

## 4. Definition of done per service

| Service | Done when |
|---|---|
| Safety-rule library | Every HLD 04 rule implemented once and used by both Backend and Controller; complete decision coverage; 10,000 generated invalid candidates produce zero approvals |
| Backend | HLD 05 §5 and §7 endpoints; HLD 03 transitions with every unlisted transition rejected; idempotency per HLD 05 §8; audit events for every transition |
| Oracle | HLD 04 §13 Options A and B; classification order per HLD 03 §15.1; tests at each requirement boundary including inconclusive bands |
| Agent | Campaign loop with discovery and verification pools; verification phase per HLD 04 §14 (necessity probes and the 24-episode budget pending the decision in HLD 04 §14); stop rules |
| Decision | Done for the MVP (see §2); remaining: optional coverage planner |
| Simulator adapter | Implements the `BenchAdapter` interface with the HLD 06 benchmark profiles; under 1 ms per episode |
| Controller | HLD 03 episode state machine; preflight and live checks; shutdown and cutoff paths; local spool |
| Adapter | Capability reporting (HLD 02 §9); serial driver per HLD 05 §9; loopback and physical implementations |
| Console | HLD 09 pages; every HLD 03 §22 item visible |
| Test-controller firmware | HLD 05 §9 protocol; host-loss shutdown; watchdog; event templates within timing tolerance |
| DUT firmware | HLD 02 §12 workloads; telemetry; seeded fault behind a build flag with ground truth on a separate link |

## 5. Milestones and work packages

**ActiveQual decision (2026-11-05):** the build runs in four milestones. Milestone 2 runs the whole software loop, Controller included, against the simulator before any serial or hardware work, so every milestone ends with something runnable.

### 5.1 Package layout

Follows HLD 01 §6.2: `model/` (contract v2 schema, predicates, canonical hash, safety-rule library), `storage/`, `service/` (Backend and Oracle), `agent/service/`, `decision/service/` (exists), `controller/service/`, `adapter/service/`, `tools/` (benchmark CLI, hardware test harness), `console/ui/`, `firmware/`. One Python project with two entry points: `control-plane` and `bench`. The contract parsing now in `decision/service/domain.py` moves to `model/` so Backend, Controller and Decision share it.

### 5.2 Milestones

| Milestone | Work packages | Ends with |
|---|---|---|
| M1 Planners and simulator | WP0 (done), WP3 | Benchmark CLI reproduces the HLD 06 tables |
| M2 Software loop on the simulator | WP1, WP2, WP4, WP6, WP13, WP8 | **Gate A**, driven through the API |
| M3 Serial driver and loopback | WP9 | Loopback adapter passes the Controller test suite; firmware test vectors published |
| M4 Console | WP7 | HLD 09 pages; legacy setup path removed |

| WP | Content | Depends on | Effort (person-weeks) |
|---|---|---|---|
| WP0 | Decision Service, contract v2 domain (done) | — | — |
| WP1 | Shared safety-rule library in `model/`; RFC 8785 canonical JSON for the contract hash | HLD 04 | 1 |
| WP2 | Oracle (Options A and B, classification order HLD 03 §15.1) | HLD 04 | 0.5 |
| WP3 | `BenchAdapter` interface; in-memory simulator adapter with B1a, B1b, B1w, B2, B3 (no fault), B4 (instrument glitches); fixed/corner and coverage baseline planners (Halton sequence, no new dependency); benchmark CLI ported from the evaluation harness | HLD 06 | 1.5–2 |
| WP4 | Backend: HLD 05 §5 and §7 endpoints, HLD 03 state machines, idempotency, events, SQLite (HLD 08), bench token and reviewer role (HLD 07) | WP1, WP2 | 2 |
| WP5 | Thin hardware slice: one rail, DUT, real latency read-back; measure noise σ and settling | Parts for one rail | hardware track |
| WP6 | Agent loop: discovery and verification pools, confirm, minimize, bracket, stop rules; phase-plan items as configuration flags | WP4 | 1 |
| WP13 | Controller core: claim and lease, preflight, phase state machine, ordered shutdown, local spool, against any `BenchAdapter` | WP4 | 1–1.5 |
| WP8 | Simulated end-to-end campaigns through every service; parity check that full-stack campaigns match the benchmark CLI (HLD 01 CTX-09) | WP3, WP6, WP13 | 0.5 |
| WP9 | COBS + CRC framing library; byte-stream transport interface; in-process MCU emulator (the firmware's reference); loopback and physical serial adapters; dummy-load test harness | HLD 05 §9 | 2 |
| WP7 | Console: contract editor, arm checklist, live campaign over server-sent events, failure region, verification, counterexample, report, comparison | WP4 API stable | 3 |
| WP10 | Dummy-load safety acceptance | WP9, safety hardware | hardware track |
| WP11 | DUT firmware, seeded benchmark on hardware | WP10 | hardware track |
| WP12 | Pre-registered research campaigns and report | Gate C | research track |

Software total: about 12 person-weeks, spread over the platform and algorithms roles (§9).

### 5.3 Implementation constraints

- **One control-plane process, one server worker.** SQLite has one writer and the Agent loop runs inside the process; several workers would mean several writers and duplicate Agent loops.
- **No OS-specific test transport.** pyserial's `loop://` only echoes the host's own writes, and virtual pty pairs are POSIX-only. Adapters talk to a byte-stream transport; tests plug in the in-process MCU emulator, so they run on Linux, macOS and Windows alike.
- **Planner exclusion is not a retry policy.** The Agent schedules retries of invalid points as new linked episodes (HLD 03 §17.2).
- **The benchmark CLI is a fast path.** Research numbers on hardware go through the full stack; the WP8 parity check guards the difference.

## 6. Schedule (relative weeks)

| Week | Software | Hardware |
|---:|---|---|
| 1 | Package layout; WP3 | Inventory; order parts; WP5 begins |
| 2 | WP3 done (M1); WP1, WP2 | WP5: one rail on a dummy load |
| 3 | WP4; WP9 framing and emulator begin | WP5: DUT on one rail, latency read-back, noise measured |
| 4 | WP4; WP9 test vectors to firmware | Kill criterion K1 (§8) |
| 5 | WP6, WP13 | Firmware against the test vectors |
| 6 | WP8, **Gate A**; WP7 begins | Cutoff and E-stop |
| 7 | WP9 adapters done (M3); WP7 | WP10 dummy-load acceptance |
| 8 | WP7; bench integration | **Gate B**; kill criterion K2 |
| 9 | WP7; bench integration | WP11 DUT integration |
| 10 | WP7 done (M4); **Gate C**; pre-registration frozen | 100 nominal episodes |
| 11 | WP12 research campaigns | Supervised campaign blocks |
| 12 | Report, demo rehearsal, evidence freeze | Hardware freeze |

## 7. Integration gates

| Gate | Pass condition |
|---|---|
| A — simulated end to end | A campaign runs through the API: Backend → Agent → Decision → Backend safety → Controller → simulator adapter → Oracle → report, with no hardware; the WP8 parity check passes; L0–L2 green |
| B — dummy-load safety | Every HLD 02 §18 test passes on dummy loads; host loss and E-stop measured |
| C — DUT ready | 100 nominal episodes with under 5% invalid; seeded benchmark detected on a fixed plan; calibration recorded; Console shows every HLD 03 §22 item |

## 8. Kill and pivot criteria

| ID | When | Condition | Action |
|---|---|---|---|
| K1 | Week 4 | No safe, read-back-capable rail on the thin slice | Pivot to simulator-first research with one physical validation channel |
| K2 | Week 8 | Dummy-load safety tests fail | No DUT campaigns until fixed |
| K3 | Week 10 | Over 5% invalid episodes in 100 nominal runs | Pause algorithm work; fix instrumentation |
| K4 | Any | Measured latency noise makes the guard band cover most of the requirement range (HLD 06 §6) | Redesign the observation or the requirement before campaigns |

## 9. Ownership

Adapted from PRD §28 for five people:

| Role | Owns |
|---|---|
| A — Research lead | HLD 06 pre-registration, analysis, report, demo |
| B — Hardware and safety lead | WP5, WP10, HLD 02 decisions, safety approvals |
| C — Embedded lead | WP9 framing spec, MCU emulator and test vectors (weeks 3–4); test-controller firmware; WP11 DUT firmware and seeded benchmarks |
| D — Algorithms and data lead | WP2, WP3, WP6 verification phase; WP9 host-side serial adapters and dummy-load harness (weeks 6–7); statistics |
| E — Platform lead | WP1, WP4, WP13 Controller (week 5), WP8, WP7, deployment |

Load check: no role carries more than one work package in the same week except week 6 (E closes WP8 and starts WP7). WP9 is split between C and D because firmware alone fills C's weeks 3–7.

Two-person review for any safety-limit or fixture change (PRD §28.1).

## 10. Open decisions

| Decision | Recommended direction |
|---|---|
| Project start date and 12 vs 24 weeks | Fix a start date; plan to 12 weeks with the PRD's 24-week items as stretch |
| Second DUT and natural fault (PRD exit criteria) | Stretch goals, not MVP |
| CI provider | Any runner that can execute L0–L2; the Decision Service tests already run headless |

## 11. Change log

| Date | Change |
|---|---|
| 2026-11-05 | Initial draft |
| 2026-11-05 | Milestones locked after a two-pass review: Controller work package added, Gate A defined through the API, serial work moved earlier, layout aligned with HLD 01 §6.2, implementation constraints added |
