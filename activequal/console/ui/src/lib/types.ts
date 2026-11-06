export type SetupDraft = {
  name: string;
  dut: string;
  firmware: string;
  fixture: string;
  wiring: string;
  railName: string;
  railMin: string;
  railMax: string;
  railStep: string;
  sensorRailName: string;
  sensorRailMin: string;
  sensorRailMax: string;
  sensorRailStep: string;
  redLedOptions: string;
  greenLedOptions: string;
  workloads: string;
  settleMs: string;
  durationMs: string;
  observations: string;
  requirement: string;
  forbiddenCombinations: string;
  maxVoltage: string;
  maxCurrent: string;
  maxTemperature: string;
  safeState: string;
  experimentBudget: string;
  plannerMethod: "tpe" | "gp" | "random" | "grid";
  plannerSeed: string;
};

export type ProposedTest = {
  id: string;
  title: string;
  purpose: string;
  requested: string[];
  expectedObservations: string[];
  reason?: string;
  conditions?: { railVolts: number; sensorRailVolts?: number; redLed: string; greenLed: string; workload: string };
};

export type ProposalResponse = {
  source: "mock" | "backend" | "decision";
  setupName: string;
  tests: ProposedTest[];
  method?: string;
  historyUsed?: number;
};

export const emptyDraft: SetupDraft = {
  name: "", dut: "", firmware: "", fixture: "", wiring: "",
  railName: "", railMin: "", railMax: "", railStep: "", sensorRailName: "", sensorRailMin: "", sensorRailMax: "", sensorRailStep: "", redLedOptions: "on, off", greenLedOptions: "on, off",
  workloads: "", settleMs: "", durationMs: "", observations: "",
  requirement: "", forbiddenCombinations: "", maxVoltage: "",
  maxCurrent: "", maxTemperature: "", safeState: "", experimentBudget: "", plannerMethod: "tpe", plannerSeed: "42"
};
