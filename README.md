# ChipCheck: Adaptive Hardware Fuzzing Testbench (AHFT)

> **Safety-Constrained Adaptive Physical Fuzzing for Embedded Systems**

This repository contains the Product Requirements Document (PRD) and specification for **ChipCheck / Adaptive Hardware Fuzzing Testbench (AHFT)**.

## Overview

ChipCheck is a hardware-in-the-loop (HIL) test station that:
1. Accepts an engineer-written **test contract** defining controllable variables, measurable outputs, legal operating limits, hard safety limits, and failure requirements;
2. Chooses informative next physical experiments within that contract using adaptive test selection;
3. Controls external programmable rails and workloads while the real device under test (DUT) runs;
4. Records synchronized electrical and firmware observations;
5. Assigns a pass/fail result and a continuous robustness score;
6. Minimizes and reproduces discovered failures under a strict experiment budget; and
7. Produces an evidence package with exact test sequences, measured traces, safety decisions, and residual uncertainty.

## Documentation

- [Product Requirements Document (PRD)](./docs/adaptive-hardware-fuzzing-prd.md)
- [HLD Document Map](./docs/00-activequal-hld-document-map.md)
- [HLD 01: System Context and Platform Boundaries](./docs/01-activequal-system-context-and-platform-boundaries.md)
- [HLD 02: Hardware Architecture](./docs/02-activequal-hardware-architecture.md)
- [HLD 03: Episode Execution and Safety State Machine](./docs/03-activequal-episode-execution-and-safety-state-machine.md)

- [Algorithm and ML Methodology](./Documnentation%20on%20Algorithm/ChipCheck_Algorithm_and_ML_Methodology.docx)
- [Simplified implementation proposal](./docs/SIMPLIFIED-PLAN.md)
- [Design issue analysis](./docs/SOLUTIONS.md)
- [Project walkthrough](./docs/WALKTHROUGH.md)

The HLD documents define the current service boundaries. The methodology documents provide planner and research guidance; their combined Python stack is an alternative proposal.
