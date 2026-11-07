// The arming checklist (HLD 03 §6.2). The control plane decides; this module only lays its answers out so that
// Arm is enabled when, and only when, every condition passes. Unknown counts as failing.

import type { BenchHealth, CampaignView, ContractSummary, FixtureView, Reason } from "./types.ts";

export const HEALTH_MAX_AGE_S = 10; // activequal/service/backend.py HEALTH_MAX_AGE_S

export type ConditionStatus = "pass" | "fail" | "unknown";
export type Condition = { id: string; label: string; status: ConditionStatus; messages: string[] };

type Def = { id: string; label: string; codes: string[] };
const DEFS: Def[] = [
  { id: "contract", label: "Contract version is approved and immutable", codes: ["CONTRACT_NOT_APPROVED"] },
  { id: "fixture", label: "Fixture identity and revision match the contract", codes: ["FIXTURE_ID_MISMATCH", "FIXTURE_REVISION_MISMATCH", "CAPABILITY_MISSING"] },
  { id: "firmware", label: "DUT and test-controller firmware match approved values", codes: ["DUT_FIRMWARE_MISMATCH", "MCU_FIRMWARE_MISMATCH", "DUT_FIRMWARE_CHANGED", "MCU_FIRMWARE_CHANGED"] },
  { id: "calibration", label: "Calibration is present and current", codes: ["CALIBRATION_MISSING", "CALIBRATION_EXPIRED", "CALIBRATION_CHANGED"] },
  { id: "adapters", label: "Required adapters report compatible capabilities", codes: ["ADAPTER_INCOMPATIBLE"] },
  { id: "outputs", label: "Programmable outputs report shutdown state", codes: ["OUTPUTS_ENERGIZED"] },
  { id: "estop", label: "E-stop is released", codes: ["ESTOP_PRESSED"] },
  { id: "interlock", label: "Hardware interlock and watchdog report healthy", codes: ["INTERLOCK_UNHEALTHY", "WATCHDOG_UNHEALTHY"] },
  { id: "trip", label: "No unresolved trip or lockout exists", codes: ["TRIP_ACTIVE"] },
  { id: "health", label: "Bench health report is recent", codes: ["BENCH_HEALTH_UNKNOWN", "BENCH_HEALTH_STALE"] },
  { id: "budget", label: "Budgets fit inside the contract", codes: ["BUDGET_EXCEEDS_CONTRACT"] },
  { id: "planner", label: "Planner is available", codes: ["PLANNER_UNKNOWN"] },
];

export type ChecklistInput = {
  campaign: Pick<CampaignView, "state"> | null;
  contract: Pick<ContractSummary, "approved" | "approvedBy" | "approvalsRequired"> | null;
  fixture: FixtureView | null;
  /** Reasons from the latest validate response or from a refused arm (error.details.reasons). null = never checked. */
  serverReasons: Reason[] | null;
  now: number; // epoch ms
  wiringConfirmed: boolean;
};

function healthAgeS(fixture: FixtureView | null, now: number): number | null {
  if (!fixture?.healthAt) return null;
  const t = Date.parse(fixture.healthAt);
  return Number.isNaN(t) ? null : Math.max(0, (now - t) / 1000);
}

/** Conditions the Console can already see from the fixture and contract; the server's own reasons then override. */
function localFailures(input: ChecklistInput): Reason[] {
  const out: Reason[] = [];
  const { contract, fixture, now } = input;
  if (contract && !contract.approved) out.push({ code: "CONTRACT_NOT_APPROVED", message: `contract has ${contract.approvedBy.length} of ${contract.approvalsRequired} required approvals` });
  if (fixture) {
    const cal = fixture.calibration;
    if (!cal) out.push({ code: "CALIBRATION_MISSING", message: "the fixture has no calibration" });
    else if (Date.parse(cal.validUntil) <= now) out.push({ code: "CALIBRATION_EXPIRED", message: "the fixture's calibration has expired" });
    const h: BenchHealth | null = fixture.health;
    const age = healthAgeS(fixture, now);
    if (!h || age === null) out.push({ code: "BENCH_HEALTH_UNKNOWN", message: "the bench has not reported its health" });
    else {
      if (age > HEALTH_MAX_AGE_S) out.push({ code: "BENCH_HEALTH_STALE", message: `the bench health report is ${age.toFixed(0)} s old (limit ${HEALTH_MAX_AGE_S} s)` });
      if (!h.estopReleased) out.push({ code: "ESTOP_PRESSED", message: "the E-stop is pressed" });
      if (!h.interlockHealthy) out.push({ code: "INTERLOCK_UNHEALTHY", message: "the hardware interlock is not healthy" });
      if (!h.watchdogHealthy) out.push({ code: "WATCHDOG_UNHEALTHY", message: "the watchdog is not healthy" });
      if (!h.outputsInShutdown) out.push({ code: "OUTPUTS_ENERGIZED", message: "programmable outputs are not in shutdown" });
      if (!h.adaptersCompatible) out.push({ code: "ADAPTER_INCOMPATIBLE", message: "adapter capabilities are incompatible" });
      if (h.tripActive) out.push({ code: "TRIP_ACTIVE", message: "an unresolved trip is active" });
    }
  }
  return out;
}

export type Checklist = {
  conditions: Condition[];
  /** Reasons whose code the Console does not know; they still block arming. */
  other: Reason[];
  armable: boolean;
  blockers: string[];
};

export function buildChecklist(input: ChecklistInput): Checklist {
  const reasons = [...localFailures(input), ...(input.serverReasons ?? [])];
  const seen = new Set<string>();
  const unique = reasons.filter(r => { const k = r.code + "|" + r.message; if (seen.has(k)) return false; seen.add(k); return true; });
  const known = new Set(DEFS.flatMap(d => d.codes));
  const other = unique.filter(r => !known.has(r.code));
  const sourcesKnown = (id: string): boolean => {
    switch (id) {
      case "contract": return input.contract !== null || input.serverReasons !== null;
      case "fixture": case "budget": case "planner": return input.serverReasons !== null;
      case "firmware": return input.fixture?.health != null || input.serverReasons !== null;
      case "calibration": return input.fixture !== null;
      default: return input.fixture !== null;
    }
  };
  const conditions: Condition[] = DEFS.map(def => {
    const messages = unique.filter(r => def.codes.includes(r.code)).map(r => r.message);
    const status: ConditionStatus = messages.length ? "fail" : sourcesKnown(def.id) ? "pass" : "unknown";
    return { id: def.id, label: def.label, status, messages };
  });
  const blockers: string[] = [];
  if (!input.campaign) blockers.push("The campaign has not loaded.");
  else if (input.campaign.state !== "READY") blockers.push(`The campaign is ${input.campaign.state}; only a READY campaign can be armed. Validate it first.`);
  for (const c of conditions) if (c.status !== "pass") blockers.push(c.status === "unknown" ? `${c.label}: not checked yet.` : `${c.label}: ${c.messages.join("; ")}`);
  for (const r of other) blockers.push(r.message);
  if (!input.wiringConfirmed) blockers.push("Confirm that the fixture wiring matches the contract.");
  return { conditions, other, armable: blockers.length === 0, blockers };
}
