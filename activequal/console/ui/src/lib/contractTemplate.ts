import type { JsonValue } from "./types.ts";

// A copy of activequal/model/examples.py oled_example_contract() (HLD 04 §12.1). Example values, not approved limits:
// take real limits from the selected parts (HLD 02 §19.1). The control plane validates whatever is saved.
export const OLED_TEMPLATE: Record<string, JsonValue> = {
  contractVersion: 2,
  setup: { dut: "esp32s3-oled-demo", firmwareSha256: "0".repeat(64), fixture: "bench-A", fixtureRev: "A" },
  controls: {
    oledRailV: { type: "continuous", unit: "V", min: 3.0, max: 3.6, step: 0.01, nominal: 3.3, shutdown: 0.0, slewPerSMax: 0.5, bind: { target: "supply.ch2", action: "setVoltage" } },
    sensorRailV: { type: "continuous", unit: "V", min: 3.0, max: 3.6, step: 0.01, nominal: 3.3, shutdown: 0.0, slewPerSMax: 0.5, bind: { target: "supply.ch3", action: "setVoltage" } },
    redLed: { type: "boolean", nominal: false, bind: { target: "dut", action: "LED RED" } },
    greenLed: { type: "boolean", nominal: false, bind: { target: "dut", action: "LED GREEN" } },
    workload: { type: "categorical", values: ["idle", "oled_refresh", "sensor_read", "flash_write"], nominal: "idle", bind: { target: "dut", action: "WORKLOAD" } },
    flashOffsetMs: { type: "integer", unit: "ms", min: 0, max: 20, step: 1, nominal: 0, activeWhen: { control: "workload", eq: "flash_write" }, bind: { target: "mcu", action: "flashOffset" } },
    dwellMs: { type: "duration", unit: "ms", min: 200, max: 2000, step: 100, nominal: 500 },
  },
  forbidden: [{ all: [{ control: "workload", eq: "flash_write" }, { control: "sensorRailV", gte: 3.55 }] }],
  observations: {
    oledLatencyMs: { unit: "ms", source: "firmware", reduction: "max", requiredWhen: { control: "workload", eq: "oled_refresh" }, uncertainty: 5 },
    maxHeartbeatGapMs: { unit: "ms", source: "firmware", reduction: "max_gap", required: true, uncertainty: 10 },
    resetCount: { unit: "count", source: "mcu", reduction: "count", required: true },
    measuredOledRailV: { unit: "V", source: "instrument", reduction: "mean", required: true, uncertainty: 0.01 },
    measuredDut3v3MinV: { unit: "V", source: "instrument", reduction: "min", required: true, uncertainty: 0.01 },
  },
  requirements: [
    { id: "latency", metric: "oledLatencyMs", op: "<=", limit: 120, nominal: 31 },
    { id: "heartbeat", metric: "maxHeartbeatGapMs", op: "<=", limit: 500, nominal: 200 },
    { id: "reset", metric: "resetCount", op: "exact", limit: 0 },
    { id: "dut_3v3_band", metric: "measuredDut3v3MinV", op: "band", lo: 3.135, hi: 3.465, nominal: 3.3 },
  ],
  validity: [{ metric: "measuredOledRailV", tracks: "oledRailV", tolerance: 0.03 }],
  scoring: { planner: "normalized_min", verdict: "guard_banded" },
  safety: { channels: { "supply.ch2": { maxA: 0.2, maxV: 3.6 }, "supply.ch3": { maxA: 0.2, maxV: 3.6 } }, maxTempC: 60, maxEpisodeS: 10 },
  templates: [],
  campaign: { budget: 74, seed: 42, plan: "default_v1" },
};
