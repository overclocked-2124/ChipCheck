<p align="center">
  <h1 align="center">⚡ ChipCheck</h1>
  <p align="center">
    <strong>Adaptive Hardware Fuzzing for Embedded Systems</strong>
  </p>
  <p align="center">
    Find hidden bugs in embedded devices by intelligently choosing which experiments to run.
  </p>
  <p align="center">
    <a href="./docs/WALKTHROUGH.md">Walkthrough</a> •
    <a href="./docs/SIMPLIFIED-PLAN.md">Implementation Plan</a> •
    <a href="./docs/SOLUTIONS.md">Design Decisions</a> •
    <a href="./docs/adaptive-hardware-fuzzing-prd.md">Full PRD</a>
  </p>
</p>

---

## What is this?

ChipCheck is a **test station** that finds rare interaction bugs in embedded devices (ESP32, STM32) — bugs that only appear when multiple conditions collide (specific voltage + specific state + specific workload).

Instead of testing millions of combinations by brute force, ChipCheck uses **adaptive search** (via [Optuna](https://optuna.org/)) to pick the most informative experiments, find failures faster, and automatically reproduce and minimize them.

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Optuna     │     │   Safety     │     │   Physical   │
│  picks next  │────▶│   kernel     │────▶│   hardware   │
│  experiment  │     │  validates   │     │   executes   │
└──────────────┘     └──────────────┘     └──────┬───────┘
       ▲                                         │
       │              ┌──────────────┐           │
       └──────────────│   Oracle     │◀──────────┘
                      │   scores     │
                      │   result     │
                      └──────────────┘
```

## Key Features

- 🔍 **Adaptive search** — Optuna's TPE sampler focuses experiments on suspicious regions
- 🛡️ **Safety-first** — deterministic safety kernel + hardware limits + fuse + manual switch
- 📊 **Fair comparison** — same budget, same bench: TPE vs. Random vs. Grid
- 🔁 **Auto-reproduce** — failures are replayed 5× and minimized to essential conditions
- 📋 **Honest reporting** — "no counterexample found" ≠ "device is safe"

## Quick Start (Once Built)

```bash
# Install dependencies
pip install optuna fastapi pyserial pyyaml plotly scipy

# Run a campaign
python chipcheck/run_campaign.py --contract contracts/esp32_demo.yaml --method tpe --budget 50

# View results
optuna-dashboard sqlite:///campaigns/latest.db
```

## Hardware Setup (~₹3,300)

```
Laptop (USB) ──► RP2040 Pico (instrument controller)
                    ├── DAC → LDO → OLED power rail
                    ├── DAC → LDO → Sensor power rail
                    ├── ADC ← voltage/current readback
                    └── Watchdog (cuts power if host disconnects)

Laptop (USB) ──► ESP32-S3 DevKitC (device under test)
                    ├── OLED display (on external rail)
                    ├── BME280 sensor (on external rail)
                    ├── Red + Green LEDs
                    ├── Heartbeat output
                    └── UART telemetry
```

## Project Structure

```
ChipCheck/
├── README.md
├── docs/
│   ├── WALKTHROUGH.md              # Detailed plain-English explanation
│   ├── SIMPLIFIED-PLAN.md          # 12-week implementation plan
│   ├── SOLUTIONS.md                # Design decisions & issue mitigations
│   └── adaptive-hardware-fuzzing-prd.md  # Original full PRD (reference)
├── chipcheck/                      # Python: orchestrator, safety, scoring
├── firmware/
│   ├── esp32_dut/                  # ESP32 workload + heartbeat + faults
│   └── rp2040_controller/         # RP2040 DAC/ADC/watchdog firmware
├── contracts/                      # YAML test contracts
├── campaigns/                      # SQLite databases (Optuna studies)
└── reports/                        # Generated evidence reports
```

## Research Question

> Given a mixed continuous/discrete test space and a fixed experiment budget, does adaptive search (TPE) find embedded device failures in fewer physical experiments than random or grid testing?

## Documentation

| Document | What it covers |
|---|---|
| [**Walkthrough**](./docs/WALKTHROUGH.md) | Plain-English explanation of the entire project — problem, users, architecture, step-by-step usage |
| [**Simplified Plan**](./docs/SIMPLIFIED-PLAN.md) | The practical 12-week build plan with weekly tasks and checkpoints |
| [**Solutions**](./docs/SOLUTIONS.md) | Every identified risk/issue and its practical mitigation |
| [**Full PRD**](./docs/adaptive-hardware-fuzzing-prd.md) | The complete research-grade product requirements document (reference) |

## Team

| Role | Focus |
|---|---|
| Research Lead | Contract spec, research questions, report, demo |
| Hardware | RP2040 firmware, wiring, DAC/LDO/ADC, calibration |
| Embedded | ESP32 firmware, workloads, heartbeat, seeded faults |
| Algorithm | Optuna integration, simulation, statistics |
| UI + Platform | Web dashboard, campaign runner, report generator |

## License

TBD

---

<p align="center">
  <sub>Final-year project • SDG 9: Industry, Innovation and Infrastructure</sub>
</p>
