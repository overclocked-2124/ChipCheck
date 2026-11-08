import assert from "node:assert/strict";
import { test } from "node:test";
import { describeRequirement, describeRule, jsonDiff } from "../src/lib/contractView.ts";
import { controlInputs } from "../src/lib/manual.ts";
import { countBy, outcomeStrip, toHistory, tracksFrom, verificationGroups } from "../src/lib/region.ts";
import { OLED_TEMPLATE } from "../src/lib/contractTemplate.ts";
import type { EpisodeRecord, JsonValue } from "../src/lib/types.ts";

function rec(seq: number, over: Partial<EpisodeRecord> = {}): EpisodeRecord {
  return {
    episodeId: `e${seq}`, attempt: 1, role: "discovery", pool: "discovery", state: "FINALIZED", outcome: "PASS",
    linkedEpisodeId: null, plannerSequence: seq, discoveryIndex: seq, requested: { oledRailV: 3.25, redLed: true },
    measured: { measuredOledRailV: { value: 3.248, uncertainty: 0.01, requested: 3.25 } },
    verdict: { outcome: "PASS", reasonCode: "ALL_REQUIREMENTS_MET", reason: "ok", margins: {}, robustness: 0.5, requirements: {} },
    planner: { method: "tpe", reason: "r", reasonCode: "MODEL", repeatReason: null }, quality: null, createdAt: "", finalizedAt: "",
    ...over,
  };
}

test("charts use measured values for tracked controls and never give invalid episodes a margin", () => {
  const tracks = tracksFrom({ validity: [{ metric: "measuredOledRailV", tracks: "oledRailV" }, { bad: 1 }] as JsonValue });
  assert.deepEqual(tracks, { oledRailV: "measuredOledRailV" });
  const invalid = rec(2, { outcome: "INVALID_EXPERIMENT", verdict: { outcome: "INVALID_EXPERIMENT", reasonCode: "RAIL_NOT_SETTLED", reason: "x", margins: {}, robustness: 0.3, requirements: {} } });
  const running = rec(3, { state: "EXECUTING", outcome: null, verdict: null });
  const h = toHistory([rec(1), invalid, running], tracks);
  assert.equal(h.length, 2);                                   // unfinished episodes are not plotted
  assert.equal(h[0].conditions.oledRailV, 3.248);              // measured, not the requested 3.25
  assert.equal(h[1].robustness, null);
  assert.deepEqual(toHistory([rec(1)], {})[0].conditions.oledRailV, 3.25);
});

test("outcome strip is in planner order; reasons are counted; verification groups by trigger", () => {
  const cells = outcomeStrip([rec(3), rec(1), rec(2, { role: "confirm", linkedEpisodeId: "e1", pool: "verification" })]);
  assert.deepEqual(cells.map(c => c.sequence), [1, 2, 3]);
  assert.match(cells[1].label, /confirm/);
  assert.deepEqual(countBy([{ c: "A" }, { c: "B" }, { c: "A" }, { c: null }], x => x.c), [["A", 2], ["B", 1]]);
  const groups = verificationGroups([rec(1), rec(4, { role: "bracket", linkedEpisodeId: "e1" }), rec(2, { role: "confirm", linkedEpisodeId: "e1" })]);
  assert.deepEqual(groups.map(g => [g.trigger, g.steps.map(s => s.plannerSequence)]), [["e1", [2, 4]]]);
});

test("manual inputs come from the contract controls", () => {
  const inputs = controlInputs(OLED_TEMPLATE as Record<string, JsonValue>);
  const byName = Object.fromEntries(inputs.map(i => [i.name, i]));
  assert.equal(byName.redLed.kind, "boolean");
  assert.equal(byName.workload.kind, "choice");
  const rail = byName.oledRailV;
  assert.ok(rail.kind === "number" && rail.min === 3.0 && rail.max === 3.6 && rail.step === 0.01 && rail.unit === "V");
  const flash = byName.flashOffsetMs;
  assert.ok(flash.kind === "number" && flash.activeWhen === "workload = flash_write");
});

test("contract rules read as text and versions diff by path", () => {
  assert.equal(describeRule({ all: [{ control: "workload", eq: "flash_write" }, { control: "sensorRailV", gte: 3.55 }] }), "workload = flash_write AND sensorRailV ≥ 3.55");
  assert.equal(describeRequirement({ metric: "x", op: "band", lo: 1, hi: 2 }), "1 ≤ x ≤ 2");
  assert.equal(describeRequirement({ metric: "oledLatencyMs", op: "<=", limit: 120 }), "oledLatencyMs <= 120");
  const diff = jsonDiff({ safety: { maxTempC: 60, channels: { a: { maxV: 3.6 } } }, list: [1, 2] },
                        { safety: { maxTempC: 45, channels: { a: { maxV: 3.6 } } }, list: [1], added: true });
  assert.deepEqual(diff, [
    { path: "added", before: "—", after: "true" },
    { path: "list[1]", before: "2", after: "—" },
    { path: "safety.maxTempC", before: "60", after: "45" },
  ]);
  assert.deepEqual(jsonDiff({ a: 1 }, { a: 1 }), []);
});

test("number fields: rules replace type=number checks, and steppers keep the step's precision", async () => {
  const { numberProblem, stepNumber } = await import("../src/lib/number.ts");
  assert.equal(numberProblem("abc", { integer: true }), "Whole number only");
  assert.equal(numberProblem("1.5", { integer: true }), "Whole number only");
  assert.equal(numberProblem("0", { integer: true, min: 1 }), "At least 1");
  assert.equal(numberProblem("", { integer: true }), "Required");
  assert.equal(numberProblem("3.25", { min: 3, max: 3.6 }), null);
  assert.equal(stepNumber("3.3", 1, 0.01, { min: 3, max: 3.6 }), "3.31");
  assert.equal(stepNumber("3.6", 1, 0.01, { min: 3, max: 3.6 }), "3.60");
  assert.equal(stepNumber("1", -1, 1, { min: 1 }), "1");
  assert.equal(stepNumber("0.1", 1, 0.1), "0.2");
});
