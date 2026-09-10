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

- [Product Requirements Document (PRD)](./adaptive-hardware-fuzzing-prd.md)
