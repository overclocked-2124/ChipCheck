import path from "node:path";
import * as grpc from "@grpc/grpc-js";
import * as protoLoader from "@grpc/proto-loader";

type Conditions = { railVolts: number; sensorRailVolts?: number; redLed: string; greenLed: string; workload: string };
type TestSetup = { name?: string; observations?: string; rail?: { name?: string }; additionalRails?: { name?: string }[]; [key: string]: unknown };
type Request = { setup?: TestSetup; method?: string; seed?: number; count?: number; warmupTrials?: number; history?: unknown[] };
type DecisionResponse = { source: string; setupName: string; method: string; historyUsed: number;
  tests: { id: string; conditions: Conditions; reason: string }[] };
type Selector = (request: Request) => Promise<DecisionResponse>;

export const protoPath = path.resolve(__dirname, "../../api/proto/chipcheck/console/v1/console.proto");

export async function queryDecision(request: Request): Promise<DecisionResponse> {
  const url = process.env.CHIPCHECK_DECISION_URL ?? "http://127.0.0.1:8001/v1/proposals";
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal: AbortSignal.timeout(5000)
  });
  const body = await response.json() as DecisionResponse & { error?: string };
  if (!response.ok) {
    const error = new Error(body.error || `Decision Service returned ${response.status}`) as grpc.ServiceError;
    error.code = response.status === 400 ? grpc.status.INVALID_ARGUMENT : grpc.status.UNAVAILABLE;
    throw error;
  }
  return body;
}

export function makePreviewHandler(select: Selector = queryDecision) {
  return async (call: grpc.ServerUnaryCall<Request, unknown>, callback: grpc.sendUnaryData<unknown>) => {
    const request = call.request;
    if (!request.setup?.name?.trim()) {
      callback({ code: grpc.status.INVALID_ARGUMENT, message: "setup.name is required" });
      return;
    }
    try {
      const result = await select(request);
      const railName = request.setup.rail?.name || "Rail";
      callback(null, {
        source: "PROPOSAL_SOURCE_DECISION",
        setupName: result.setupName,
        method: result.method,
        historyUsed: result.historyUsed,
        tests: result.tests.map((test, index) => ({
          id: test.id,
          title: `Candidate ${index + 1}`,
          purpose: "Unapproved proposed test conditions",
          reason: test.reason,
          requested: [`${railName}: ${test.conditions.railVolts} V`,
                      ...(test.conditions.sensorRailVolts !== undefined ? [`${request.setup?.additionalRails?.[0]?.name || "Sensor rail"}: ${test.conditions.sensorRailVolts} V`] : []),
                      `Red LED: ${test.conditions.redLed}`,
                      `Green LED: ${test.conditions.greenLed}`, `Workload: ${test.conditions.workload}`],
          expectedObservations: [request.setup?.observations || "Configured observations"],
          conditions: test.conditions
        }))
      });
    } catch (cause) {
      const error = cause as grpc.ServiceError;
      callback({ code: error.code === grpc.status.INVALID_ARGUMENT ? grpc.status.INVALID_ARGUMENT : grpc.status.UNAVAILABLE,
                 message: error.message || "Decision Service unavailable" });
    }
  };
}

export const previewProposedTests = makePreviewHandler();

export function createServer(): grpc.Server {
  const definition = protoLoader.loadSync(protoPath, {
    keepCase: false, longs: String, enums: String, defaults: true, oneofs: true
  });
  const root = grpc.loadPackageDefinition(definition) as unknown as {
    chipcheck: { console: { v1: { ConsoleService: { service: grpc.ServiceDefinition } } } }
  };
  const server = new grpc.Server();
  server.addService(root.chipcheck.console.v1.ConsoleService.service, { previewProposedTests });
  return server;
}

if (require.main === module) {
  const address = process.env.CHIPCHECK_BFF_LISTEN ?? "127.0.0.1:50051";
  createServer().bindAsync(address, grpc.ServerCredentials.createInsecure(), (error, port) => {
    if (error) { console.error(error); process.exitCode = 1; return; }
    console.log(`ChipCheck BFF gRPC listening on ${address} (port ${port})`);
  });
}
