> **Status:** Methodology and alternative implementation proposal. The ActiveQual HLD documents define current service ownership. For the implemented architecture, Decision proposes candidates; Backend and Controller own approval and execution. Values and hardware limits in this document are examples until reviewed for the selected fixture.

# ChipCheck — Complete Project Walkthrough

> A plain-English, step-by-step explanation of what this project is, who it's for, and exactly how everything works.

---

## Table of Contents

1. [The Problem We're Solving](#1-the-problem-were-solving)
2. [What ChipCheck Actually Is](#2-what-chipcheck-actually-is)
3. [Who Uses This and Why](#3-who-uses-this-and-why)
4. [The Physical Setup — What's on the Bench](#4-the-physical-setup--whats-on-the-bench)
5. [The Software Stack — What Runs on the Computer](#5-the-software-stack--what-runs-on-the-computer)
6. [Core Concept: The Test Contract](#6-core-concept-the-test-contract)
7. [Core Concept: The Safety System](#7-core-concept-the-safety-system)
8. [Core Concept: The Adaptive AI Planner](#8-core-concept-the-adaptive-ai-planner)
9. [Step-by-Step: Setting Up a New Device for Testing](#9-step-by-step-setting-up-a-new-device-for-testing)
10. [Step-by-Step: Running a Test Campaign](#10-step-by-step-running-a-test-campaign)
11. [Step-by-Step: What Happens When a Failure is Found](#11-step-by-step-what-happens-when-a-failure-is-found)
12. [The Teacher Demo — The 8-Minute Showpiece](#12-the-teacher-demo--the-8-minute-showpiece)
13. [What Makes This a Research Project](#13-what-makes-this-a-research-project)
14. [What This Project Does NOT Do](#14-what-this-project-does-not-do)
15. [Glossary](#15-glossary)

---

## 1. The Problem We're Solving

### The Real-World Scenario

Imagine you're building an IoT weather station — an ESP32 board with a display, a temperature sensor, Wi-Fi connectivity, an LED indicator, and flash storage. You test it on your bench: power it up at 3.3V, the display works, the sensor reads correctly, Wi-Fi connects. Ship it.

Three months later, a customer reports: *"The display freezes randomly."*

After weeks of debugging, you discover the cause:

```
When the battery drops to around 3.25V
AND the red status LED is on
AND the green LED is off
AND the display is refreshing
→ The display task gets starved and freezes
```

This failure never showed up in your testing because you never happened to test that exact combination. Each condition alone was fine. It was the **interaction** that caused the problem.

### Why This Is Hard

The math is brutal. Even a simple board has many things you could vary:

| What you can control | Example values |
|---|---|
| Main power voltage | 3.0V to 5.0V in 0.01V steps = ~200 settings |
| OLED display voltage | 3.0V to 3.6V in 0.01V steps = ~60 settings |
| Sensor rail voltage | 3.0V to 3.6V in 0.01V steps = ~60 settings |
| Red LED | ON or OFF = 2 states |
| Green LED | ON or OFF = 2 states |
| Active workload | idle, display refresh, sensor read, Wi-Fi transmit, flash write = 5 states |
| Event timing | Which workload starts first? How long between them? |

Even if you simplify to just 20 voltage steps per rail, 5 rails, and 4 binary states:

```
20 × 20 × 20 × 20 × 20 × 2 × 2 × 2 × 2 = 51,200,000 combinations
```

At 2 seconds per test, that's **3.2 years of non-stop testing**. And that's ignoring timing variations.

### The Question This Project Asks

> If you can only afford to run 30 (or 50, or 100) physical experiments, which ones should you pick to have the best chance of finding a bug?

That's what ChipCheck does. It picks the experiments intelligently.

---

## 2. What ChipCheck Actually Is

ChipCheck is a **test station** — a combination of hardware on a lab bench and software on a laptop. Together they form an automated loop:

```
                    ┌──────────────────────────────┐
                    │                              │
                    ▼                              │
            ┌──────────────┐                       │
            │  AI Planner  │ "Test 3.24V with      │
            │  picks next  │  red LED on and       │
            │  experiment  │  display refreshing"   │
            └──────┬───────┘                       │
                   │                               │
                   ▼                               │
            ┌──────────────┐                       │
            │ Safety Check │ "Is this within       │
            │              │  approved limits?"    │
            │              │  → YES, approved      │
            └──────┬───────┘                       │
                   │                               │
                   ▼                               │
            ┌──────────────┐                       │
            │   Execute    │  Set voltage to 3.24V │
            │   on real    │  Turn on red LED      │
            │   hardware   │  Start OLED refresh   │
            └──────┬───────┘                       │
                   │                               │
                   ▼                               │
            ┌──────────────┐                       │
            │   Measure    │  Record voltage,      │
            │  everything  │  current, timing,     │
            │              │  heartbeat, display   │
            └──────┬───────┘                       │
                   │                               │
                   ▼                               │
            ┌──────────────┐                       │
            │    Judge     │  Pass or fail?        │
            │   (Oracle)   │  How close to failing?│
            └──────┬───────┘                       │
                   │                               │
                   ▼                               │
            ┌──────────────┐                       │
            │  AI learns   │  "Interesting, the    │
            │  from result │   display was slow    │
            │              │   near 3.25V..."      │
            └──────┬───────┘                       │
                   │                               │
                   └───────────────────────────────┘
                        Repeat until budget runs out
                        or failure is found
```

The key insight: **the AI doesn't just test randomly**. After each test, it learns something about where failures might be hiding and focuses its next test on the most suspicious areas.

---

## 3. Who Uses This and Why

### User 1: The Embedded Engineer (Primary User)

**Who:** Someone building an IoT product — maybe a smart thermostat, a sensor node, a display gadget.

**Their problem:** They've done basic testing but they're worried about weird corner cases. They can't test every combination manually. They've been burned before by field failures.

**How ChipCheck helps:** They write a "test contract" describing their board, plug it into the test station, and let ChipCheck systematically hunt for failure conditions. If something is found, they get an exact reproducible recipe: *"This fails when you set the OLED rail to 3.24V, turn the red LED on, and start an OLED refresh."*

### User 2: The Hardware Startup Engineer

**Who:** Someone who just had to swap a voltage regulator because the original went out of stock (very common in hardware).

**Their problem:** Does the new regulator change the failure behavior? Does the board still work in all the same conditions?

**How ChipCheck helps:** Run the same test contract on both board versions. Compare side-by-side. See if the failure boundary moved.

### User 3: The Researcher / Algorithm Developer

**Who:** Someone studying adaptive testing algorithms.

**Their problem:** Most test benchmarks are simulated. They want to test on real, noisy, physical hardware.

**How ChipCheck helps:** The project produces a reusable benchmark suite with documented devices, contracts, and ground truth.

### User 4: The Faculty Evaluator / Teacher

**Who:** The professor grading this project.

**Their problem:** AI project demos can be vague or fake. They want to see something real and understand what's happening.

**How ChipCheck helps:** A live 8-minute demo where they can see real hardware being tested, watch the AI home in on a failure, and see the failure reproduced in real-time. Everything is transparent — the test limits are shown, every decision is logged, and the seeded bug is disclosed.

### User 5: Lab Operator

**Who:** Someone running the test station day-to-day.

**Their problem:** They need test campaigns to be safe and repeatable without deep expertise.

**How ChipCheck helps:** The test contract defines everything. The safety system prevents damage. The UI guides the process.

---

## 4. The Physical Setup — What's on the Bench

Here's what the actual lab bench looks like:

```
┌─────────────────────────────────────────────────────────────────┐
│                         LAB BENCH                               │
│                                                                 │
│  ┌──────────┐      ┌──────────────────┐      ┌──────────────┐  │
│  │  LAPTOP  │──USB─│ PROGRAMMABLE     │──────│ DEVICE UNDER │  │
│  │          │      │ POWER SUPPLIES   │ wires│ TEST (DUT)   │  │
│  │ Runs the │      │                  │      │              │  │
│  │ software │      │ Ch1: Main power  │      │ ESP32-S3     │  │
│  │          │      │ Ch2: OLED rail   │      │ + OLED       │  │
│  │          │      │ Ch3: Sensor rail │      │ + Sensor     │  │
│  │          │      └──────────────────┘      │ + LEDs       │  │
│  │          │                                │ + Wi-Fi      │  │
│  │          │──USB─┌──────────────────┐      └──────┬───────┘  │
│  │          │      │ OSCILLOSCOPE /   │◄────────────┘          │
│  │          │      │ DAQ              │  probe wires           │
│  │          │      │ (measures stuff) │                        │
│  │          │      └──────────────────┘                        │
│  │          │                                                  │
│  │          │──USB─┌──────────────────┐                        │
│  │          │      │ TEST CONTROLLER  │──── trigger/reset ───► │
│  │          │      │ (RP2040/STM32)   │     to DUT             │
│  │          │      │ Watchdog + timing│                        │
│  │          │      └──────────────────┘                        │
│  └──────────┘                                                  │
│                                                                 │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              INDEPENDENT SAFETY CHAIN                   │    │
│  │  [E-STOP Button] ── [Fuses] ── [Current Comparator]   │    │
│  │  Can cut ALL power to the DUT without any software     │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### Hardware Components Explained

| Component | What it is | What it does |
|---|---|---|
| **Laptop/PC** | Any computer with USB | Runs all the software — AI planner, safety checks, UI, data logging |
| **Programmable Power Supplies** | Lab instruments (borrowed or bought) | Set precise voltages on each rail of the DUT. Can be commanded from the laptop. Have their own built-in overcurrent/overvoltage protection |
| **Device Under Test (DUT)** | The ESP32/STM32 board being tested | The actual product. Runs firmware that does real work (display refresh, sensor reads, Wi-Fi) and sends back heartbeat/status |
| **Oscilloscope / DAQ** | Measurement instrument | Watches voltage, current, and timing on the DUT's rails. Captures fast transients the software alone would miss |
| **Test Controller MCU** | A separate RP2040 or STM32 | Handles precise timing, triggers workloads on the DUT, and acts as a hardware watchdog (cuts power if the laptop crashes) |
| **Safety Chain** | Fuses + comparators + E-stop | Completely independent of software. If current or voltage goes too high, it physically disconnects power. The red E-stop button is always accessible |

### The Three Programmable Rails (Minimum Setup)

```
Rail 1: Main DUT / Regulator Input    ──► Powers the core of the board
Rail 2: OLED Display Power             ──► Powers just the display (can be varied independently)
Rail 3: Sensor / Peripheral Power      ──► Powers just the sensor (can be varied independently)
```

By controlling these separately, ChipCheck can test what happens when, say, the display gets 3.2V while the sensor gets 3.5V and the main board gets 4.2V — something that might happen in real life as batteries drain unevenly or regulators behave differently under load.

---

## 5. The Software Stack — What Runs on the Computer

```
┌─────────────────────────────────────────────────────────┐
│                    WEB BROWSER (UI)                       │
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌───────────┐ │
│  │ Contract │ │ Live Map │ │ Timeline  │ │  Report   │ │
│  │ Review   │ │ (pass/   │ │ (events)  │ │ Generator │ │
│  │ & Arming │ │  fail    │ │           │ │           │ │
│  │          │ │  regions)│ │           │ │           │ │
│  └──────────┘ └──────────┘ └───────────┘ └───────────┘ │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  BACKEND SERVICES                        │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │  Campaign   │  │   Adaptive   │  │  Safety        │ │
│  │ Orchestrator│  │   Planner    │  │  Kernel        │ │
│  │             │  │   (the AI)   │  │  (the guard)   │ │
│  │ Manages the │  │              │  │                │ │
│  │ whole loop  │  │ Picks next   │  │ Blocks unsafe  │ │
│  │             │  │ experiment   │  │ experiments    │ │
│  └──────┬──────┘  └──────────────┘  └────────────────┘ │
│         │                                                │
│  ┌──────┴──────┐  ┌──────────────┐  ┌────────────────┐ │
│  │  Instrument │  │   Oracle /   │  │   Data         │ │
│  │  Adapters   │  │   Scorer     │  │   Recorder     │ │
│  │             │  │              │  │                │ │
│  │ Talks to    │  │ Decides      │  │ Saves every    │ │
│  │ hardware    │  │ pass/fail    │  │ measurement    │ │
│  └─────────────┘  └──────────────┘  └────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### Each Component Explained Simply

**Campaign Orchestrator** — The "brain" that coordinates everything. It's like a project manager: it asks the planner for the next experiment, sends it through safety, tells the instruments to execute it, collects results, and feeds them back. It also tracks the budget ("you've used 14 of 30 experiments").

**Adaptive Planner (The AI)** — This is the smart part. It maintains a mathematical model of where failures might be. After each experiment, it updates its model and picks the next experiment that will teach it the most. It can ONLY propose — it cannot approve or execute anything.

**Safety Kernel** — A small, simple, deterministic piece of code that checks every proposed experiment against the test contract. "Is 3.24V within the allowed 3.0–3.6V range? Is the current limit set? Are there any forbidden combinations?" If anything is wrong, it rejects the proposal. This is intentionally kept simple and well-tested — no AI, no learning, no grey areas.

**Instrument Adapters** — Translation layers that convert generic commands ("set rail 2 to 3.24V") into the specific protocol the actual lab instrument understands (SCPI commands, serial protocols, etc.).

**Oracle / Scorer** — Checks the measurements against requirements. "Was the heartbeat gap under 500ms? Was the display latency under 120ms?" Also computes a **robustness score** — not just pass/fail, but *how close* to failing (e.g., "latency was 95ms, requirement is 120ms, so you have 25ms of margin").

**Data Recorder** — Saves absolutely everything: what was proposed, what was approved, what was commanded, what was measured, timestamps, calibration data. This creates a complete audit trail.

---

## 6. Core Concept: The Test Contract

The test contract is a YAML file that an engineer writes before any testing begins. Think of it as the **rulebook** for a testing campaign. It defines:

### What Can Be Controlled

```yaml
controls:
  oled_rail_v:          # The OLED display power
    type: continuous    # It's a voltage (not on/off)
    min: 3.00           # Never go below 3.0V
    max: 3.60           # Never go above 3.6V
    resolution: 0.01    # Smallest step: 10mV
    shutdown: 0.0       # When done, set to 0V

  red_led:              # The red LED on the board
    type: categorical   # It's either on or off
    values: [off, on]

  workload:             # What the firmware is doing
    type: categorical
    values: [idle, oled_refresh, sensor_read, wifi_tx, flash_write]
```

### What Must Never Happen (Hard Safety)

```yaml
hard_safety:
  oled_rail_v_max: 3.60         # NEVER exceed 3.6V on this rail
  channel_current_a_max: 0.20   # NEVER exceed 200mA per channel
  dut_board_temp_c_max: 60      # ABORT if board hits 60°C
  total_episode_s_max: 10       # Each test is max 10 seconds
  forbid:
    - "wifi_tx and programming_mode"  # Never do both at once
```

### What Constitutes a Failure (Requirements)

```yaml
requirements:
  heartbeat:
    rule: "gap_ms <= 500"           # Heartbeat must come every 500ms
  oled_refresh:
    rule: "frame_latency_ms <= 120" # Display must update within 120ms
  reset_count:
    rule: "reset_count == 0"        # Board must not reset during a test
```

### Campaign Settings

```yaml
campaign:
  method: adaptive_mixed_v1    # Use the adaptive AI planner
  budget_episodes: 30          # Only 30 experiments allowed
  seed: 20260903               # Random seed (for reproducibility)
  initial_design_episodes: 8   # First 8 are broad/space-filling
  repeat_on_failure: 10        # Replay each failure 10 times
```

### Why the Contract Matters

The contract is the **single source of truth**. The AI cannot invent limits. The safety system enforces contract limits. The operator reviews and approves the contract before testing starts. If the contract says "max 3.6V on the OLED rail," then 3.61V is **impossible** — not unlikely, not discouraged, but rejected by multiple independent systems.

---

## 7. Core Concept: The Safety System

Safety is the #1 priority. The system has **6 independent layers**, each of which can stop a bad experiment:

```
Layer 1: TEST CONTRACT
         ├── Human engineer wrote and reviewed the limits
         └── Faculty/safety lead approved it

Layer 2: SAFETY KERNEL (software)
         ├── Checks every proposal against the contract
         ├── Validates voltage ranges, current limits, slew rates
         ├── Checks forbidden combinations
         └── Rejects invalid proposals BEFORE they reach hardware

Layer 3: INSTRUMENT LIMITS (firmware on the power supply)
         ├── The power supply itself has OVP (overvoltage protection)
         ├── And OCP (overcurrent protection)
         └── Set BEFORE the DUT is connected, read back to confirm

Layer 4: TEST CONTROLLER WATCHDOG (separate microcontroller)
         ├── If the laptop freezes or USB disconnects
         └── This MCU automatically cuts power to the DUT

Layer 5: HARDWARE INTERLOCK (analog circuit)
         ├── A comparator/fuse circuit
         ├── Monitors current and voltage with no software involved
         └── Physically disconnects power if limits are exceeded

Layer 6: E-STOP (big red button)
         ├── Latching physical switch
         ├── Directly disconnects power
         └── Requires manual reset after being pressed
```

### The Key Principle

> **The AI proposes. It never approves or executes.**

Even if the AI's code had a bug and proposed 100V on a 3.3V rail:
- Layer 2 (safety kernel) would reject it
- Even if that failed, Layer 3 (instrument OVP) would clamp it
- Even if that failed, Layer 5 (hardware interlock) would cut power
- Even if that failed, Layer 6 (E-stop) is always available

**The result that matters: zero unsafe experiments executed. Ever.**

---

## 8. Core Concept: The Adaptive AI Planner

### How It Thinks

The planner maintains a **model** of the test space — essentially a map of "what I think will happen at each combination of conditions." After each experiment, it updates this map.

For each possible next experiment, it calculates a score based on:

```
score(x) = w₁ × probability_of_failure(x)    ← "How likely is this to fail?"
         + w₂ × uncertainty(x)                ← "How little do I know about this region?"
         + w₃ × novelty(x)                    ← "How different is this from what I've seen?"
         - w₄ × cost(x)                       ← "How expensive/time-consuming is this test?"
```

It picks the experiment with the highest score.

### The Three Stages

**Stage 1: Broad Exploration (first ~8 of 30 experiments)**

The AI doesn't start by guessing. It first casts a wide net:
- Test the nominal (normal operating) point
- Test known corners (min voltage, max voltage)
- Use Latin Hypercube Sampling (a fancy way to spread tests evenly across the space)
- Cover pairwise combinations of discrete states (red on + Wi-Fi, green on + flash write, etc.)

This gives the model a baseline understanding of the whole space.

**Stage 2: Adaptive Hunting (experiments ~9-25)**

Now the AI starts getting smart. Maybe it noticed that:
- At 3.25V on the OLED rail, the display latency was 95ms (close to the 120ms limit!)
- But only when the red LED was on
- When the red LED was off, 3.25V was totally fine

So it starts focusing its experiments around that area, varying the voltage in small steps, trying different LED combinations, to map out exactly where the failure boundary is.

**Stage 3: Confirmation & Minimization (experiments ~26-30)**

Once a failure is found:
- Replay it immediately to confirm
- Try removing conditions one at a time (does it still fail without the red LED? → No → red LED is essential)
- Narrow the voltage range (fails at 3.22V? 3.28V? but not 3.18V or 3.32V?)
- Replay the final minimal failure 10 times to measure reproducibility

### What the AI Does NOT Do

- ❌ It does NOT control instruments directly
- ❌ It does NOT decide if something is safe
- ❌ It does NOT know the hidden seeded failure rule
- ❌ It does NOT use an LLM for decision-making (an LLM is optional/advisory only)
- ❌ It does NOT claim "the device is safe" after passing tests

---

## 9. Step-by-Step: Setting Up a New Device for Testing

Here's exactly what happens when you want to test a new board:

### Step 1: Design the Fixture

Build a carrier board / wiring harness that connects the DUT to the test station.

```
Power supply Ch1 ──► [Load switch] ──► DUT main power input
Power supply Ch2 ──► [Load switch] ──► DUT OLED power
Power supply Ch3 ──► [Load switch] ──► DUT sensor power

DUT UART TX ──► Laptop USB (heartbeat + telemetry)
DUT reset pin ──► Test controller (reset monitoring)
DUT trigger input ──► Test controller (start workload)

Current shunts on each rail ──► Oscilloscope/DAQ
Temperature sensor on DUT ──► Safety interlock
```

### Step 2: Collect Specifications

Gather the actual limits from datasheets:
- ESP32-S3: recommended operating voltage 3.0–3.6V
- SSD1306 OLED: 3.0–3.6V
- BME280 sensor: 1.71–3.6V

Important: use the **recommended operating** range, never the **absolute maximum**.

### Step 3: Write the Test Contract

Create the YAML file defining controls, limits, requirements, and safety bounds. Have it reviewed by at least two team members.

### Step 4: Flash the DUT Firmware

Load the test firmware that:
- Executes named workloads on command (display refresh, sensor read, Wi-Fi TX, etc.)
- Sends heartbeat pulses every 200ms
- Reports boot reason after any reset
- Records timing markers for measurement alignment
- (In demo mode) contains the seeded failure predicate

Record the firmware's SHA256 hash.

### Step 5: Calibrate Everything

With the DUT **disconnected**, test each power supply channel:
- Command 3.0V → measure with a trusted multimeter → record the difference
- Command 3.3V → measure → record
- Command 3.6V → measure → record
- Record gain, offset, date, operator, meter ID, uncertainty

### Step 6: Safety Acceptance Tests (with Dummy Loads, NOT the DUT)

Connect resistor loads instead of the real board and verify:

| Test | Expected result |
|---|---|
| Command 0V on all channels | All outputs read 0V ✓ |
| Command nominal voltages | Outputs match within tolerance ✓ |
| Command overvoltage (above contract max) | Safety kernel REJECTS the command ✓ |
| Trigger instrument OCP | Current cuts off, alarm logged ✓ |
| Pull the USB cable | Watchdog cuts power within timeout ✓ |
| Press E-stop | All outputs immediately go to 0V ✓ |
| Inject fake overtemperature signal | Power cuts, system enters LOCKOUT ✓ |

**If any of these fail, you do NOT proceed.**

### Step 7: Connect the Real DUT

- Power off everything
- Connect the DUT through the fixture
- Apply nominal voltages in the approved power-up sequence
- Confirm heartbeat, display animation, sensor data, LED control
- Run one known-passing test manually
- Run one known-failing test (if seeded firmware) to verify the oracle detects it

### Step 8: Approve and Lock

Lock the contract-firmware-fixture tuple. If anything changes (new firmware, different wire, updated contract), the approval is invalidated and you start over from the relevant step.

---

## 10. Step-by-Step: Running a Test Campaign

Now the actual testing begins. Here's what a 30-experiment campaign looks like:

### Before Starting

The operator sees a screen like this:

```
╔══════════════════════════════════════════════════════════╗
║  ChipCheck — Campaign Setup                              ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║  DUT:        ESP32-S3 Display-Sensor Demo v1             ║
║  Serial:     DUT-A-01                                    ║
║  Firmware:   sha256: a3f8c2...                           ║
║  Contract:   sha256: 7b2e91...                           ║
║  Calibration: 2026-09-10 (2 days ago) ✓                  ║
║                                                          ║
║  Autonomous Bounds:                                      ║
║    OLED rail:    3.00V – 3.60V                           ║
║    Sensor rail:  3.00V – 3.60V                           ║
║    Max current:  200mA per channel                       ║
║    Max temp:     60°C                                    ║
║    Max episode:  10 seconds                              ║
║                                                          ║
║  Campaign:                                               ║
║    Method:    Adaptive Mixed v1                          ║
║    Budget:    30 experiments                              ║
║    Seed:      20260903                                   ║
║                                                          ║
║  E-Stop:     [■ CONNECTED]    Interlock: [■ HEALTHY]     ║
║                                                          ║
║  [ ] I have verified wiring matches the fixture diagram  ║
║  [ ] I have reviewed the test contract                   ║
║                                                          ║
║              [ ARM SYSTEM ]                              ║
╚══════════════════════════════════════════════════════════╝
```

The operator checks the boxes, presses **ARM**.

The system programs the instrument OVP/OCP limits and reads them back. Then it runs a nominal health check episode. If everything passes, the **START CAMPAIGN** button appears.

### During the Campaign

Each experiment (called an "episode") follows this exact sequence:

```
EPISODE 14 of 30
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. PLANNER PROPOSES:
   ├── OLED rail:   3.24V
   ├── Sensor rail: 3.30V
   ├── Red LED:     ON
   ├── Green LED:   OFF
   ├── Workload:    OLED refresh
   └── Reason:      HIGH_BOUNDARY_PROBABILITY (score: 0.81)
                    "Model predicts this region has ~81% chance
                     of being near a failure boundary"

2. SAFETY KERNEL VALIDATES:
   ├── 3.24V in [3.00, 3.60]?  ✓
   ├── 3.30V in [3.00, 3.60]?  ✓
   ├── No forbidden combo?      ✓
   ├── Slew rate OK?            ✓
   ├── Duration within limit?   ✓
   └── APPROVED ✓ (token: safe-ep14-xxxx)

3. EXECUTOR RUNS:
   ├── Set all rails to 0V (safe start)
   ├── Reset DUT, wait for boot
   ├── Health check: heartbeat detected ✓
   ├── Set OLED rail to 3.24V (ramping at approved slew rate)
   ├── Set Sensor rail to 3.30V
   ├── Command: Red LED ON
   ├── Command: Green LED OFF
   ├── Command: Start OLED refresh workload
   ├── Wait observation period (2 seconds)
   └── Record all measurements

4. MEASUREMENTS:
   ├── OLED rail actual:     3.238V (commanded 3.24V, Δ = -2mV ✓)
   ├── Sensor rail actual:   3.301V
   ├── OLED current:         47mA
   ├── Sensor current:       12mA
   ├── Heartbeat gaps:       [198ms, 203ms, 201ms, 197ms, 202ms] all < 500ms ✓
   ├── OLED frame latency:   251ms ← !!! EXCEEDS 120ms LIMIT !!!
   └── Reset count:          0 ✓

5. ORACLE JUDGES:
   ├── Heartbeat:        PASS  (robustness: +298ms margin)
   ├── OLED refresh:     FAIL  (robustness: -131ms, exceeded by 131ms)
   ├── Rail regulation:  PASS  (robustness: +28mV margin)
   ├── Reset count:      PASS
   └── Overall:          ██ FAIL ██

6. SHUTDOWN:
   ├── Return all rails to 0V
   ├── Confirm DUT safe
   └── Log complete episode

7. PLANNER UPDATES:
   └── "Strong failure signal at OLED=3.24V, Red=ON, Green=OFF, OLED_refresh.
        Switching to confirmation and minimization mode."
```

### What the Live UI Shows

During the campaign, the operator sees:
- A **2D scatter plot** of OLED voltage vs. robustness score, colored pass (green) / fail (red)
- A **progress bar** showing experiments used (14/30)
- **Current measurements** updating in real-time
- A **timeline** of events within the current episode
- The **planner's reasoning** for each choice
- Count of **rejected proposals** (if any were unsafe)
- A big **STOP AND DE-ENERGIZE** button

---

## 11. Step-by-Step: What Happens When a Failure is Found

When episode 14 returns a FAIL, the system doesn't just log it and move on. It enters **confirmation and minimization mode**:

### Phase 1: Immediate Replay

Re-run the exact same conditions. Did it fail again?

```
Replay 1: OLED=3.24V, Red=ON, Green=OFF, OLED_refresh → FAIL (latency: 247ms)
Replay 2: Same conditions → FAIL (latency: 253ms)
```

Good — it's reproducible, not a fluke.

### Phase 2: Remove Events One at a Time

Is every condition necessary? Remove them one by one:

```
Test: Red LED OFF (everything else same)
  → PASS (latency: 31ms)
  → Conclusion: Red LED ON is REQUIRED for failure ✓

Test: Green LED ON (everything else same)
  → PASS (latency: 29ms)
  → Conclusion: Green LED OFF is REQUIRED for failure ✓

Test: Workload = idle (everything else same)
  → PASS (latency: N/A — no refresh happening)
  → Conclusion: OLED refresh workload is REQUIRED for failure ✓

Test: Sensor rail OFF (everything else same)
  → FAIL (latency: 249ms)
  → Conclusion: Sensor rail is NOT required. Removed from reproducer. ✓
```

### Phase 3: Narrow the Voltage Range

Where exactly does the failure start and stop?

```
OLED = 3.18V, Red=ON, Green=OFF, OLED_refresh → PASS (latency: 42ms)
OLED = 3.20V → PASS (latency: 78ms)  ← getting warm
OLED = 3.22V → FAIL (latency: 189ms) ← boundary!
OLED = 3.24V → FAIL (latency: 251ms)
OLED = 3.26V → FAIL (latency: 243ms)
OLED = 3.28V → FAIL (latency: 194ms)
OLED = 3.30V → PASS (latency: 71ms)  ← boundary!
OLED = 3.32V → PASS (latency: 38ms)
```

Failure region: approximately **3.22V – 3.28V** on the OLED rail.

### Phase 4: Final Reproduction

Replay the minimized condition 10 times:

```
Minimal reproducer:
  OLED rail = 3.24V, Red LED = ON, Green LED = OFF, Workload = OLED refresh

Results: 10/10 FAIL
  Latencies: [251, 247, 253, 249, 252, 248, 251, 250, 253, 249] ms
  Mean: 250.3ms, Std: 1.9ms
```

### The Final Counterexample Report

```yaml
counterexample: CE-001
  discovery_episode: 14
  original_conditions:
    oled_rail_v: 3.24
    sensor_rail_v: 3.30
    red_led: on
    green_led: off
    workload: oled_refresh
  minimized_conditions:
    oled_rail_v: 3.24
    red_led: on
    green_led: off
    workload: oled_refresh
    # sensor_rail_v: removed (not required)
  failure_region: oled_rail_v ∈ [3.22, 3.28]
  violated_requirement: oled_refresh (frame_latency_ms <= 120)
  reproduction_rate: 10/10
  fault_type: SEEDED (intentionally programmed for demonstration)
  nearby_passing:
    - oled_rail_v: 3.18, red_led: on → PASS (42ms)
    - oled_rail_v: 3.32, red_led: on → PASS (38ms)
    - oled_rail_v: 3.24, red_led: off → PASS (31ms)
```

---

## 12. The Teacher Demo — The 8-Minute Showpiece

This is the script for the live presentation:

### Minute 0–1: "Look, everything works"

Show the board running normally. Display refreshes, sensor readings update, LEDs toggle, Wi-Fi responds. Point to the UI showing the safety bounds.

> *"Every control we use stays inside this reviewed, non-destructive test contract. The AI cannot change those limits."*

### Minute 1–2: "The search space is too large for brute force"

Show the math: 51.2 million combinations. Explain that a single-voltage sweep would be trivial — the interesting problem is **interactions** between voltage, LED state, workload, and timing.

### Minute 2–3: "Try it yourself"

Invite the teacher to pick 3–5 combinations using sliders and toggles on the UI. The safety kernel validates each choice. Most will pass. This is a fun, interactive moment.

### Minute 3–5: "Let the AI hunt"

Press **"Find a counterexample — 30 tests"**. Watch in real-time as:
- First ~8 experiments spread across the space (broad exploration)
- The AI notices rising latency near 3.25V with red LED on
- It starts focusing experiments in that region
- The map visibly clusters around the suspicious area

### Minute 5–6: "Found it"

The display freezes visibly. The UI shows:
```
Episode 14: FAIL
OLED rail: 3.24V | Red: ON | Green: OFF | OLED refresh
Frame latency: 251ms (limit: 120ms)
```

> *"This failure was intentionally seeded in the firmware for a reproducible demo. The planner did not know the rule — it found it by following the robustness gradient."*

### Minute 6–7: "Prove it and simplify it"

Show the automatic minimization: removing unnecessary conditions, narrowing the voltage range, replaying 10/10.

### Minute 7–8: "What it means and what it doesn't"

Show the evidence report. End with:

> *"We found a reproducible violation with fewer experiments than random testing on this benchmark. If no failure had been found, the honest result would be 'no counterexample found within 30 tests,' not 'the device is proven safe.'"*

---

## 13. What Makes This a Research Project

This isn't just "build a test rig." There are specific **scientific hypotheses** being tested:

| Question | Hypothesis | How we test it |
|---|---|---|
| Does adaptive search find failures faster? | 30% fewer tests than random | Run 30+ campaigns with each method, compare statistically |
| Does it work within 30 tests? | 20 percentage-point improvement over random | Measure discovery rate at budget=30 |
| Does robustness feedback help? | Yes, for continuous failures; maybe not for binary-only ones | Ablation: run with and without robustness scores |
| Can it minimize failures? | Removes ≥1 unnecessary condition in ≥70% of cases | Measure before/after complexity |
| Is the safety system airtight? | Zero unsafe executions in ≥10,000 generated test cases | Automated mutation testing of the safety kernel |
| Does it transfer to a second device? | Yes, with only a new contract/fixture | Test on STM32 without changing core code |

### The Benchmarks

There are 10 pre-defined benchmark scenarios (B1–B10):

| ID | What it tests | Purpose |
|---|---|---|
| B1 | Simple voltage threshold | Sanity check — even binary search should find this |
| B2 | Narrow non-monotonic interval | Shows why binary search fails (failure is in a valley, not at an edge) |
| B3 | Conditional island (voltage + LED state) | The core demo scenario |
| B4 | 3-way interaction | Mixed continuous/discrete search |
| B5 | Timed sequence | Temporal ordering matters |
| B6 | Multiple disconnected failure regions | Tests diversity |
| B7 | Intermittent / probabilistic | Tests reproduction rate estimation |
| B8 | No failure exists | Tests honest "not found" reporting |
| B9 | Natural power transient | Real emergent failure (not seeded) |
| B10 | Cross-unit comparison | Manufacturing variation |

### What's Compared Against

The adaptive method is compared against these baselines:

1. **Fixed corners** — manually chosen worst-case points (what most engineers do today)
2. **Uniform random** — pick legal experiments randomly
3. **Grid sweep** — systematic grid (only works for low dimensions)
4. **Latin Hypercube** — space-filling statistical design
5. **t-way covering arrays** — ensure every pair/triple of discrete states is tested
6. **Bayesian optimization** — standard GP-based optimization
7. **Active level-set estimation** — boundary-finding algorithm

The adaptive method must beat **at least random and fixed corners** to be considered successful. If grid or t-way testing wins at this scale, that's reported honestly.

---

## 14. What This Project Does NOT Do

This is just as important as what it does:

| Claim we DO NOT make | Why |
|---|---|
| "The device is proven safe" | 30 passing tests ≠ proof. We say "no counterexample found within budget" |
| "This replaces certification" | We're a research POC, not an accredited test lab |
| "AI controls the hardware safely" | **Deterministic safety** controls the hardware. AI just suggests experiments |
| "Works with any device" | Each device needs a custom fixture and contract |
| "Finds all bugs" | Finds bugs within the declared test space. Untested regions remain unknown |
| "The LLM is essential" | The system works without any LLM. An LLM is optional for drafting contracts |
| "Destructive testing" | We stay within recommended operating conditions. No glitching, no overvoltage abuse |
| "Production-ready" | This is a 24-week proof-of-concept research project |

---

## 15. Glossary

| Term | Plain English |
|---|---|
| **DUT** | Device Under Test — the board you're testing |
| **Episode** | One complete experiment: reset → set conditions → measure → judge → shutdown |
| **Campaign** | A set of episodes with a fixed budget (e.g., 30 experiments) |
| **Test Contract** | The YAML rulebook defining what's allowed and what constitutes failure |
| **Oracle** | The judge — checks if measurements meet requirements |
| **Robustness Score** | How much safety margin exists. Positive = passing, zero = boundary, negative = failing |
| **Safety Kernel** | The software guard that blocks unsafe experiments |
| **Counterexample** | A proven, reproducible set of conditions that cause a failure |
| **Seeded Fault** | A bug intentionally programmed into firmware for testing purposes (disclosed) |
| **Natural Fault** | A real bug discovered from actual electrical interactions |
| **Falsification** | Finding a concrete example that disproves a claim ("board never resets" → here's a reset) |
| **Minimization** | Simplifying a failure to its essential trigger by removing unnecessary conditions |
| **HIL** | Hardware-In-the-Loop — testing with real hardware in an automated loop |
| **OVP/OCP** | Overvoltage/Overcurrent Protection — hardware safety features on power supplies |
| **Slew Rate** | How fast voltage is allowed to change (e.g., 0.5V per second max) |
| **E-stop** | Emergency stop — big red button that kills power immediately |
| **Acquisition Function** | The AI's scoring formula for ranking candidate experiments |
| **Space-filling** | Spreading initial tests evenly across the whole space (like Latin Hypercube) |
| **t-way coverage** | Ensuring every combination of t discrete variables is tested at least once |
