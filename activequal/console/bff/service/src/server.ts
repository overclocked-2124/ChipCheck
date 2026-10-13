import path from "node:path";
import * as grpc from "@grpc/grpc-js";
import * as protoLoader from "@grpc/proto-loader";

type Setup = {
  name?: string;
  rail?: { name?: string };
  workloads?: string;
  ledStates?: string;
  observations?: string;
  requirement?: string;
};

type Request = { setup?: Setup };

export const protoPath = path.resolve(__dirname, "../../api/proto/chipcheck/console/v1/console.proto");

export function previewProposedTests(call: grpc.ServerUnaryCall<Request, unknown>, callback: grpc.sendUnaryData<unknown>) {
  const setup = call.request.setup;
  if (!setup?.name?.trim()) {
    callback({ code: grpc.status.INVALID_ARGUMENT, message: "setup.name is required" });
    return;
  }

  // Fixed presentation examples. The Backend/Agent/Decision services will own
  // validation, candidate selection, and approval in later milestones.
  callback(null, {
    source: "PROPOSAL_SOURCE_MOCK",
    setupName: setup.name,
    tests: [
      {
        id: "preview-1",
        title: "Nominal setup check",
        purpose: "Preview the first proposed experiment after configuration.",
        requested: [setup.rail?.name ? `${setup.rail.name}: within entered range` : "Configured controls", setup.workloads || "Configured workload"],
        expectedObservations: [setup.observations || "Configured observations"]
      },
      {
        id: "preview-2",
        title: "Range exploration",
        purpose: "Show how a subsequent proposal could be presented.",
        requested: [setup.rail?.name ? `${setup.rail.name}: another allowed setting` : "Another allowed setting", setup.ledStates || "Configured states"],
        expectedObservations: [setup.requirement || "Configured requirement"]
      }
    ]
  });
}

export function createServer(): grpc.Server {
  const definition = protoLoader.loadSync(protoPath, {
    keepCase: false,
    longs: String,
    enums: String,
    defaults: true,
    oneofs: true
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
