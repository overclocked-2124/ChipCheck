> **Status:** Methodology and alternative implementation proposal. The ActiveQual HLD documents define current service ownership. For the implemented architecture, Decision proposes candidates; Backend and Controller own approval and execution. Values and hardware limits in this document are examples until reviewed for the selected fixture.
>
> **Superseded points (2026-11-05):**
> - The plain-text serial protocol lacks the framing, checksums, duplicate detection, and explicit rejection HLD 02 §8.3 requires; see HLD 05 §9.
> - A fuse and a toggle switch are not the safety baseline; HLD 02 §13 keeps the watchdog, hardware cutoff, and E-stop.
> - The raw-difference scorer is replaced by HLD 04 §13 (normalized headroom for the planner, guard-banded verdict for the outcome).
> - Fault A is a cliff, not a gradient: inside its window the added delay is already about 100 ms at the edges, so latency jumps from about 31 ms to over 130 ms with no warning outside. HLD 06 §5 defines the benchmark profiles.
> - The 2.80–3.60 V rail range is below the ESP32-S3 and possibly the SSD1306 recommended supply; limits come from the selected parts (HLD 02 §19.1).
> - Optuna storage is not the record of campaigns; the Backend database is (HLD 08).
> - Replays and minimization follow the verification phase in HLD 04 §14 and HLD 06 §7.

# ChipCheck — Simplified Implementation Plan

> The practical, actually-buildable version. 12 weeks to a working demo.

---

## What We're Actually Building

A test station that:
1. Controls 2 voltage rails and 4 firmware states on an ESP32 board
2. Uses **Optuna** (off-the-shelf ML library) to pick informative experiments
3. Finds seeded bugs faster than random testing
4. Reproduces and minimizes discovered failures
5. Shows everything on a live web dashboard

**Total hardware cost: ~₹5,000**
**Total custom ML code: ~30 lines** (Optuna does the heavy lifting)

---

## Architecture — The Simple Version

```
┌──────────────────────────────────────────────────────────┐
│                    HOST LAPTOP                            │
│                                                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │
│  │   Optuna    │  │   Safety    │  │   Web UI        │  │
│  │   (TPE /    │  │   Kernel    │  │   (FastAPI +    │  │
│  │   Random /  │  │   (50 lines │  │   Optuna Dash   │  │
│  │   Grid)     │  │   of Python)│  │   + status)     │  │
│  └──────┬──────┘  └──────┬──────┘  └─────────────────┘  │
│         │                │                               │
│         ▼                ▼                               │
│  ┌────────────────────────────────────────────────────┐  │
│  │              Campaign Orchestrator                  │  │
│  │              (Python, ~300 lines)                   │  │
│  │  - Asks Optuna for next trial                      │  │
│  │  - Validates through safety kernel                 │  │
│  │  - Sends commands to RP2040                        │  │
│  │  - Reads measurements                             │  │
│  │  - Scores pass/fail + robustness                   │  │
│  │  - Reports result back to Optuna                   │  │
│  └──────────────┬────────────────────────┬────────────┘  │
│           USB Serial                USB Serial           │
└──────────┬──────────────────────────┬────────────────────┘
           │                          │
           ▼                          ▼
┌──────────────────┐      ┌──────────────────────┐
│   RP2040 Pico    │      │   ESP32-S3 DevKitC   │
│   (Instrument    │      │   (Device Under      │
│    Controller)   │      │    Test)              │
│                  │      │                       │
│  • 2× MCP4725   │ wire │  • SSD1306 OLED       │
│    DAC modules   │──────│    (on rail 1)        │
│  • 2× AMS1117   │      │  • BME280 sensor      │
│    LDO modules   │      │    (on rail 2)        │
│  • 1× ADS1115   │      │  • Red + Green LEDs   │
│    ADC module    │      │  • Heartbeat output   │
│  • Load switches │      │  • UART telemetry     │
│  • Watchdog      │      │  • Seeded fault logic  │
│  • Fuse (500mA)  │      │                       │
└──────────────────┘      └──────────────────────┘
```

---

## Hardware — Bill of Materials

| Component | Qty | Price (₹) | Purpose |
|---|---|---|---|
| ESP32-S3 DevKitC | 1 | 800 | Device under test |
| Raspberry Pi Pico (RP2040) | 1 | 400 | Instrument controller + watchdog |
| SSD1306 OLED 0.96" I²C | 1 | 200 | Display peripheral (on external rail) |
| BME280 I²C module | 1 | 300 | Sensor peripheral (on external rail) |
| MCP4725 DAC module | 2 | 400 | Voltage control (one per rail) |
| AMS1117-ADJ or LM317 LDO | 2 | 100 | Regulated output from DAC reference |
| ADS1115 16-bit ADC module | 1 | 300 | Accurate voltage/current readback |
| 5mm Red LED + 330Ω resistor | 1+1 | 10 | Discrete state control |
| 5mm Green LED + 330Ω resistor | 1+1 | 10 | Discrete state control |
| 500mA polyfuse (resettable) | 2 | 40 | Overcurrent protection |
| Current shunt resistors (0.5Ω) | 2 | 20 | Current measurement via ADC |
| Toggle switch (SPST) | 1 | 50 | Manual power disconnect |
| Breadboard (full size) | 2 | 300 | Assembly |
| Jumper wire kit | 1 | 200 | Wiring |
| USB cables (micro + type-C) | 3 | 300 | Connections |
| 5V 2A USB power adapter | 1 | 200 | RP2040 power + rail source |
| **TOTAL** | | **~₹3,300** | |

> **Note:** If the lab has a bench power supply with USB/serial, use it for one rail and the DAC+LDO for the other. This gives better accuracy with less work.

---

## Software — Stack

| Component | Technology | Why |
|---|---|---|
| Adaptive planner | **Optuna** (TPE, Random, Grid, CMA-ES) | Handles mixed spaces natively; no custom ML code |
| Backend | **FastAPI** (Python) | Simple, async, modern |
| Frontend | **HTML/JS + Optuna Dashboard** | Optuna dashboard is free; add a custom status page |
| Data storage | **SQLite** (via Optuna's built-in storage) | Zero setup |
| RP2040 communication | **pyserial** | Simple serial protocol |
| ESP32 communication | **pyserial** | UART telemetry |
| Visualization | **Plotly** (charts) + Optuna's built-in plots | Publication-ready graphs |
| Analysis | **pandas + scipy** | Statistical comparison |

---

## The Serial Protocol (RP2040 ↔ Host)

Dead simple text protocol over USB serial:

```
# Host → RP2040 (commands)
SET OLED 3.24          → Set OLED rail to 3.24V
SET SENSOR 3.30        → Set sensor rail to 3.30V
READ ALL               → Read all voltages and currents
ENABLE OLED            → Turn on OLED rail load switch
DISABLE OLED           → Turn off OLED rail load switch
SHUTDOWN               → All outputs to 0V, all switches off
PING                   → Watchdog keepalive
STATUS                 → Report current state

# RP2040 → Host (responses)
OK OLED 3.238          → Acknowledged, actual voltage measured
OK SENSOR 3.301        → Acknowledged, actual voltage measured
DATA OLED_V=3.238 OLED_I=0.047 SENSOR_V=3.301 SENSOR_I=0.012
OK SHUTDOWN
PONG
STATUS ARMED OLED=3.238 SENSOR=3.301

# RP2040 → Host (safety events)
ALERT OVERCURRENT OLED 0.215    → Current exceeded limit
ALERT WATCHDOG_TIMEOUT          → Host didn't ping in 3 seconds
ALERT FUSE_BLOWN                → Polyfuse tripped
```

---

## The Serial Protocol (ESP32 DUT ↔ Host)

```
# Host → ESP32 (workload commands)
WORKLOAD OLED_REFRESH      → Start OLED refresh task
WORKLOAD SENSOR_READ       → Start sensor read task
WORKLOAD FLASH_WRITE       → Start flash write task
WORKLOAD IDLE              → Stop all workloads
LED RED ON                 → Turn red LED on
LED RED OFF                → Turn red LED off
LED GREEN ON               → Turn green LED on
LED GREEN OFF              → Turn green LED off
RESET                      → Software reset
REPORT                     → Send current status

# ESP32 → Host (telemetry, sent every 200ms)
HB 1042                            → Heartbeat with uptime_ms
OLED_LAT 31                        → OLED frame latency in ms
SENSOR_VAL 25.3 1013.2 45.1        → Temp, pressure, humidity
BOOT_REASON POWER_ON               → After reset
WORKLOAD_ACK OLED_REFRESH          → Workload started
```

---

## Test Contract — Simplified

```yaml
# contract.yaml — the only config file you need
contract_version: 1
dut:
  name: "ESP32-S3 OLED+Sensor Demo"
  firmware_hash: "sha256:abc123..."

controls:
  oled_rail_v:
    min: 2.80
    max: 3.60
    step: 0.01
  sensor_rail_v:
    min: 2.80
    max: 3.60
    step: 0.01
  red_led: [on, off]
  green_led: [on, off]
  workload: [idle, oled_refresh, sensor_read, flash_write, cpu_stress]

safety:
  max_voltage: 3.60
  max_current_ma: 200
  max_episode_seconds: 10
  forbidden:
    - "oled_rail_v > 3.60"
    - "sensor_rail_v > 3.60"

requirements:
  heartbeat_gap_ms: 500     # must not exceed
  oled_latency_ms: 120      # must not exceed
  reset_count: 0             # must equal

campaign:
  budget: 50
  seed: 42
  warmup_trials: 10          # random trials before TPE kicks in
  replays_on_failure: 5      # how many times to replay a failure
```

---

## Seeded Faults — Three Types

### Fault A: Gradient-Guided (for the demo)
```c
// In ESP32 firmware, #ifdef FAULT_A
if (oled_rail_mv >= 3200 && oled_rail_mv <= 3300 &&
    red_led_on && !green_led_on &&
    workload == OLED_REFRESH) {
    // Gradual: latency increases as voltage approaches center
    int distance = abs(oled_rail_mv - 3250);
    int extra_delay = map(distance, 0, 100, 200, 0);
    delay_ms(extra_delay);  // makes latency exceed 120ms near center
}
```

### Fault B: Binary Island (no gradient, harder)
```c
// In ESP32 firmware, #ifdef FAULT_B
if (oled_rail_mv >= 3150 && oled_rail_mv <= 3180 &&
    sensor_rail_mv >= 3400 &&
    workload == SENSOR_READ) {
    trigger_software_reset();  // instant reset, no warning
}
```

### Fault C: No Fault (honest negative)
```c
// In ESP32 firmware, #ifdef FAULT_C
// Nothing. No seeded fault. Everything works within spec.
// Tests that the system correctly reports "no counterexample found."
```

---

## How an Episode Runs — The Code

```python
# core loop — this is basically the whole project
import optuna
import serial
import yaml
import time

def load_contract(path):
    with open(path) as f:
        return yaml.safe_load(f)

def safety_check(contract, params):
    """50 lines of deterministic validation."""
    if params["oled_rail_v"] > contract["safety"]["max_voltage"]:
        return False, "OLED voltage exceeds maximum"
    if params["oled_rail_v"] < contract["controls"]["oled_rail_v"]["min"]:
        return False, "OLED voltage below minimum"
    # ... check all constraints ...
    return True, "approved"

def execute_episode(rp2040, esp32, params, contract):
    """Execute one physical experiment."""
    # 1. Set rails
    rp2040.write(f"SET OLED {params['oled_rail_v']:.2f}\n".encode())
    response = rp2040.readline()  # "OK OLED 3.238"
    actual_oled_v = float(response.split()[-1])

    rp2040.write(f"SET SENSOR {params['sensor_rail_v']:.2f}\n".encode())
    response = rp2040.readline()
    actual_sensor_v = float(response.split()[-1])

    # 2. Set discrete states
    esp32.write(f"LED RED {params['red_led'].upper()}\n".encode())
    esp32.write(f"LED GREEN {params['green_led'].upper()}\n".encode())

    # 3. Start workload
    esp32.write(f"WORKLOAD {params['workload'].upper()}\n".encode())

    # 4. Observe for episode duration
    start = time.time()
    heartbeats = []
    oled_latencies = []
    resets = 0

    while time.time() - start < contract["safety"]["max_episode_seconds"]:
        if esp32.in_waiting:
            line = esp32.readline().decode().strip()
            if line.startswith("HB"):
                heartbeats.append(int(line.split()[1]))
            elif line.startswith("OLED_LAT"):
                oled_latencies.append(int(line.split()[1]))
            elif line.startswith("BOOT_REASON"):
                resets += 1

    # 5. Read final measurements
    rp2040.write(b"READ ALL\n")
    measurements = rp2040.readline()

    # 6. Shutdown
    rp2040.write(b"SHUTDOWN\n")
    esp32.write(b"WORKLOAD IDLE\n")

    # 7. Score
    return score_episode(contract, heartbeats, oled_latencies, resets,
                         actual_oled_v, actual_sensor_v)

def score_episode(contract, heartbeats, oled_latencies, resets, oled_v, sensor_v):
    """Oracle + robustness scoring."""
    scores = []

    # Heartbeat requirement
    if len(heartbeats) >= 2:
        max_gap = max(heartbeats[i+1] - heartbeats[i]
                      for i in range(len(heartbeats)-1))
        scores.append(contract["requirements"]["heartbeat_gap_ms"] - max_gap)
    else:
        scores.append(-1000)  # no heartbeat = very bad

    # OLED latency requirement
    if oled_latencies:
        max_lat = max(oled_latencies)
        scores.append(contract["requirements"]["oled_latency_ms"] - max_lat)

    # Reset requirement
    scores.append(-1000 * resets)  # any reset is a failure

    # Robustness = minimum margin (negative = failure)
    robustness = min(scores) if scores else -1000
    passed = robustness >= 0

    return {"robustness": robustness, "passed": passed,
            "max_oled_latency": max(oled_latencies) if oled_latencies else None,
            "resets": resets}

def run_campaign(contract_path, sampler_name="tpe"):
    contract = load_contract(contract_path)

    # Pick sampler
    if sampler_name == "tpe":
        sampler = optuna.samplers.TPESampler(
            n_startup_trials=contract["campaign"]["warmup_trials"])
    elif sampler_name == "random":
        sampler = optuna.samplers.RandomSampler()
    elif sampler_name == "grid":
        # define grid search space
        search_space = {
            "oled_rail_v": [round(v, 2) for v in
                           np.arange(2.8, 3.61, 0.1)],
            "sensor_rail_v": [3.3],  # fixed for grid
            "red_led": ["on", "off"],
            "green_led": ["on", "off"],
            "workload": ["idle", "oled_refresh", "sensor_read",
                         "flash_write", "cpu_stress"],
        }
        sampler = optuna.samplers.GridSampler(search_space)

    study = optuna.create_study(
        direction="minimize",  # minimize robustness → find failures
        sampler=sampler,
        storage=f"sqlite:///campaigns/{sampler_name}_{int(time.time())}.db",
    )

    rp2040 = serial.Serial("COM3", 115200, timeout=2)
    esp32 = serial.Serial("COM4", 115200, timeout=2)

    def objective(trial):
        params = {
            "oled_rail_v": trial.suggest_float("oled_rail_v",
                contract["controls"]["oled_rail_v"]["min"],
                contract["controls"]["oled_rail_v"]["max"],
                step=contract["controls"]["oled_rail_v"]["step"]),
            "sensor_rail_v": trial.suggest_float("sensor_rail_v",
                contract["controls"]["sensor_rail_v"]["min"],
                contract["controls"]["sensor_rail_v"]["max"],
                step=contract["controls"]["sensor_rail_v"]["step"]),
            "red_led": trial.suggest_categorical("red_led",
                contract["controls"]["red_led"]),
            "green_led": trial.suggest_categorical("green_led",
                contract["controls"]["green_led"]),
            "workload": trial.suggest_categorical("workload",
                contract["controls"]["workload"]),
        }

        # Safety check
        ok, reason = safety_check(contract, params)
        if not ok:
            trial.set_user_attr("rejected_reason", reason)
            raise optuna.TrialPruned()

        # Execute
        result = execute_episode(rp2040, esp32, params, contract)

        # Log everything
        trial.set_user_attr("passed", result["passed"])
        trial.set_user_attr("max_oled_latency", result["max_oled_latency"])
        trial.set_user_attr("resets", result["resets"])

        # If failure found, replay for confirmation
        if not result["passed"]:
            print(f"⚠️  FAILURE at trial {trial.number}!")
            replay_results = []
            for i in range(contract["campaign"]["replays_on_failure"]):
                r = execute_episode(rp2040, esp32, params, contract)
                replay_results.append(r["passed"])
            repro_rate = 1 - (sum(replay_results) /
                              len(replay_results))
            trial.set_user_attr("repro_rate", repro_rate)
            print(f"   Reproduction rate: {repro_rate:.0%}")

        return result["robustness"]

    study.optimize(objective, n_trials=contract["campaign"]["budget"])
    rp2040.close()
    esp32.close()

    return study
```

That's... essentially the entire project in one file. Everything else is firmware, wiring, and reporting.

---

## 12-Week Timeline

### Phase 1: Foundations (Weeks 1–3)

| Week | Task | Owner | Deliverable |
|---|---|---|---|
| 1 | Set up repo, Optuna hello-world, simulator function | All | Optuna finding a "failure" in a Python function |
| 1 | Order components (₹3,300 total) | Hardware person | Parts ordered |
| 2 | RP2040 firmware: serial protocol + DAC + ADC | Hardware person | RP2040 sets voltage and reads it back |
| 2 | Python: safety kernel + contract loader | Software person | Contract YAML loads and validates |
| 2 | ESP32 firmware: heartbeat + LED + workload commands | Embedded person | ESP32 responds to serial commands |
| 3 | Wire up breadboard: RP2040 → DACs → LDOs → ESP32 peripherals | Hardware person | Voltage controllable from laptop |
| 3 | Integrate: Optuna → safety → RP2040 → ESP32 → score | Software person | First end-to-end episode works |

**Week 3 checkpoint: Can we set a voltage, run a workload, and get a robustness score?**
If NO → fix hardware/firmware. If YES → proceed.

### Phase 2: Core Features (Weeks 4–6)

| Week | Task | Owner | Deliverable |
|---|---|---|---|
| 4 | ESP32: implement seeded Fault A (gradient) | Embedded person | Fault triggers at known conditions |
| 4 | Python: full campaign loop with Optuna storage | Software person | 50-episode campaign runs to completion |
| 4 | Calibration routine: auto-calibrate at campaign start | Hardware person | Gain/offset stored per campaign |
| 5 | Run first real adaptive campaign → find Fault A | All | TPE finds the seeded fault! |
| 5 | ESP32: implement Fault B (binary) and Fault C (no fault) | Embedded person | Multiple benchmark configs |
| 5 | Python: minimizer (replay with conditions removed) | Software person | Minimized counterexample produced |
| 6 | Run TPE vs. Random vs. Grid on all 3 fault types | All | First comparison data |
| 6 | Fix issues discovered during testing | All | Stable system |

**Week 6 checkpoint: Does TPE beat Random on Fault A?**
If NO → debug model/scoring. If YES → you have a working demo.

### Phase 3: Polish & Evaluate (Weeks 7–9)

| Week | Task | Owner | Deliverable |
|---|---|---|---|
| 7 | Web UI: live status page + Optuna dashboard integration | UI person | Live campaign view in browser |
| 7 | Python: evidence report generator (Markdown) | Software person | Auto-generated report per campaign |
| 8 | Run 10+ campaigns per method for statistical comparison | All | Comparison table with confidence intervals |
| 8 | Simulation layer: run 100+ campaigns on synthetic functions | Algorithm person | Statistically significant results |
| 9 | Second firmware config (different fault geometry) on same board | Embedded person | "Transfer" demonstration |
| 9 | Prepare demo script and rehearse | All | 8-minute demo runs smoothly |

**Week 9 checkpoint: Is the demo reliable across 10+ random seeds?**

### Phase 4: Documentation & Defense (Weeks 10–12)

| Week | Task | Owner | Deliverable |
|---|---|---|---|
| 10 | Freeze code and benchmarks | All | Tagged release |
| 10 | Final evaluation runs (pre-registered) | Algorithm person | All raw data archived |
| 11 | Write report: results, analysis, limitations | Research lead | Draft report |
| 11 | Record demo video as backup | All | Video file |
| 12 | Defense preparation, slides, Q&A practice | All | Ready to present |

---

## Team Split (5 People)

| Person | Primary Role | Key Deliverables |
|---|---|---|
| **A** | Research Lead + Integration | Contract spec, pre-registration, report, demo script |
| **B** | Hardware | RP2040 firmware, wiring, DAC/LDO/ADC setup, calibration |
| **C** | Embedded (ESP32) | DUT firmware, workloads, heartbeat, seeded faults |
| **D** | Algorithm + Analysis | Optuna integration, simulation, statistics, comparison tables |
| **E** | UI + Platform | Web dashboard, campaign runner, report generator, data storage |

**Rule:** Everyone can assemble the breadboard and run a campaign. No single point of failure.

---

## 4 Benchmarks (not 10)

| ID | Fault Type | What It Proves |
|---|---|---|
| B1 | Gradient-guided (OLED latency rises near failure) | TPE can follow a gradient signal |
| B2 | Binary island (instant reset, no warning) | How methods handle cliff-edge failures |
| B3 | No fault exists | System correctly reports "not found" |
| B4 | Different fault geometry (second firmware config) | System works with different contracts |

---

## Success Criteria

The project succeeds if:

1. ✅ The system runs a 50-episode campaign on real hardware without crashing
2. ✅ TPE finds seeded Fault A within 50 episodes in ≥80% of campaigns
3. ✅ TPE finds Fault A with fewer episodes than Random (on average, across 10+ campaigns)
4. ✅ The minimizer reduces the counterexample (removes ≥1 unnecessary condition)
5. ✅ Zero unsafe experiments executed (safety kernel rejects all out-of-bounds proposals)
6. ✅ Fault C (no fault) correctly produces "no counterexample found" report
7. ✅ A faculty member can understand the demo without reading the code
8. ✅ All raw data is published

It's okay if:
- TPE barely beats Random on Fault B (binary) — that's an honest negative result
- Grid search is competitive on this specific scale — report it
- Some episodes fail due to measurement noise — log them, report the rate

---

## What We Explicitly Defer to "Future Work"

- Custom PCB / professional fixture
- Wi-Fi and RF workloads
- Temperature control
- Multiple DUT designs (STM32)
- Custom GP/kernel implementation
- 10-benchmark suite
- LLM-assisted contract drafting
- Production deployment
- Formal safety certification
- Custom hardware interlock circuit
