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
  return { setup: {
    name: draft.name, dut: draft.dut, firmware: draft.firmware,
    fixture: draft.fixture, wiring: draft.wiring,
    rail: { name: draft.railName, minimumVolts: Number(draft.railMin), maximumVolts: Number(draft.railMax), stepVolts: Number(draft.railStep) },
    ledStates: draft.ledStates, workloads: draft.workloads,
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
  if (!draft || typeof draft.name !== "string" || !draft.name.trim()) {
    return NextResponse.json({ error: "A setup name is required" }, { status: 400 });
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
    return NextResponse.json({ error: `Could not load proposed tests: ${message}` }, { status: 503 });
  } finally { client.close(); }
}
