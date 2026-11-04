import { NextRequest, NextResponse } from "next/server";
import { SetupDraft } from "@/lib/types";

export const runtime = "nodejs";

type Conditions = { railVolts: number; sensorRailVolts?: number; redLed: string; greenLed: string; workload: string };
type DecisionResponse = { setupName: string; method: string; historyUsed: number;
  tests: { id: string; conditions: Conditions; reason: string }[] };

function toRequest(draft: SetupDraft) {
  const options = (value: string) => (value || "").split(",").map(item => item.trim().toLowerCase()).filter(Boolean);
  return { method: draft.plannerMethod, seed: Number(draft.plannerSeed), count: 3, warmupTrials: 8, setup: {
    name: draft.name, dut: draft.dut, firmware: draft.firmware,
    fixture: draft.fixture, wiring: draft.wiring,
    rail: { name: draft.railName, minimumVolts: Number(draft.railMin), maximumVolts: Number(draft.railMax), stepVolts: Number(draft.railStep) },
    additionalRails: draft.sensorRailName?.trim() ? [{ name: draft.sensorRailName, minimumVolts: Number(draft.sensorRailMin), maximumVolts: Number(draft.sensorRailMax), stepVolts: Number(draft.sensorRailStep) }] : [],
    ledStates: `red: ${draft.redLedOptions}; green: ${draft.greenLedOptions}`, workloads: draft.workloads,
    redLedOptions: options(draft.redLedOptions), greenLedOptions: options(draft.greenLedOptions), workloadOptions: options(draft.workloads),
    settleMs: Number(draft.settleMs), durationMs: Number(draft.durationMs),
    observations: draft.observations, requirement: draft.requirement,
    forbiddenCombinations: draft.forbiddenCombinations,
    safety: { maximumVolts: Number(draft.maxVoltage), maximumAmps: Number(draft.maxCurrent), maximumCelsius: Number(draft.maxTemperature), safeReturnState: draft.safeState },
    experimentBudget: Number(draft.experimentBudget)
  } };
}

export async function POST(request: NextRequest) {
  let draft: SetupDraft;
  try { draft = await request.json() as SetupDraft; }
  catch { return NextResponse.json({ error: "Invalid configuration JSON" }, { status: 400 }); }
  if (!draft || typeof draft.name !== "string" || !draft.name.trim() ||
      typeof draft.railName !== "string" || typeof draft.redLedOptions !== "string" ||
      typeof draft.greenLedOptions !== "string" || typeof draft.workloads !== "string") {
    return NextResponse.json({ error: "Setup name, rail, LED options, and workloads are required" }, { status: 400 });
  }

  // The Decision Service proposes candidates only. It does not approve them or operate hardware.
  const url = process.env.CHIPCHECK_DECISION_URL ?? "http://127.0.0.1:8001/v1/proposals";
  const payload = toRequest(draft);
  try {
    const response = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload), signal: AbortSignal.timeout(15000)
    });
    const body = await response.json() as DecisionResponse & { error?: string };
    if (!response.ok) {
      return NextResponse.json({ error: `Could not load proposed tests: ${body.error || `Decision Service returned ${response.status}`}` },
                               { status: response.status === 400 ? 400 : 503 });
    }
    const railName = payload.setup.rail.name || "Rail";
    const sensorName = payload.setup.additionalRails[0]?.name || "Sensor rail";
    return NextResponse.json({
      source: "PROPOSAL_SOURCE_DECISION",
      setupName: body.setupName,
      method: body.method,
      historyUsed: body.historyUsed,
      tests: body.tests.map((test, index) => ({
        id: test.id,
        title: `Candidate ${index + 1}`,
        purpose: "Unapproved proposed test conditions",
        reason: test.reason,
        requested: [`${railName}: ${test.conditions.railVolts} V`,
                    ...(test.conditions.sensorRailVolts !== undefined ? [`${sensorName}: ${test.conditions.sensorRailVolts} V`] : []),
                    `Red LED: ${test.conditions.redLed}`, `Green LED: ${test.conditions.greenLed}`,
                    `Workload: ${test.conditions.workload}`],
        expectedObservations: [payload.setup.observations || "Configured observations"],
        conditions: test.conditions
      }))
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Decision Service unavailable";
    return NextResponse.json({ error: `Could not load proposed tests: ${message}` }, { status: 503 });
  }
}
