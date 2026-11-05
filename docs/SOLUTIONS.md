> **Status:** Methodology and alternative implementation proposal. The ActiveQual HLD documents define current service ownership. For the implemented architecture, Decision proposes candidates; Backend and Controller own approval and execution. Values and hardware limits in this document are examples until reviewed for the selected fixture.
>
> **Superseded points (2026-11-05):**
> - Issue 11: level translation is still needed. When a peripheral rail is below the ESP32's 3.3 V signal level, signals can back-power the peripheral (HLD 02 §7).
> - Issues 18–20: the ₹70 fuse-and-switch safety set is not the baseline; HLD 02 §13 keeps the watchdog, cutoff, and E-stop.
> - Issue 23: the HLD set remains the structure (HLD 00); this document is a proposal.
> - Issue 17: HLD 06 recommends a log-rank test on episodes to first failure as the primary metric, because it had more statistical power than discovery rate in every simulated comparison.
> - Issue 4 is only partly supported: in simulation GP-BO beat TPE on two benchmarks and lost on one, so both are kept as adaptive methods (HLD 06 §3).

# ChipCheck — Solutions to Every Identified Issue

> For each problem, a **practical fix** that reduces scope, effort, or complexity while keeping the project credible.

---

## 🔴 Issue 1: Search space might be too small for AI

**Problem:** With 3 rails × 20 steps × 4 binary states = 128K combinations, a grid could finish in hours.

**Solution: Add temporal sequencing to make the space genuinely large.**

Instead of just "set conditions → observe," test **event sequences with timing**:

```
set_rails → [workload A] → wait d1 → [workload B] → wait d2 → [workload C] → observe
```

With 5 workloads, 3 positions, 5 delay values each:
```
60 voltage combos × 16 discrete states × P(5,3) orderings × 5² delays
= 60 × 16 × 60 × 25 = 1,440,000 combinations
```

That's legitimately too large for brute force. Also, **frame the research question honestly**: "At what scale does adaptive search start outperforming grid?" is itself a valid contribution.

**Effort: LOW** — just add delay/ordering parameters to the test contract.

---

## 🔴 Issue 2: Seeded fault designed to make AI look good

**Problem:** The gradient signal leading to the seeded fault is basically a cheat code for the optimizer.

**Solution: Include 3 fault types, not just 1.**

| Fault | Type | What it tests |
|---|---|---|
| Fault A | Gradient-guided (original) | "Can the AI follow a robustness signal?" |
| Fault B | Binary island (no gradient) | "Can the AI find a fault with no signal?" |
| Fault C | No fault exists | "Does the AI correctly report 'not found'?" |

In the demo, show all three and be upfront:

> *"Fault A has a gradient — the AI exploits it. Fault B has no gradient — the AI is only slightly better than random. That's the honest boundary of this approach."*

This is **more impressive** than pretending the AI magically works on everything.

**Effort: LOW** — just add 2 more `#ifdef` blocks in the firmware.

---

## 🟠 Issue 3: Statistical significance hard with physical experiments

**Problem:** 30 campaigns × 10 benchmarks × 9 methods = 81,000 physical experiments.

**Solution: Use a simulation layer for statistics, hardware for credibility.**

```
Layer 1: Simulation (unlimited budget)
  → Run 1000+ campaigns per method per benchmark
  → Get statistically significant comparisons
  → This is where you prove/disprove hypotheses

Layer 2: Physical (limited budget)
  → Run 5–10 campaigns per method on 2–3 benchmarks
  → Confirm that simulation results transfer to real hardware
  → This is where you show it's not just theoretical
```

The simulation uses synthetic functions that mimic the seeded firmware behavior. The physical runs validate that the simulation is realistic.

**Effort: MEDIUM** — need to build a simulator, but it's just Python functions.

---

## 🟠 Issue 4: GP doesn't handle mixed spaces well

**Problem:** Gaussian Processes need custom kernels for categorical/conditional variables.

**Solution: Don't use GPs. Use Optuna's TPE sampler.**

[Optuna](https://optuna.org/) already implements:
- **TPE (Tree-structured Parzen Estimator)** — natively handles mixed continuous/categorical/conditional spaces
- **Random sampler** — baseline comparison
- **Grid sampler** — another baseline
- **CMA-ES sampler** — continuous optimization baseline
- **Built-in dashboard** — free visualization
- **Study storage** — SQLite persistence
- **Trial history** — complete audit trail

The entire adaptive planner becomes ~30 lines:

```python
import optuna

def objective(trial):
    oled_v = trial.suggest_float("oled_v", 3.0, 3.6)
    red_led = trial.suggest_categorical("red_led", ["on", "off"])
    green_led = trial.suggest_categorical("green_led", ["on", "off"])
    workload = trial.suggest_categorical("workload",
        ["idle", "oled_refresh", "sensor_read", "flash_write"])

    if not safety_kernel.validate(oled_v, red_led, green_led, workload):
        raise optuna.TrialPruned()

    result = execute_physical_episode(oled_v, red_led, green_led, workload)
    return result.robustness_score  # Optuna minimizes this

# Adaptive (TPE)
study_adaptive = optuna.create_study(sampler=optuna.samplers.TPESampler())
study_adaptive.optimize(objective, n_trials=50)

# Random baseline
study_random = optuna.create_study(sampler=optuna.samplers.RandomSampler())
study_random.optimize(objective, n_trials=50)
```

You just **eliminated weeks of ML implementation** and got a better, more tested algorithm.

**Effort: VERY LOW** — `pip install optuna` and 30 lines of code.

---

## 🟠 Issue 5: 30 data points isn't enough

**Problem:** Too few experiments for any model to learn meaningfully.

**Solution: Increase budget to 50–100. Episodes are cheap.**

At 5 seconds per episode, 100 episodes = ~10 minutes. There's no reason to limit to 30 unless you're trying to make a theoretical point. For practical use:

- **Demo:** 50 episodes (~ 5 minutes, good for live presentation)
- **Research:** 100 episodes (~ 10 minutes, better statistics)
- **Deep investigation:** 200 episodes (~ 20 minutes, thorough)

Also, TPE needs fewer data points than GP because it models the distribution of good vs. bad points, not the entire response surface.

**Effort: ZERO** — just change a number in the config.

---

## 🟠 Issue 6: Robustness score only works for gradual failures

**Problem:** Cliff-edge failures have no gradient for the AI to follow.

**Solution: Use multiple feedback channels, not just the primary oracle.**

Even when the main requirement is binary (reset or no reset), secondary signals can provide gradient:

| Signal | What it tells the AI |
|---|---|
| Current draw | "Current spiked to 180mA (limit 200mA) — getting close to something" |
| Heartbeat jitter | "Heartbeat timing variance increased — system is stressed" |
| Boot time | "Boot took 800ms instead of 500ms — something is off" |
| OLED latency | "Frame was 90ms (limit 120ms) — approaching boundary" |
| Voltage droop | "Rail drooped 50mV during Wi-Fi TX — interaction happening" |

Feed ALL of these to the planner as a composite score, not just the binary pass/fail.

**Effort: LOW** — just log more measurements and combine them.

---

## 🟠 Issue 7: Acquisition function weights are arbitrary

**Problem:** `w_fail`, `w_uncertainty`, `w_novelty`, `w_cost` — how do you set them?

**Solution: Don't use a custom acquisition function. Use Optuna's TPE.**

TPE doesn't have user-tunable exploration/exploitation weights. It automatically balances exploration and exploitation through its kernel density estimation. One less thing to tune, one less thing to defend.

If you want more exploration, just increase `n_startup_trials` (the number of random trials before TPE kicks in).

**Effort: ZERO** — already solved by Issue 4's solution.

---

## 🟠 Issue 8: "Novelty" is undefined

**Problem:** What does "behavioral novelty" even mean concretely?

**Solution: Drop novelty from V1. It's not needed.**

TPE already handles exploration vs. exploitation. Adding a novelty term on top adds complexity with unclear benefit. If you want diversity:

- Optuna's TPE naturally explores under-sampled regions
- You can add a `QMCSampler` for quasi-random space-filling
- You can constrain: "don't repeat the same categorical combination twice in a row"

Save "novelty-based exploration" for a future-work slide.

**Effort: NEGATIVE** — you're removing work, not adding it.

---

## 🔴 Issue 9: Instrument control will eat weeks

**Problem:** SCPI dialects, USB flakiness, timing quirks.

**Solution: Build a simple RP2040-based "instrument" with DAC + LDO modules.**

Instead of expensive lab instruments with finicky SCPI:

```
RP2040 Pico (₹400)
  ├── I²C → MCP4725 DAC #1 (₹200) → AMS1117-ADJ LDO → OLED rail
  ├── I²C → MCP4725 DAC #2 (₹200) → AMS1117-ADJ LDO → Sensor rail
  ├── I²C → ADS1115 ADC (₹300) → reads back actual voltages
  ├── GPIO → Load switch enable pins (cut power to each rail)
  ├── GPIO → DUT reset pin
  └── USB Serial → Host laptop (simple text protocol)
```

The protocol is dead simple:

```
Host sends:    SET OLED 3.24
RP2040 does:   Set DAC to value, wait 50ms, read ADC
RP2040 replies: OK OLED 3.238

Host sends:    SET SENSOR 3.30
RP2040 replies: OK SENSOR 3.301

Host sends:    READ ALL
RP2040 replies: OLED=3.238 SENSOR=3.301 CURR_OLED=0.047 CURR_SENSOR=0.012

Host sends:    SHUTDOWN
RP2040 replies: OK ALL_OFF
```

No SCPI. No PyVISA. No instrument drivers. Just serial.

**Total hardware cost: ~₹2,000** for the instrument controller.

The RP2040 also acts as the **watchdog**: if it doesn't receive a serial message for 3 seconds, it sets all DACs to 0V and opens load switches.

**Effort: MEDIUM** — need to write RP2040 firmware (~200 lines of C) and wire up the breadboard.

---

## 🟠 Issue 10: DUT will be flaky

**Problem:** ESP32 Wi-Fi is non-deterministic, ADC is noisy, timing varies.

**Solution: Accept it. Design around it.**

1. **Drop Wi-Fi as a workload** for V1 — use deterministic workloads only (LED, OLED, sensor, flash, CPU-intensive loop)
2. **Use external ADC** (ADS1115) for measurement, not ESP32's internal ADC
3. **Run each condition 3 times** minimum before scoring — use median, not single reading
4. **Add a "measurement quality" flag** — if readings vary by >10%, mark the trial as "noisy" and re-run

**Effort: LOW** — just firmware and scoring logic changes.

---

## 🔴 Issue 11: Custom carrier PCB is a separate project

**Problem:** Designing, ordering, and debugging a custom PCB takes 4-6 weeks.

**Solution: No custom PCB. Use breadboard + modules.**

```
Breadboard Layout:
┌─────────────────────────────────────────────────┐
│                                                  │
│  [ESP32-S3 DevKitC]  ← powered via USB (3.3V)   │
│     │    │    │                                   │
│     │    │    └── UART TX → Host laptop           │
│     │    └── I²C SDA/SCL → [OLED module]         │
│     └── I²C SDA/SCL → [BME280 sensor module]     │
│     GPIO → Red LED + 330Ω resistor               │
│     GPIO → Green LED + 330Ω resistor             │
│                                                   │
│  [OLED module VCC] ← wire from LDO #1 output     │
│  [Sensor module VCC] ← wire from LDO #2 output   │
│                                                   │
│  [RP2040 Pico] ← the instrument controller       │
│     I²C → [DAC #1] → [LDO #1] → OLED power     │
│     I²C → [DAC #2] → [LDO #2] → Sensor power   │
│     I²C → [ADS1115] ← reads rail voltages       │
│     GPIO → load switch enables                    │
│     USB → Host laptop                             │
│                                                   │
│  [Fuse] in main power line (500mA polyfuse)       │
│  [Toggle switch] for manual power cut             │
└─────────────────────────────────────────────────┘
```

Key trick: the ESP32 core is always powered via USB (stable 3.3V from onboard regulator). Only the **peripheral power** (OLED and sensor) is externally controlled. This eliminates the need for level translators and back-power protection on the main bus — the I²C lines are always at 3.3V from the ESP32.

**Cost: ~₹3,000 total** for all components.
**Effort: LOW** — breadboard assembly, no PCB design/fabrication.

---

## 🟠 Issue 12: Calibration drift

**Problem:** Tuesday's 3.24V might be Wednesday's 3.27V.

**Solution: Auto-calibrate at the start of every campaign.**

```python
def auto_calibrate():
    """Run at campaign start. Takes 30 seconds."""
    for target_v in [3.0, 3.2, 3.4, 3.6]:
        set_dac(target_v)
        time.sleep(0.5)
        actual_v = read_adc()
        calibration_points.append((target_v, actual_v))

    # Linear fit: actual = gain * target + offset
    gain, offset = np.polyfit(
        [p[0] for p in calibration_points],
        [p[1] for p in calibration_points], 1)

    # Now use corrected values: dac_value = (desired - offset) / gain
```

Run this automatically before every campaign. Takes 30 seconds. Stores gain/offset with timestamp.

**Effort: VERY LOW** — 20 lines of Python.

---

## 🟠 Issue 13: Controlled Wi-Fi is hard

**Problem:** RF environment is inconsistent in a shared lab.

**Solution: Drop Wi-Fi for V1. Replace with deterministic workloads.**

| Dropped | Replacement | Why it's better |
|---|---|---|
| Wi-Fi TX | CPU-intensive FFT computation | Deterministic, repeatable, creates real current draw |
| Wi-Fi scan | Rapid GPIO toggling | Creates current transients without RF dependency |

If Wi-Fi is needed later, add it as a V2 feature with a dedicated AP in a shielded box.

**Effort: NEGATIVE** — removing complexity.

---

## 🟠 Issue 14: Comparing adaptive vs. random on seeded fault is circular

**Problem:** Designing the test to suit the method proves nothing.

**Solution: Run multiple fault geometries and report ALL results.**

The honest story is:

```
Fault Type          | TPE vs Random      | Why
────────────────────┼────────────────────┼──────────────────
Gradient-guided     | TPE wins by 40%    | TPE exploits gradient
Binary island       | TPE wins by 5%     | Mostly luck-based
Disconnected        | TPE wins by 15%    | TPE covers space better
No fault            | Both correct       | Neither false-alarms
```

Showing WHERE the method works and WHERE it doesn't is **stronger research** than claiming it always works.

**Effort: LOW** — just run all fault types and make a table.

---

## 🟠 Issue 15: N=1 devices means no generalization

**Solution: Accept it. Frame correctly.**

"We demonstrate the approach on one device family with multiple workload configurations. Generalization to other architectures is a direction for future work."

Nobody expects a POC to solve everything. What matters is that the **system design** is reusable (swap contract + firmware, same engine).

**Effort: ZERO** — just honest writing.

---

## 🟠 Issue 16: Team evaluates own algorithm

**Solution: Use pre-registration and publish everything.**

1. Write down benchmarks, metrics, and success criteria BEFORE running final experiments
2. Freeze code before final evaluation
3. Publish all raw data, all seeds, all results (including bad ones)
4. Use Optuna's built-in samplers (you didn't write the algorithm, Optuna's team did)

Using Optuna also helps here — you're comparing **third-party algorithms** (TPE, CMA-ES, random) against each other. You didn't write any of them.

**Effort: LOW** — a 1-page pre-registration document.

---

## 🟡 Issue 17: Tests-to-first-failure is misleading for cliff-edge failures

**Solution: Use discovery rate as the primary metric.**

Instead of "how many tests until the first failure" (dominated by luck), use:

```
Discovery Rate = (campaigns that found ≥1 failure) / (total campaigns)
```

At budget 50, across 20 campaigns:
- TPE: 18/20 = 90%
- Random: 12/20 = 60%

This is more robust and easier to interpret.

**Effort: ZERO** — just a different calculation on the same data.

---

## 🟡 Issue 18–20: Safety system gaps and hardware interlock

**Solution: For extra-low-voltage supervised testing, simplify drastically.**

The entire safety system for V1:

| Layer | Implementation | Cost |
|---|---|---|
| Software safety kernel | Python function, 50 lines | ₹0 |
| RP2040 watchdog | Cuts power if no heartbeat from host for 3s | ₹0 (same RP2040) |
| Polyfuse | 500mA resettable fuse in power line | ₹20 |
| Toggle switch | Manual power disconnect | ₹50 |
| Current monitoring | ADS1115 reads shunt voltage, software checks limit | ₹0 (same ADC) |

Total hardware safety cost: **₹70**

At <5V and <500mA, the absolute worst case is a ₹800 dev board dying. That's an acceptable risk for a supervised lab project. No need for a custom interlock PCB, E-stop button, or comparator circuits.

**Effort: VERY LOW** — ₹70 of parts and 50 lines of Python.

---

## 🔴 Issue 21: Project is 3–5 projects in one

**Solution: Ruthlessly cut scope.**

| Original scope | Simplified scope | What changed |
|---|---|---|
| Custom carrier PCB | Breadboard + modules | No PCB design |
| 3-5 programmable rails | 2 rails (OLED + sensor) | Fewer channels |
| Lab instruments + SCPI | RP2040 + DAC + LDO | Cheap, custom, simple |
| GP/RF/TPE from scratch | Optuna (pip install) | Zero ML code |
| 10 HLD documents | 1 design doc | Less paperwork |
| 10 benchmarks | 4 benchmarks | B1, B3, B6, B8 |
| 9 baseline methods | 3 baselines | Random, Grid, TPE |
| 2 DUT designs | 1 DUT, 2 firmware configs | Same board, different faults |
| Custom web UI | Optuna Dashboard + simple status page | Free dashboard |
| Custom interlock PCB | Fuse + toggle switch | ₹70 |
| Wi-Fi workload | Deterministic workloads only | No RF headaches |
| 24-week timeline | 12-week core + 12 polish | Earlier working system |

**Effort: NEGATIVE** — you're removing work.

---

## 🔴 Issue 22: 1884 lines of PRD, 0 lines of code

**Solution: Code-first approach.**

Week 1: Get Optuna running with a Python function as the DUT simulator.
Week 2: Get RP2040 talking to the laptop over serial.
Week 3: Get DAC controlling voltage and ADC reading it back.
Week 4: Wire up the ESP32 with OLED and sensor on external rails.
Week 5: End-to-end physical campaign.

Documents evolve WITH the code, not before it.

**Effort: NEGATIVE** — stop writing docs, start coding.

---

## 🔴 Issue 23: 10 HLDs is enterprise overkill

**Solution: One design doc. Update it as you build.**

Replace all 10 HLDs with a single `ARCHITECTURE.md` that contains:
- System diagram (what talks to what)
- Data flow (how an episode runs)
- File structure (where code lives)
- API (serial protocol + Python functions)

Update it weekly. Don't pre-write sections you haven't built yet.

**Effort: NEGATIVE** — deleting 9 planned documents.

---

## 🟡 Issues 24–31: Episode limits, oracle, minimizer, episodes, team, lab, timeline, debugging

All of these are solved by the scope reduction above:

| Issue | Solution |
|---|---|
| Episodes miss long-duration bugs | Accept the limitation, document it |
| Oracle needs semantic understanding | V1 uses timing-based oracles only (sufficient for demo) |
| Minimizer assumes deterministic | Run each minimization step 3× and use majority vote |
| 2-second episodes too short | Default to 5 seconds, configurable per contract |
| Hardware single point of failure | Breadboard is simple enough for any team member |
| Lab access conflicts | Rig fits in a shoebox, can work at home |
| Kill criteria too late | Week 2: hardware working. Week 4: first sim campaign. Week 6: first physical campaign |
| Physical debugging is slow | Build simulator FIRST. Debug all logic in sim. |

---

## Summary: Before vs. After

| Aspect | Original PRD | Simplified |
|---|---|---|
| Hardware cost | ₹15,000–₹3,00,000 | ~₹5,000 |
| Custom PCBs needed | 2+ (carrier + interlock) | 0 |
| Lines of ML code | 1000+ (GP, kernels, acquisition) | ~30 (Optuna wrapper) |
| Documents to write | 10 HLDs + PRD | 1 design doc |
| Benchmarks | 10 (B1–B10) | 4 |
| Baselines to implement | 9 | 3 (all from Optuna) |
| Time to first physical test | Week 8 | Week 4 |
| Dependencies on lab equipment | High | Low (portable rig) |
| Risk of total project failure | High | Low |
