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
- [HLD 04: Test Contract and Domain Model](./docs/04-activequal-test-contract-and-domain-model.md)
- [HLD 05: APIs and Instrumentation Protocols](./docs/05-activequal-apis-and-instrumentation-protocols.md)
- [HLD 06: Adaptive Search and Research Evaluation](./docs/06-activequal-adaptive-search-and-research-evaluation.md)
- [HLD 07: Security and Deployment](./docs/07-activequal-security-and-deployment.md)
- [HLD 08: Persistence, Telemetry, and Observability](./docs/08-activequal-persistence-telemetry-and-observability.md)
- [HLD 09: Console and Researcher Experience](./docs/09-activequal-console-and-researcher-experience.md)
- [HLD 10: Verification and Implementation Plan](./docs/10-activequal-verification-and-implementation-plan.md)

- [Algorithm and ML Methodology](./Documnentation%20on%20Algorithm/ChipCheck_Algorithm_and_ML_Methodology.docx)
- [Simplified implementation proposal](./docs/SIMPLIFIED-PLAN.md)
- [Design issue analysis](./docs/SOLUTIONS.md)
- [Project walkthrough](./docs/WALKTHROUGH.md)
- [SWE Handoff: Software-First POC, Plug-and-Play Planners & Hardware Integration](./docs/SWE-POC-HANDOFF.md)

The HLD documents define the current design and service boundaries. The methodology and proposal documents provide background; where they differ from the HLDs, the HLDs win.

## Run it (no GPU or hardware needed)

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m unittest discover -s activequal -t .          # full suite
.venv/bin/python -m activequal.tools.benchmark --campaigns 20      # planner comparison on the simulator
.venv/bin/python -m activequal.service.app --init                  # config, operator token, reviewer passphrase
.venv/bin/python -m activequal.service.app                         # control plane on 127.0.0.1:8001
.venv/bin/python -m activequal.tools.demo_seed                     # approved OLED contract, bench-A, calibration
.venv/bin/python -m activequal.controller.service.app --fixture-id bench-A \
    --token-file ~/.config/activequal/bench-A.token --mode sim --profile B1w
cd activequal/console/ui && npm ci && \
    ACTIVEQUAL_OPERATOR_TOKEN_FILE=~/.config/activequal/operator.token npm run dev   # Console
```

Bench tools (HLD 02 §18):

```bash
.venv/bin/python -m activequal.tools.hardware_check --emulator --energize        # self-test, no hardware
.venv/bin/python -m activequal.tools.hardware_check --port /dev/ttyACM0          # real test controller
.venv/bin/python -m activequal.tools.calibrate points.json --operator dana --post # rail calibration
```

The optional `gp` planner needs `.[gp]` (torch, CPU is enough). Real serial benches use `--mode serial --port /dev/ttyACM0` with `.[serial]`; that path is tested only against the MCU emulator.
