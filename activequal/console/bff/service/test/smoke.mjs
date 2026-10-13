import assert from "node:assert/strict";
import * as protoLoader from "@grpc/proto-loader";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createServer, makePreviewHandler, protoPath } = require("../dist/server.js");
const definition = protoLoader.loadSync(protoPath, { enums: String, defaults: true });
assert.ok(definition["chipcheck.console.v1.ConsoleService"]);
assert.ok(createServer());
const call = { request: { setup: { name: "OLED demo", rail: { name: "OLED rail" }, additionalRails: [{ name: "Sensor rail" }], observations: "frame latency" } } };
const handler = makePreviewHandler(async () => ({ source: "decision", setupName: "OLED demo", method: "tpe", historyUsed: 0, tests: [
  { id: "candidate-1", reason: "Startup coverage", conditions: { railVolts: 3.2, sensorRailVolts: 3.3, redLed: "on", greenLed: "off", workload: "oled_refresh" } }
] }));
const response = await new Promise((resolve, reject) => handler(call, (error, value) => error ? reject(error) : resolve(value)));
assert.equal(response.source, "PROPOSAL_SOURCE_DECISION");
assert.equal(response.setupName, "OLED demo");
assert.equal(response.tests.length, 1);
assert.match(response.tests[0].requested[0], /OLED rail/);
assert.match(response.tests[0].requested[1], /Sensor rail/);
assert.equal(response.tests[0].conditions.railVolts, 3.2);
console.log("BFF protobuf and Decision response mapping smoke test passed");
