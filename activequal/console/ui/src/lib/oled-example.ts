import { SetupDraft } from "./types";

// PRD §9.2 and §16.1; HLD 04 §11. This is a preview, not a reviewed bench contract.
export const oledExample: SetupDraft = {
  name: "ESP32-S3 OLED demo",
  dut: "ESP32-S3 carrier · revision A · DUT-A-01",
  firmware: "Build hash pending (example)",
  fixture: "OLED demo fixture (identity pending)",
  wiring: "Protected, fixed 3.3 V MCU supply. SSD1306-class OLED and 3.3 V I²C sensor on separate programmable rails. Red/green LEDs, heartbeat pin, UART telemetry and reset monitor. Bus isolation prevents back-powering. Actual hardware and calibration need confirmation.",
  railName: "OLED rail", railMin: "3.00", railMax: "3.60", railStep: "0.01",
  sensorRailName: "Sensor rail", sensorRailMin: "3.00", sensorRailMax: "3.60", sensorRailStep: "0.01",
  redLedOptions: "off, on", greenLedOptions: "off, on", workloads: "oled_refresh",
  settleMs: "100", durationMs: "2000",
  observations: "Requested and measured OLED/sensor rail voltages, per-channel current, board temperature, OLED frame latency, heartbeat gaps, reset count/reason and UART timing markers. Record missing or unreliable evidence as invalid.",
  requirement: "OLED frame latency ≤ 120 ms; heartbeat gap ≤ 500 ms; |measured voltage − requested voltage| ≤ 0.03 V; reset count = 0. Judge usable measured behavior only.",
  forbiddenCombinations: "", maxVoltage: "3.60", maxCurrent: "0.20", maxTemperature: "60",
  safeState: "Example only; bench review pending. Stop the workload, isolate signals to prevent back-powering, then return programmable rails to 0 V in the approved fixture order and verify read-back. Safety trip: cut relevant outputs, enter lockout and require manual reset. PRD episode ceiling: 10 s. The 100 ms settling and 2000 ms workload values are preview placeholders, not reviewed limits.",
  experimentBudget: "30", plannerMethod: "tpe", plannerSeed: "20260903"
};
