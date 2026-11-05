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

## 5. Work packages and order

```text
              ┌─ WP1 Safety-rule library ─┐
WP0 (done) ───┼─ WP2 Oracle ───────────────┼─ WP4 Backend ─┬─ WP6 Agent ── WP8 Simulated end-to-end (Gate A)
              └─ WP3 Simulator adapter ────┘               └─ WP7 Console campaign flow
WP5 Thin hardware slice (in parallel from week 1) ── WP9 Serial driver + firmware ── WP10 Dummy-load (Gate B)
                                                                  └── WP11 DUT integration ── Gate C ── WP12 Research campaigns
```

| WP | Content | Depends on |
|---|---|---|
| WP0 | Decision Service, contract v2 domain (done) | — |
| WP1 | Shared safety-rule library | HLD 04 |
| WP2 | Oracle (Options A and B) | HLD 04 |
| WP3 | Simulator adapter and benchmark CLI (move the evaluation harness into the repository); fixed/corner and coverage baseline planners required by HLD 01 §3.2 | HLD 06 |
| WP4 | Backend: contracts, campaigns, candidates, episodes, leases, results, events; SQLite | WP1, WP2, HLD 05, HLD 08 |
| WP5 | Thin hardware slice: one rail, DUT, real latency read-back; measure noise σ and settling | Parts for one rail |
| WP6 | Agent loop and verification phase | WP4 |
| WP7 | Console campaign pages | WP4, HLD 09 |
| WP8 | Simulated end-to-end campaign through every service | WP3, WP6 |
| WP9 | Serial driver, loopback tests, test-controller firmware | HLD 05 §9 |
| WP10 | Dummy-load safety acceptance | WP9, safety hardware |
| WP11 | DUT firmware, seeded benchmark on hardware | WP10 |
| WP12 | Pre-registered research campaigns and report | Gate C |

## 6. Schedule (relative weeks)

| Week | Software | Hardware |
|---:|---|---|
| 1 | WP1, WP2 | Inventory; order parts; WP5 begins |
| 2 | WP1, WP2, WP3 | WP5: one rail on a dummy load |
| 3 | WP4 | WP5: DUT on one rail, latency read-back, noise measured |
| 4 | WP4, WP6 | Kill criterion K1 (§8) |
| 5 | WP6, WP7 | WP9: framing and firmware |
| 6 | WP8, **Gate A** | WP9, cutoff and E-stop |
| 7 | WP7, hardening | WP10 dummy-load acceptance |
| 8 | Bench integration | **Gate B**; kill criterion K2 |
| 9 | Bench integration | WP11 DUT integration |
| 10 | **Gate C**; pre-registration frozen | 100 nominal episodes |
| 11 | WP12 research campaigns | Supervised campaign blocks |
| 12 | Report, demo rehearsal, evidence freeze | Hardware freeze |

## 7. Integration gates

| Gate | Pass condition |
|---|---|
| A — simulated end to end | A campaign runs Console → Backend → Agent → Decision → simulator → Oracle → report with no hardware; L0–L2 green |
| B — dummy-load safety | Every HLD 02 §18 test passes on dummy loads; host loss and E-stop measured |
| C — DUT ready | 100 nominal episodes with under 5% invalid; seeded benchmark detected on a fixed plan; calibration recorded |

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
| C — Embedded lead | WP9 firmware, WP11 DUT firmware, seeded benchmarks |
| D — Algorithms and data lead | WP2, WP3, WP6 verification phase, statistics |
| E — Platform lead | WP1, WP4, WP7, WP8, deployment |

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
