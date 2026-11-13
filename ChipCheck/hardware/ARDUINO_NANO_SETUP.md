# 3.3 V Arduino Nano setup

These steps assume a **Nano 33 IoT or Nano 33 BLE**. These are 3.3 V boards;
the classic Arduino Nano is 5 V and needs a different PWM mapping. The sketch
uses D3, D5, and D6 for LED PWM, D9 for the buzzer module signal, and
`LED_BUILTIN` to show failures.

The contract and host print a 0–3.3 V PWM-average-equivalent scale. The Nano's
PWM pin switches between 0 and 3.3 V; it does not produce a steady analog
voltage. The failure is injected in the sketch, so this is a search demo, not
detection of an unknown electrical fault.

## Connections

Unplug USB while wiring. Use the pin labels printed on the board, not header
position numbers.

**Buzzer module:** this wiring is for a module with three pins (`VCC`, `GND`,
and `SIG`/`IN`), whose documentation says it works from 3.3 V and accepts a
3.3 V logic signal.

| Buzzer module pin | Nano connection |
|---|---|
| `VCC` / `+` | `3V3` |
| `GND` / `-` | `GND` |
| `SIG` / `IN` | `D9` |

If the module is marked 5 V only, or has only two pins, do not connect it this
way; check its part number or label first. If it is active-low, change
`BUZZER_ACTIVE_HIGH` to `false` in the sketch and upload it again. No external
transistor is needed for a module whose onboard driver takes the buzzer current
and whose signal pin is a 3.3 V logic input.

**Three LEDs (optional):** give every LED its own series resistor:

- `D3` → resistor → LED long leg; LED short leg → `GND`
- `D5` → resistor → LED long leg; LED short leg → `GND`
- `D6` → resistor → LED long leg; LED short leg → `GND`

Use about 330–470 Ω for clearly visible LEDs. Orange-white-yellow is 390 kΩ;
45 kΩ is also much too high for bright LEDs, so leave the external LEDs
disconnected for now. The buzzer and Nano's built-in LED are enough to run the
demo. At each test the built-in LED gives a brief start flash, the PWM values
are held for 0.5 seconds, and then the result is signaled: two short buzzer
beeps for pass, or three LED flashes followed by a steady LED for failure.

## Upload the sketch

1. Install Arduino IDE and connect the Nano by USB.
2. Open `hardware/ArduinoNanoFaultDemo/ArduinoNanoFaultDemo.ino`.
3. In **Tools → Board**, select the exact board: **Arduino Nano 33 IoT** or
   **Arduino Nano 33 BLE**. Install its board package if Arduino IDE prompts.
4. Select the Nano under **Tools → Port** and click **Upload**.
5. Close Arduino IDE's Serial Monitor before running the Python program.

## Run the search

From PowerShell in the `ChipCheck` folder:

```powershell
python -m pip install optuna pyserial
```

Find the Nano's serial port in Arduino IDE's **Tools → Port** menu or Device
Manager, then replace `COM4` below with that port:

```powershell
python hardware/arduino_nano_fault_demo.py --port COM4 --scenario R2 --trials 200 --seed 42
```

The computer proposes a test, sends it over USB, and waits for the Nano's
result before proposing the next one. The CLI prints each test. R2 is the
broad/easy seeded fault. R1 and R3 are narrower; R4 has no fault. To skip extra
boundary probes after the first discovered failure, add `--no-localize`.

The reported voltage values are PWM-average equivalents, not measured analog
voltages. Do not connect the Nano PWM pins to a device expecting steady analog
voltage without appropriate conversion hardware.
