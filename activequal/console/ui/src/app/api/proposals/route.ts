import path from "node:path";
import * as grpc from "@grpc/grpc-js";
import * as protoLoader from "@grpc/proto-loader";
import { NextRequest, NextResponse } from "next/server";
import { SetupDraft } from "@/lib/types";

export const runtime = "nodejs";

type Client = grpc.Client & {
  previewProposedTests(request: unknown, callback: (error: grpc.ServiceError | null, response: unknown) => void): void;
};

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

  const proto = path.resolve(process.cwd(), "../bff/api/proto/chipcheck/console/v1/console.proto");
  const definition = protoLoader.loadSync(proto, { keepCase: false, longs: String, enums: String, defaults: true });
  const root = grpc.loadPackageDefinition(definition) as unknown as {
    chipcheck: { console: { v1: { ConsoleService: new (address: string, credentials: grpc.ChannelCredentials) => Client } } }
  };
  const address = process.env.CHIPCHECK_BFF_ADDRESS ?? "127.0.0.1:50051";
  const client = new root.chipcheck.console.v1.ConsoleService(address, grpc.credentials.createInsecure());
  try {
    const result = await new Promise<unknown>((resolve, reject) => {
      client.previewProposedTests(toRequest(draft), (error, response) => error ? reject(error) : resolve(response));
    });
    return NextResponse.json(result);
  } catch (error) {
    const message = error instanceof Error ? error.message : "BFF unavailable";
    return NextResponse.json({ error: `Could not load proposed tests: ${message}` }, { status: (error as grpc.ServiceError).code === grpc.status.INVALID_ARGUMENT ? 400 : 503 });
  } finally { client.close(); }
}
