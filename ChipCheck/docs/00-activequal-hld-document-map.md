# ActiveQual High-Level Design Document Map

**Purpose:** Define the document numbering pattern, explain what information belongs in each design document, and track drafting progress.  
**Project duration:** 12-week proof of concept  
**Status:** Living index  

## 1. File naming pattern

Every architecture document uses:

```text
NN-activequal-topic-name.md
```

Where:

- `NN` is the two-digit reading and implementation order;
- `activequal` identifies the project;
- `topic-name` describes the document's single main responsibility;
- filenames use lowercase words separated by hyphens;
- the document title uses `ActiveQual HLD NN`;
- approved documents are stored in the main Documents folder;
- drafts remain in the working output folder until reviewed.

Examples:

```text
00-activequal-hld-document-map.md
01-activequal-system-context-and-platform-boundaries.md
02-activequal-hardware-architecture.md
03-activequal-episode-execution-and-safety-state-machine.md
```

## 2. Document status values

| Status | Meaning |
|---|---|
| Planned | Scope is known, but drafting has not started |
| Initial draft | First complete version exists and needs review |
| In review | The team is actively commenting or changing decisions |
| Approved | The team accepts the document as the implementation baseline |
| Superseded | A newer document or recorded decision replaces it |

Moving a file into the main Documents folder means it is accepted as the current working baseline. It may still be revised later.

## 3. Document map

| No. | Document | Main question answered | Status |
|---:|---|---|---|
| 00 | HLD Document Map | Which document owns each design topic, and in what order should the documents be read? | Approved |
| 01 | System Context and Platform Boundaries | What is ActiveQual, who uses it, which services exist, and where are the application, bench, and hardware boundaries? | Approved |
| 02 | Hardware Architecture | How are the DUT, power rails, test controller, measurements, signal protection, and physical safety mechanisms connected? | Approved |
| 03 | Episode Execution and Safety State Machine | How does a campaign and one physical experiment move from proposal through safety validation, execution, shutdown, classification, and recovery? | Initial draft |
| 04 | Test Contract and Domain Model | How does a DUT declare variables, legal ranges, constraints, workloads, observations, failure rules, budgets, and compatible fixtures? | Planned |
| 05 | APIs and Instrumentation Protocols | What RPCs and device messages connect the Console, BFF, Backend, Agent, Controller, Adapter, test controller, and DUT? | Planned |
| 06 | Adaptive Search and Research Evaluation | How are experiments selected, how do baselines and adaptive methods share one interface, and how will performance be compared fairly? | Planned |
| 07 | Security and Deployment | How are users and machine processes authenticated, how are services deployed, and how are credentials and network boundaries protected? | Planned |
| 08 | Persistence, Telemetry, and Observability | Which database entities, events, measurements, traces, logs, and metrics are stored, and how are they queried and retained? | Planned |
| 09 | Console and Researcher Experience | What screens and user flows support contract review, arming, live execution, failures, minimization, comparison, and reporting? | Planned |
| 10 | Verification and Implementation Plan | How will software, simulator, dummy-load, hardware, safety, and research acceptance be tested and delivered within 12 weeks? | Planned |

## 4. Document responsibilities

### HLD 01 — System Context and Platform Boundaries

Contains:

- project purpose, MVP scope, stretch scope, and non-goals;
- human actors and external systems;
- Console, BFF, Backend, Agent, Controller, and Adapter Service boundaries;
- control-plane and bench-plane separation;
- high-level authority and trust boundaries;
- local MVP deployment shape;
- high-level data ownership;
- system-wide failure behavior.

Does not contain:

- electrical schematics or component selection;
- exact state-transition rules;
- protobuf messages or database tables;
- adaptive-search mathematics.

### HLD 02 — Hardware Architecture

Contains:

- DUT components and power domains;
- three programmable peripheral rails;
- fixed controller and ESP32 supplies for the initial benchmark;
- test-controller MCU responsibilities;
- rail measurement and transient capture;
- OLED external observation;
- signal isolation and back-power prevention;
- watchdog, interlock, fuse, current limit, and E-stop;
- normal power sequencing;
- equipment inventory and hardware acceptance tests.

Does not contain:

- campaign scheduling;
- database persistence;
- planner algorithms;
- detailed application RPCs.

### HLD 03 — Episode Execution and Safety State Machine

Contains:

- campaign lifecycle;
- candidate validation lifecycle;
- physical episode lifecycle;
- episode leases and physical ownership;
- phase-specific safety checks;
- pause, abort, disarm, shutdown, cutoff, and lockout;
- outcome classification;
- retry and idempotency rules;
- disconnect recovery;
- state-machine acceptance tests.

Does not contain:

- exact database entities;
- complete protobuf definitions;
- hardware circuit selection;
- adaptive model implementation.

### HLD 04 — Test Contract and Domain Model

Will contain:

- contract identity, version, approval, and immutable hash;
- controllable continuous, integer, Boolean, categorical, and timing variables;
- engineering units and measurement tolerance;
- legal ranges and forbidden combinations;
- power and signal transition constraints;
- approved workload/event templates;
- required observations and measurement-quality rules;
- pass/fail oracle definitions;
- safety limits and shutdown state;
- campaign budgets and stopping rules;
- fixture and firmware compatibility;
- domain entities and conversion boundaries;
- complete OLED-demo contract example.

### HLD 05 — APIs and Instrumentation Protocols

Will contain:

- Console-to-BFF RPCs;
- BFF-to-Backend RPCs;
- Agent proposal interface;
- Controller claim, lease, heartbeat, and result-submission RPCs;
- Adapter capability and operation interfaces;
- test-controller serial protocol;
- ESP32 DUT workload protocol;
- request identity, versions, idempotency keys, and error models;
- timeouts and compatibility negotiation;
- example end-to-end messages.

### HLD 06 — Adaptive Search and Research Evaluation

Will contain:

- common planner interface;
- feature representation for mixed continuous, discrete, and temporal inputs;
- initial space-filling phase;
- random, fixed/corner, grid, pairwise, and space-filling baselines;
- selected adaptive method;
- continuous robustness and failure-probability signals;
- exploration versus exploitation;
- invalid-experiment handling;
- failure confirmation, boundary mapping, and minimization;
- experiment budgets and stopping rules;
- tests-to-first-failure, discovery rate, characterization accuracy, and minimal-reproducer metrics;
- repeated seeds, held-out benchmarks, and statistical analysis.

### HLD 07 — Security and Deployment

Will contain:

- researcher authentication and project authorization;
- Controller Service machine identity;
- fixture registration and credential lifecycle;
- service and network boundaries;
- local-development deployment;
- process startup, readiness, and shutdown;
- secrets and configuration handling;
- protection against replayed or cross-fixture commands;
- software and firmware version binding;
- supervised-lab restrictions;
- future remote-deployment considerations.

### HLD 08 — Persistence, Telemetry, and Observability

Will contain:

- campaign, contract, fixture, candidate, episode, lease, result, and event entities;
- requested versus measured values;
- raw-trace manifests and checksums;
- local evidence spool;
- state-transition audit history;
- metrics, structured logs, and health signals;
- trace alignment;
- data retention and export;
- evidence-bundle structure;
- research queries and dashboard read models.

### HLD 09 — Console and Researcher Experience

Will contain:

- navigation and page structure;
- contract creation and review;
- fixture readiness and campaign arming;
- live campaign view;
- current episode and phase display;
- safety and lockout presentation;
- failure-region visualization;
- trace and evidence inspection;
- confirmation and minimization flows;
- baseline comparison and final report;
- empty, loading, disconnected, invalid, and error states;
- teacher demonstration flow.

### HLD 10 — Verification and Implementation Plan

Will contain:

- simulator strategy;
- contract and state-machine tests;
- Adapter and protocol tests;
- dummy-load hardware tests;
- safety acceptance suite;
- seeded benchmark validation;
- repeated research campaigns;
- definition of done for every service;
- five-person ownership map;
- dependencies and critical path;
- week-by-week implementation schedule;
- integration gates, demonstration rehearsal, and final evidence freeze.

## 5. Source-of-truth rules

When information could fit in multiple documents:

1. Store the full decision in the document that owns the topic.
2. Other documents should give a short summary and link to the owning document.
3. Do not copy complete tables or rules between documents.
4. If a decision changes, update the owning document first.
5. Record the impact on dependent documents in the change log.

Examples:

| Information | Owning document |
|---|---|
| Why the Controller Service exists | HLD 01 |
| Exact rail wiring and signal isolation | HLD 02 |
| Meaning of `LOCKED_OUT` | HLD 03 |
| Maximum OLED voltage field and unit | HLD 04 |
| `ClaimNextEpisode` request and response | HLD 05 |
| How the adaptive planner selects a candidate | HLD 06 |
| Controller machine credential | HLD 07 |
| Episode database schema | HLD 08 |
| Live campaign screen | HLD 09 |
| Physical E-stop acceptance procedure | HLD 10 |

## 6. Required structure for every HLD

Each HLD should normally contain:

1. Title and metadata.
2. Purpose.
3. Scope and non-goals.
4. Terms that are specific to the document.
5. Requirements and constraints.
6. Architecture or flow diagram.
7. Component responsibilities.
8. Main execution or data flow.
9. Failure and recovery behavior.
10. Security or safety implications.
11. Decisions made.
12. Open decisions.
13. Acceptance or review checklist.
14. Change log.

Sections may be omitted when they do not apply, but the document should explain a consequential omission.

## 7. Decision language

Use these labels:

- **Verified stack pattern:** Existing implementation convention confirmed from the current source.
- **ActiveQual decision:** A design choice accepted for this project.
- **Recommended:** Current preferred option awaiting review.
- **Open decision:** Choice requiring evidence, a spike, or team agreement.
- **Stretch:** Useful after the MVP is complete.

Avoid presenting recommendations as existing facts.

## 8. Cross-document vocabulary

Use these terms consistently:

| Preferred term | Meaning |
|---|---|
| Researcher | Person who defines, runs, monitors, and evaluates campaigns |
| DUT | Complete device under test |
| Test contract | Versioned declaration of controls, legal limits, observations, and requirements |
| Campaign | One budgeted research run |
| Candidate | Agent Service proposal before safety approval |
| Episode | One durable reset-to-reset physical experiment |
| Outcome | `PASS`, `DUT_FAILURE`, `INVALID_EXPERIMENT`, or `SAFETY_ABORT` |
| Agent Service | Selects proposed experiments and schedules minimization |
| Controller Service | Owns the local physical episode state machine |
| Adapter Service | Translates generic operations into instrument-specific commands |
| Test-controller MCU | Executes deterministic timing and maintains watchdog liveness |
| Raw trace | Detailed waveform, image, event capture, or log from an episode |
| Trace reference | Database metadata pointing to a separately stored raw trace |
| Shutdown | Normal transition to the safe output state |
| Lockout | Prevention of new execution until a safety event is manually reviewed |

## 9. Current files

| File | Location |
|---|---|
| `00-activequal-hld-document-map.md` | Main Documents folder |
| `01-activequal-system-context-and-platform-boundaries.md` | Main Documents folder |
| `02-activequal-hardware-architecture.md` | Main Documents folder |
| `03-activequal-episode-execution-and-safety-state-machine.md` | Draft working folder; move to Documents after review |

## 10. Change log

| Date | Change |
|---|---|
| 2026-09-10 | Created the document map, numbering convention, topic ownership, standard HLD structure, and initial status table |
