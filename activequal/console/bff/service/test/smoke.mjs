import assert from "node:assert/strict";
import * as protoLoader from "@grpc/proto-loader";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createServer, previewProposedTests, protoPath } = require("../dist/server.js");
const definition = protoLoader.loadSync(protoPath, { enums: String, defaults: true });
assert.ok(definition["chipcheck.console.v1.ConsoleService"]);
assert.ok(createServer());
const call = { request: { setup: { name: "OLED demo", rail: { name: "OLED rail" }, workloads: "OLED refresh", observations: "frame latency" } } };
const response = await new Promise((resolve, reject) => previewProposedTests(call, (error, value) => error ? reject(error) : resolve(value)));
assert.equal(response.source, "PROPOSAL_SOURCE_MOCK");
assert.equal(response.setupName, "OLED demo");
assert.equal(response.tests.length, 2);
assert.match(response.tests[0].requested[0], /OLED rail/);
console.log("BFF protobuf and handler smoke test passed");
