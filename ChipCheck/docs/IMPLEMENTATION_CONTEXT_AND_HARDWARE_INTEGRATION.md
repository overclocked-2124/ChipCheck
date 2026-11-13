# ChipCheck Raspberry Pi Pin-Failure Search

This document records the current implementation, what has been tested, how to run it, and the work needed to connect a real test fixture.

## 1. Project goal

ChipCheck proposes input configurations, executes them one at a time, observes a result, and uses the result to choose later tests. For this use case, a configuration sets three LED-related input voltages and observes whether a separate buzzer works.

The failure condition is an interaction: the buzzer fails only when **all three input voltages are in their failing intervals at the same time**. The search target is therefore a three-dimensional box (or a union of several boxes), such as:

```text
LED 1: 1.1–2.2 V
LED 2: 2.1–2.3 V
LED 3: 1.7–2.1 V
Outcome: buzzer fails only when all three conditions hold
```

The contract describes the inputs and required observation. The search algorithm does not receive the hidden failure intervals.

## 2. What is implemented

### Contract and voltage representation

[`contracts/raspi_pins.yaml`](../contracts/raspi_pins.yaml) defines three input parameters, `led1_voltage`, `led2_voltage`, and `led3_voltage`, each spanning 0–3.3 V. The inputs are represented as 8-bit levels:

```text
code = 0..255
voltage = 3.3 * code / 255
```

The contract also requires `buzzer_working >= 1`, where 1 means working and 0 means malfunctioning. Safety validation rejects voltages outside the contract range and values that are not aligned to the 8-bit step.

Optuna samples integer codes internally and ChipCheck converts those codes to voltages. This avoids floating-point step warnings and ensures proposed voltages correspond to representable levels.

### Simulator scenarios

[`chipcheck/executor/raspi_simulator.py`](../chipcheck/executor/raspi_simulator.py) has deterministic scenarios used to test the search software:

| Scenario | Simulated fault |
|---|---|
| R1 | LED 1: 1.1–2.2 V; LED 2: 2.1–2.3 V; LED 3: 1.7–2.1 V |
| R2 | Broad box: LED 1: 0.8–2.5 V; LED 2: 1.0–2.8 V; LED 3: 0.5–2.5 V |
| R3 | Narrow off-centre box |
| R4 | No failure anywhere |
| R5 | Two disjoint LED 1 windows, with shared LED 2 and LED 3 conditions |

For multiple boxes, a voltage tuple fails if it is inside **any one complete box**. A tuple that satisfies only one or two pin intervals passes.

These are synthetic hidden rules. They are not a circuit simulation of Raspberry Pi silicon or proof of behavior on a physical board.

### Campaign and output

[`chipcheck/campaign/__init__.py`](../chipcheck/campaign/__init__.py) connects the contract, safety checks, planner, executor, and oracle. It executes a test synchronously: send one configuration, wait for one result, evaluate it, then ask for the next configuration.

For Raspberry Pi runs, [`main.py`](../main.py) prints every executed test and its result directly to the CLI. Campaign state is held in memory; the Pi run does not write campaign reports or databases under `output/`.

Each line looks like:

```text
[TEST 0001] led1_voltage=1.6565V led2_voltage=1.6565V led3_voltage=1.6565V -> FAIL (BUZZER FAILED)
```

At the end, ChipCheck prints the failing ranges it localized and total test count.

### Range localization

After a failure is found, ChipCheck holds two pins at the failing tuple and varies the remaining pin. It records the interval of voltage codes that continue to fail. This is repeated for each pin. A region is reported as three inclusive intervals; all three conditions must hold together.

Default multi-region mode scans outward one code at a time. It does not assume pass/fail is monotone across the entire 0–3.3 V domain, so it can keep separate windows separate when separate failing anchors have been found. A separate failing anchor is needed for each disconnected box.

`--single-region` is an optional faster mode. It stops discovery after the first failure and uses binary search to find the six edges. This assumes one contiguous failure box around that anchor and intentionally skips searching for other disconnected windows.

### Current verified results

- R1, TPE, seed 42, budget 1000, default multi-region mode found 161 failing discovery tests and localized:

  ```text
  led1_voltage=1.1000..2.2000V
  led2_voltage=2.1094..2.2906V
  led3_voltage=1.7082..2.0965V
  ```

  The LED 2 and LED 3 bounds are the nearest failing 8-bit levels to the requested continuous limits.
- For R1 with `--single-region`, the same seed found and localized the same region in 251 total tests versus 1,135 in the multi-region run (884 fewer, about 78% fewer). This result is for the deterministic simulator and this seed.
- Ten distinct synthetic three-pin boxes were passed through the range localizer. It recovered all 30 pin intervals exactly on the 8-bit code grid.
- R5 tests verify that two already-discovered LED 1 windows remain separate.
- The full unit suite last completed with **60 tests passing**.

These checks validate the software against synthetic scenarios. No physical Raspberry Pi, DAC, buzzer sensor, or controller was connected during these runs.

## 3. How to run the simulator

Run commands from the `ChipCheck` directory.

Validate the contract:

```powershell
python main.py validate-contract --contract contracts/raspi_pins.yaml
```

Quick broad-region demo:

```powershell
python main.py run --contract contracts/raspi_pins.yaml --benchmark R2 --planner tpe --budget 40 --seed 42
```

Search for the narrower R1 box, stopping at the first failure and assuming a single contiguous region:

```powershell
python main.py run --contract contracts/raspi_pins.yaml --benchmark R1 --planner tpe --budget 1000 --seed 42 --single-region
```

Search for more than one failure window by omitting `--single-region`. The discovery `--budget` limits discovery tests; boundary localization tests are additional. A narrow failure box can require a larger discovery budget before any failure point is found.

For the simulator:

- `--planner tpe` uses Optuna TPE.
- `--planner random` uses Optuna Random as a baseline.
- `--benchmark` selects R1–R5.
- `--seed` makes simulator proposal sequences repeatable.
- `--budget` is the discovery budget. Boundary probes run after discovery and are included in the final total.

## 4. Hardware reality to account for

On standard Raspberry Pi models, GPIO header pins are digital 3.3 V logic: outputs are low/high, and inputs are read as digital low/high. GPIO pins are not arbitrary analog voltage outputs or ADC inputs, and the GPIOs are not 5 V tolerant. Therefore the 0–3.3 V values in the contract require a fixture that can safely generate and measure analog levels; they cannot be generated by simply writing a Raspberry Pi GPIO high/low. See the [official Raspberry Pi computer hardware documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html).

Before wiring, identify the exact board and use the official pinout. On common 40-pin Raspberry Pi boards, physical header pin 3 is GPIO2/SDA and has an I²C role; “pin 3” can also mean a BCM GPIO number or an application signal name. These are different identifiers. Do not assume they are interchangeable.

For an analog voltage test, the fixture normally needs an external DAC (or a suitably filtered PWM stage), output buffering/current limiting appropriate to the circuit, a common reference ground, and a way to observe the buzzer signal. If the buzzer requirement is audible output rather than its electrical drive signal, the observation hardware must measure the acoustic output. The correct fixture depends on the actual schematic and the Raspberry Pi model.

Recommended conceptual layout:

```text
ChipCheck on PC
    │ USB serial: one JSON request at a time
    ▼
Test controller / fixture (for example, a separate RP2040 board)
    ├─ DAC channel 1 ──► DUT LED/input signal 1
    ├─ DAC channel 2 ──► DUT LED/input signal 2
    ├─ DAC channel 3 ──► DUT LED/input signal 3
    ├─ ADC/readback ───► measure applied voltages
    ├─ input/sensor ───► observe buzzer working or failed
    └─ serial reply ───► return result for the same experiment ID
```

The controller should be a separate fixture if the Raspberry Pi itself is the DUT. It must not rely on the DUT’s possibly malfunctioning pins to safely control test voltages or report the result.

## 4A. Direct Raspberry Pi GPIO demonstration script

[`hardware/raspi_gpio_fault_demo.py`](../hardware/raspi_gpio_fault_demo.py) is a second, direct-on-the-Pi demonstration. It uses `gpiozero` to PWM-drive three LEDs and switch an active buzzer while Optuna searches. It injects a hidden R1/R2/R3 fault in Python by silencing the buzzer for selected code combinations. This makes the search visible on physical LEDs and a buzzer, but the failure is deliberately seeded in software. It does **not** detect or prove an electrical fault in the Pi.

The script uses BCM numbering on a standard Raspberry Pi 40-pin header:

| Signal | BCM GPIO | Physical header pin | Connection |
|---|---:|---:|---|
| LED 1 | GPIO17 | 11 | GPIO17 → 330–470 ohm resistor → LED anode; LED cathode → GND |
| LED 2 | GPIO27 | 13 | GPIO27 → 330–470 ohm resistor → LED anode; LED cathode → GND |
| LED 3 | GPIO22 | 15 | GPIO22 → 330–470 ohm resistor → LED anode; LED cathode → GND |
| Buzzer control | GPIO23 | 16 | GPIO23 → 1 kohm resistor → NPN transistor base |
| Ground | GND | 6 | LED cathodes and transistor emitter return |
| Buzzer supply | 3V3 | 1 | Positive lead of a buzzer rated for 3.3 V |

Use a low-side NPN driver for the buzzer: transistor emitter to ground, collector to buzzer negative, buzzer positive to its rated supply. If the buzzer is inductive, add a flyback diode across it, with the diode stripe toward the positive supply. Transistor pin order varies by part; check its datasheet. If the buzzer needs a separate supply, join that supply's ground to Pi ground. Do not connect a 5 V signal to a Pi GPIO. The official Raspberry Pi documentation describes GPIO as 3.3 V logic and warns that it is not 5 V tolerant: [Raspberry Pi computer hardware](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html).

This script uses PWM duty cycle to vary LED brightness; PWM is a stream of digital high/low pulses, not a true analog voltage. The reported voltage-equivalent is only the PWM average used by the seeded demo. A real analog voltage test still needs an external DAC/fixture and a real DUT measurement path.

On Raspberry Pi OS, install the packages and run the broad, quick demo from the `ChipCheck` directory:

```bash
sudo apt install python3-gpiozero python3-venv
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install optuna
python hardware/raspi_gpio_fault_demo.py --scenario R2 --trials 200
```

Use `--scenario R1 --trials 1000` to search the narrower seeded R1 box. The script drives GPIO directly on the Pi, so it does not use `--hardware-port` or the USB serial protocol. Keep in mind that this is a physical-output demonstration of the software-injected fault model.

## 5. Serial protocol ChipCheck expects

The physical mode uses the existing newline-delimited JSON serial executor. ChipCheck opens the supplied serial port at 115200 baud. For each test it sends one line like:

```json
{"experiment_id":101,"command":"RUN_PIN_TEST","parameters":{"led1_voltage":1.6564705882352942,"led2_voltage":2.1094117647058823,"led3_voltage":1.708235294117647}}
```

The controller must:

1. Parse the complete line and validate the command and the three requested voltages.
2. Quantize or apply those voltages using the fixture hardware, then wait for settling as required by the circuit.
3. Measure the applied voltages if readback is available.
4. Run the buzzer functional check for a contractually defined observation period.
5. Return exactly one JSON response line with the same `experiment_id`:

```json
{"experiment_id":101,"status":"COMPLETED","results":{"buzzer_working":0}}
```

Use `buzzer_working: 1` when the buzzer passes and `0` when it fails. Extra fields such as `actual_led1_voltage`, `actual_led2_voltage`, `actual_led3_voltage`, and `measurement_quality` may be included for diagnostics; the current oracle specifically requires `buzzer_working`.

The matching experiment ID is important. A timeout, malformed response, mismatched ID, or missing `buzzer_working` measurement is an invalid/inconclusive test, not a DUT failure. Do not report a communication error as a buzzer failure. The controller should send no unsolicited JSON lines that could be mistaken for the next response.

## 6. Running against a serial controller

Install the runtime dependencies if they are not already present:

```powershell
python -m pip install optuna pyyaml pyserial
```

Connect the fixture and identify its port in Device Manager. Then run a very small campaign first, for example:

```powershell
python main.py run --contract contracts/raspi_pins.yaml --benchmark R2 --planner random --budget 1 --seed 42 --hardware-port COM4 --skip-localization
```

The one-test run sends one input tuple and waits for the controller reply. `--skip-localization` ensures this bring-up check does not launch extra range probes if the test fails. After confirming the electrical setup, controller response, returned ID, and `buzzer_working` value, run the intended discovery campaign. Example:

```powershell
python main.py run --contract contracts/raspi_pins.yaml --benchmark R1 --planner tpe --budget 1000 --seed 42 --single-region --hardware-port COM4
```

`--single-region` is appropriate only when searching for one contiguous box. For multiple windows, omit it and use a discovery budget sufficient to find an anchor in each window. Physical localization may take hundreds of additional serial transactions in exhaustive mode. Each localization probe is a real DUT test.

## 7. Hardware work still required

The software side is prepared to synchronously send one configuration and wait for its result, but hardware integration is not complete until the following are done:

1. Confirm the exact DUT model, pin numbering convention, electrical schematic, and what “LED input voltage” means in the real circuit.
2. Define the buzzer pass/fail measurement: digital drive level, current, acoustic measurement, or another signal; specify the observation duration and thresholds.
3. Design and independently review the fixture, DAC/ADC ranges, buffering, grounding, current limits, startup state, and fault-safe state.
4. Implement the controller firmware for the JSON request/reply protocol, including experiment IDs, validation, watchdog/timeout behavior, and safe output shutdown.
5. Test the controller protocol disconnected from the DUT, then run one safe known-pass case and one controlled known-fail case.
6. Only then run adaptive discovery. Compare requested and measured applied voltages and repeat physical boundary points to quantify noise before treating ranges as stable.

The current range localizer assumes deterministic pass/fail. Real hardware may be noisy or intermittent. For physical runs, repeated measurements at boundaries and a rule such as majority vote or a minimum reproducibility rate should be chosen before claiming an exact voltage range.

## 8. Key files

| File | Responsibility |
|---|---|
| [`contracts/raspi_pins.yaml`](../contracts/raspi_pins.yaml) | Voltage controls, 8-bit step, safety limits, buzzer requirement |
| [`chipcheck/executor/raspi_simulator.py`](../chipcheck/executor/raspi_simulator.py) | R1–R5 and custom synthetic failure boxes |
| [`chipcheck/planners/__init__.py`](../chipcheck/planners/__init__.py) | TPE/Random and integer-code sampling for stepped voltages |
| [`chipcheck/campaign/__init__.py`](../chipcheck/campaign/__init__.py) | Sequential execution, output, confirmation, boundary localization |
| [`chipcheck/executor/serial_executor.py`](../chipcheck/executor/serial_executor.py) | Newline JSON serial transport and response validation |
| [`main.py`](../main.py) | CLI commands, `--hardware-port`, `--single-region`, console output |
| [`tests/test_raspi.py`](../tests/test_raspi.py) | Scenario, boundary, 10-box, and console workflow tests |

