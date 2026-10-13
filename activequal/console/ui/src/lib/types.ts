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
  ledStates: string;
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
};

export type ProposedTest = {
  id: string;
  title: string;
  purpose: string;
  requested: string[];
  expectedObservations: string[];
};

export type ProposalResponse = {
  source: "mock" | "backend";
  setupName: string;
  tests: ProposedTest[];
};

export const emptyDraft: SetupDraft = {
  name: "", dut: "", firmware: "", fixture: "", wiring: "",
  railName: "", railMin: "", railMax: "", railStep: "", ledStates: "",
  workloads: "", settleMs: "", durationMs: "", observations: "",
  requirement: "", forbiddenCombinations: "", maxVoltage: "",
  maxCurrent: "", maxTemperature: "", safeState: "", experimentBudget: ""
};
