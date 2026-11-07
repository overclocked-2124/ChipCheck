import assert from "node:assert/strict";
import { test } from "node:test";
import { allowedActions, stateTone } from "../src/lib/actions.ts";
import { buildChecklist, type ChecklistInput } from "../src/lib/arming.ts";
import { applyForm, parseContractText, readForm } from "../src/lib/contractForm.ts";
import { OLED_TEMPLATE } from "../src/lib/contractTemplate.ts";
import { errorText, isUnreachable, translateError } from "../src/lib/errors.ts";
import { activeEpisode, benchStatus, connectionBanner, lockoutInfo, mergeEvents, shutdownStatus, stopExplanation } from "../src/lib/live.ts";
import { compareCampaigns, replaysFor, requestedVsMeasured, resultStatement } from "../src/lib/results.ts";
import { buildSeries, scale } from "../src/lib/series.ts";
import type { CampaignEvent, CampaignState, CampaignView, Counterexample, FixtureView, HistoryEpisode } from "../src/lib/types.ts";

// ---------------------------------------------------------------- errors
test("translateError keeps code, message, reasons and version; drops details and tracebacks", () => {
  const e = translateError(412, { error: { code: "FAILED_PRECONDITION", message: "cannot arm", details: { reasons: [{ code: "ESTOP_PRESSED", message: "the E-stop is pressed" }, { bogus: 1 }], path: "/home/x" } } });
  assert.deepEqual(e, { code: "FAILED_PRECONDITION", message: "cannot arm", status: 412, reasons: [{ code: "ESTOP_PRESSED", message: "the E-stop is pressed" }] });
  assert.match(errorText(e), /E-stop/);
  const stale = translateError(409, { error: { code: "STALE_VERSION", message: "changed", details: { currentVersion: 7 } } });
  assert.equal(stale.currentVersion, 7);
  const trace = translateError(500, { error: { code: "INTERNAL", message: "Traceback (most recent call last):\n  File \"x.py\"" } });
  assert.doesNotMatch(trace.message, /Traceback/);
  assert.equal(translateError(500, "<html>boom</html>").code, "INTERNAL");
  assert.equal(translateError(401, null).code, "UNAUTHENTICATED");
  assert.equal(isUnreachable({ code: "CONTROL_PLANE_UNREACHABLE", message: "", status: 502 }), true);
  assert.equal(isUnreachable({ code: "NOT_FOUND", message: "", status: 404 }), false);
});

// ---------------------------------------------------------------- allowed actions
const ALL_STATES: CampaignState[] = ["DRAFT", "VALIDATING", "READY", "ARMED", "RUNNING", "PAUSING", "PAUSED", "ABORTING", "ABORTED", "COMPLETED", "LOCKED_OUT"];
test("canonical campaign state maps to exactly the HLD 03 §6 researcher actions", () => {
  const expected: Record<CampaignState, string[]> = {
    DRAFT: ["validate"], VALIDATING: [], READY: ["validate", "arm"], ARMED: ["start", "disarm"], RUNNING: ["pause", "abort"],
    PAUSING: ["abort"], PAUSED: ["resume", "abort"], ABORTING: [], ABORTED: [], COMPLETED: [], LOCKED_OUT: ["clear-lockout"],
  };
  for (const s of ALL_STATES) assert.deepEqual(allowedActions(s).map(a => a.action), expected[s], s);
  assert.equal(allowedActions("LOCKED_OUT")[0].reviewer, true);
  assert.equal(allowedActions("READY").find(a => a.action === "arm")?.checklistOnly, true);
  assert.equal(allowedActions("RUNNING").find(a => a.action === "abort")?.danger, true);
  assert.equal(stateTone("LOCKED_OUT"), "bad");
  assert.notEqual(stateTone("ABORTED"), "ok");
});

// ---------------------------------------------------------------- arming checklist
const NOW = Date.parse("2026-11-07T12:00:00Z");
const healthy = { estopReleased: true, interlockHealthy: true, watchdogHealthy: true, outputsInShutdown: true, adaptersCompatible: true, tripActive: false, dutFirmwareSha256: "a", mcuFirmwareSha256: "b" };
const fixture = (over: Partial<FixtureView> = {}): FixtureView => ({
  id: "bench-A", revision: "A", capabilities: ["supply.ch2"], approvedMcuFirmwareSha256: null,
  calibration: { id: "cal1", channels: {}, meter: "m", operator: "o", createdAt: "2026-11-07T00:00:00Z", validUntil: "2026-12-01T00:00:00Z" },
  health: healthy, healthAt: "2026-11-07T11:59:58Z", ...over,
});
const input = (over: Partial<ChecklistInput> = {}): ChecklistInput => ({
  campaign: { state: "READY" }, contract: { approved: true, approvedBy: ["a", "b"], approvalsRequired: 2 },
  fixture: fixture(), serverReasons: [], now: NOW, wiringConfirmed: true, ...over,
});

test("arming is possible only when every condition passes", () => {
  const ok = buildChecklist(input());
  assert.equal(ok.armable, true);
  assert.ok(ok.conditions.every(c => c.status === "pass"));
});

test("each failing condition blocks arming and is named with its reason", () => {
  const cases: [Partial<ChecklistInput>, string][] = [
    [{ fixture: fixture({ health: { ...healthy, estopReleased: false } }) }, "estop"],
    [{ fixture: fixture({ health: { ...healthy, watchdogHealthy: false } }) }, "interlock"],
    [{ fixture: fixture({ health: { ...healthy, outputsInShutdown: false } }) }, "outputs"],
    [{ fixture: fixture({ health: { ...healthy, tripActive: true } }) }, "trip"],
    [{ fixture: fixture({ healthAt: "2026-11-07T11:58:00Z" }) }, "health"],
    [{ fixture: fixture({ health: null, healthAt: null }) }, "health"],
    [{ fixture: fixture({ calibration: null }) }, "calibration"],
    [{ contract: { approved: false, approvedBy: ["a"], approvalsRequired: 2 } }, "contract"],
    [{ serverReasons: [{ code: "DUT_FIRMWARE_MISMATCH", message: "the DUT firmware does not match the contract" }] }, "firmware"],
    [{ serverReasons: [{ code: "BUDGET_EXCEEDS_CONTRACT", message: "too big" }] }, "budget"],
  ];
  for (const [over, id] of cases) {
    const list = buildChecklist(input(over));
    assert.equal(list.armable, false, id);
    const c = list.conditions.find(x => x.id === id)!;
    assert.equal(c.status, "fail", id);
    assert.ok(c.messages.length > 0, id);
  }
});

test("unknown reason codes, a missing fixture, a missing wiring check and non-READY states all block arming", () => {
  assert.equal(buildChecklist(input({ serverReasons: [{ code: "SOMETHING_NEW", message: "new rule" }] })).armable, false);
  assert.deepEqual(buildChecklist(input({ serverReasons: [{ code: "SOMETHING_NEW", message: "new rule" }] })).other.map(r => r.code), ["SOMETHING_NEW"]);
  assert.equal(buildChecklist(input({ fixture: null })).armable, false);
  assert.equal(buildChecklist(input({ wiringConfirmed: false })).armable, false);
  assert.equal(buildChecklist(input({ serverReasons: null })).armable, false);
  for (const state of ALL_STATES.filter(s => s !== "READY")) assert.equal(buildChecklist(input({ campaign: { state } })).armable, false, state);
  assert.equal(buildChecklist(input({ campaign: null })).armable, false);
});

// ---------------------------------------------------------------- series
const ep = (id: string, conditions: HistoryEpisode["conditions"], outcome: HistoryEpisode["outcome"], robustness: number | null, role: HistoryEpisode["role"] = "discovery", linked: string | null = null): HistoryEpisode =>
  ({ episodeId: id, role, outcome, linkedEpisodeId: linked, conditions, robustness });

test("buildSeries picks the voltage control, keeps no-margin episodes apart, and does not invent values", () => {
  const eps = [
    ep("e1", { dwellMs: 500, oledRailV: 3.3, workload: "idle" }, "PASS", 0.9),
    ep("e2", { dwellMs: 600, oledRailV: 3.0, workload: "flash_write" }, "DUT_FAILURE", -0.4),
    ep("e3", { dwellMs: 700, oledRailV: 3.1, workload: "idle" }, "INVALID_EXPERIMENT", null),
  ];
  const s = buildSeries(eps);
  assert.equal(s.control, "oledRailV");
  assert.deepEqual(s.numericControls, ["dwellMs", "oledRailV"]);
  assert.deepEqual(s.points.map(p => p.x), [3.3, 3.0, 3.1]);
  assert.deepEqual(s.noMargin.map(p => p.episodeId), ["e3"]);
  assert.deepEqual(s.xRange, [3.0, 3.3]);
  assert.deepEqual(s.yRange, [-1, 1]);
  assert.equal(buildSeries(eps, "dwellMs").control, "dwellMs");
  assert.equal(buildSeries(eps, "workload").control, "oledRailV");
  assert.equal(buildSeries(eps, undefined, ["confirm"]).points.length, 0);
  assert.equal(buildSeries([]).control, null);
  assert.equal(scale(5, [0, 10], [0, 100]), 50);
  assert.equal(scale(5, [5, 5], [0, 100]), 50);
});

// ---------------------------------------------------------------- live
let nextId = 0;
const ev = (over: Partial<CampaignEvent>): CampaignEvent => ({
  id: ++nextId, entity: "episode", episodeId: null, attempt: null, previousState: null, newState: "", actorType: "system",
  actorId: "system", reasonCode: "", reason: "", backendTs: "2026-11-07T12:00:00Z", contractHash: null, fixtureId: null, ...over,
});

test("activeEpisode finds the unfinished episode, its phase and lease owner from events", () => {
  nextId = 0;
  const events = [
    ev({ episodeId: "e1", newState: "AVAILABLE" }),
    ev({ episodeId: "e1", newState: "LEASED", reasonCode: "LEASE_ISSUED", reason: "leased to controller-77", backendTs: "2026-11-07T12:00:01Z" }),
    ev({ episodeId: "e1", newState: "SETTLING", reasonCode: "PHASE_REPORTED", reason: "bench reported SETTLING", backendTs: "2026-11-07T12:00:03Z" }),
    ev({ episodeId: "e0", newState: "FINALIZED" }),
  ];
  const a = activeEpisode(events)!;
  assert.equal(a.episodeId, "e1");
  assert.equal(a.phase, "SETTLING");
  assert.equal(a.leaseOwner, "controller-77");
  assert.equal(a.lastHeartbeat, "2026-11-07T12:00:03Z");
  assert.equal(activeEpisode([...events, ev({ episodeId: "e1", newState: "FINALIZED" })]), null);
  const lost = activeEpisode([...events, ev({ entity: "lease", episodeId: "e1", newState: "NEEDS_RECONCILIATION", reason: "heartbeat arrived after expiry" })])!;
  assert.match(lost.leaseProblem ?? "", /expiry/);
});

test("mergeEvents is idempotent and ordered", () => {
  nextId = 100;
  const a = ev({}), b = ev({}), c = ev({});
  const merged = mergeEvents([a, c], [b, c, a]);
  assert.deepEqual(merged.map(e => e.id), [a.id, b.id, c.id]);
  assert.equal(mergeEvents(merged, []), merged);
});

test("a stopped campaign always has a visible reason from its final event", () => {
  nextId = 0;
  const events = [
    ev({ entity: "campaign", newState: "RUNNING", reasonCode: "STARTED", reason: "researcher started the campaign" }),
    ev({ entity: "campaign", newState: "LOCKED_OUT", reasonCode: "BENCH_REPORTED_TRIP", reason: "trip reported by the bench", actorId: "system" }),
  ];
  const s = stopExplanation("LOCKED_OUT", events)!;
  assert.equal(s.reasonCode, "BENCH_REPORTED_TRIP");
  assert.match(s.reason, /trip/);
  assert.equal(stopExplanation("RUNNING", events), null);
  assert.match(stopExplanation("ABORTED", [])!.headline, /no event explains/i);
  const lock = lockoutInfo("LOCKED_OUT", events)!;
  assert.match(lock.cause, /trip/);
  assert.ok(lock.checklist.length >= 4);
  assert.equal(lockoutInfo("RUNNING", events), null);
});

test("shutdown confirmation and bench status never default to safe", () => {
  assert.equal(shutdownStatus(null, [], "RUNNING").confirmed, null);
  assert.equal(shutdownStatus(null, [], "ABORTING").confirmed, false);
  assert.equal(shutdownStatus({ ...healthy, outputsInShutdown: false }, [], "RUNNING").confirmed, false);
  nextId = 0;
  const ack = ev({ entity: "lease", reasonCode: "ABORT_ACKNOWLEDGED", reason: "bench confirmed shutdown" });
  assert.equal(shutdownStatus(healthy, [ack], "ABORTED").confirmed, true);
  assert.deepEqual(benchStatus(null).map(l => l.ok), [null, null, null, null]);
  assert.equal(benchStatus(fixture({ health: { ...healthy, estopReleased: false } })).find(l => l.id === "estop")?.ok, false);
});

test("unreachable control plane yields an unknown-state banner and never a stopped/safe claim", () => {
  const text = connectionBanner("unreachable", "RUNNING", NOW - 5000, NOW)!;
  assert.match(text, /bench state unknown/i);
  assert.match(text, /RUNNING/);
  assert.doesNotMatch(text, /is (stopped|safe)/i);
  assert.equal(connectionBanner("live", "RUNNING", NOW, NOW), null);
  assert.equal(connectionBanner("polling", "RUNNING", NOW, NOW), null);
});

// ---------------------------------------------------------------- results
const campaign = (over: Partial<CampaignView> = {}): CampaignView => ({
  id: "c1", state: "COMPLETED", version: 5, contractVersionId: "v", contractHash: "h1", fixtureId: "bench-A",
  planner: { method: "tpe", config: {} }, seed: 1, plan: {}, budget: { discovery: 50, verification: 24, discoveryUsed: 10, verificationUsed: 4 },
  episodesByOutcome: { PASS: 9, DUT_FAILURE: 1 }, candidatesRejected: 0, softwareVersion: "dev", ...over,
});
const cx: Counterexample = {
  id: "x1", originalEpisodeId: "e2", reproductions: 3, attempts: 3, origin: "seeded",
  minimized: { conditions: { oledRailV: 3.0 }, removed: ["redLed"], kept: ["oledRailV"], necessity: { greenLed: "not_necessary" } },
  intervals: { intervals: {}, budgetExhausted: false },
};

test("result language follows PRD 19.2 and never says safe", () => {
  assert.match(resultStatement(campaign(), [cx]).text, /^Counterexample found \(seeded fault\).*reproduced 3 of 3/);
  const none = resultStatement(campaign({ episodesByOutcome: { PASS: 20 } }), []);
  assert.equal(none.kind, "none");
  assert.match(none.text, /^No counterexample found within budget: 20 valid/);
  assert.doesNotMatch(none.text, /\bis safe\b|certified/i);
  assert.equal(resultStatement(campaign({ episodesByOutcome: { PASS: 3, INVALID_EXPERIMENT: 9 } }), []).kind, "inconclusive");
  assert.equal(resultStatement(campaign({ state: "LOCKED_OUT", episodesByOutcome: { SAFETY_ABORT: 1 } }), []).kind, "safety");
  assert.equal(resultStatement(campaign({ state: "RUNNING" }), []).kind, "running");
});

test("replays group by the counterexample's original episode; requested and measured stay separate", () => {
  const eps = [ep("e1", { v: 3.3 }, "PASS", 1), ep("e2", { v: 3.0 }, "DUT_FAILURE", -1), ep("r1", { v: 3.0 }, "DUT_FAILURE", -1, "confirm", "e2"), ep("r2", { v: 3.3 }, "PASS", 1, "bracket", "e2"), ep("o", { v: 3 }, "PASS", 1, "confirm", "other")];
  assert.deepEqual(replaysFor(eps, cx).map(r => r.episodeId), ["r1", "r2"]);
  const rm = requestedVsMeasured({ requested: { oledRailV: 3.0, workload: "idle" }, measured: { measuredOledRailV: { value: 2.98, uncertainty: 0.01, requested: 3.0 }, resetCount: { value: 0, uncertainty: null, requested: null } } });
  assert.deepEqual(rm.requested, [["oledRailV", "3"], ["workload", "idle"]]);
  assert.equal(rm.measured[0].measured, "2.98");
  assert.equal(rm.measured[0].requested, "3");
  assert.equal(rm.measured[1].requested, "n/a");
});

test("comparison counts discovery-pool episodes to first failure and warns about mixed contracts", () => {
  const a = { campaign: campaign({ id: "a" }), episodes: [ep("1", {}, "PASS", 1), ep("2", {}, "PASS", 1), ep("3", {}, "DUT_FAILURE", -1), ep("v", {}, "DUT_FAILURE", -1, "confirm", "3")] };
  const b = { campaign: campaign({ id: "b", planner: { method: "random", config: {} }, contractHash: "h2" }), episodes: [ep("1", {}, "PASS", 1)] };
  const cmp = compareCampaigns([a, b]);
  assert.equal(cmp.rows[0].firstFailureAt, 3);
  assert.equal(cmp.rows[0].censored, false);
  assert.equal(cmp.rows[1].firstFailureAt, null);
  assert.equal(cmp.rows[1].censored, true);
  assert.equal(cmp.sameContract, false);
  assert.ok(cmp.warnings.some(w => /different contract/.test(w)));
  const verifyFirst = compareCampaigns([{ campaign: campaign(), episodes: [ep("v", {}, "DUT_FAILURE", -1, "confirm", "x"), ep("d", {}, "PASS", 1)] }]);
  assert.equal(verifyFirst.rows[0].firstFailureAt, null, "verification episodes must not count");
});

// ---------------------------------------------------------------- contract form
test("contract text parsing and form round-trip", () => {
  assert.equal(parseContractText("{").ok, false);
  assert.equal(parseContractText("[]").ok, false);
  assert.match((parseContractText('{"contractVersion":1}') as { error: string }).error, /contractVersion must be 2/);
  assert.match((parseContractText('{"contractVersion":2}') as { error: string }).error, /Missing section/);
  const parsed = parseContractText(JSON.stringify(OLED_TEMPLATE));
  assert.equal(parsed.ok, true);
  if (!parsed.ok) return;
  const form = readForm(parsed.value);
  assert.equal(form.dut, "esp32s3-oled-demo");
  assert.equal(form.maxEpisodeS, "10");
  const edited = applyForm(parsed.value, { ...form, fixture: "bench-B", budget: "50" });
  assert.equal((edited.setup as { fixture: string }).fixture, "bench-B");
  assert.equal((edited.campaign as { budget: number }).budget, 50);
  assert.deepEqual(edited.controls, parsed.value.controls, "the form must not touch what it does not show");
  const blank = applyForm(parsed.value, { ...form, dut: "" });
  assert.equal((blank.setup as { dut: string }).dut, "esp32s3-oled-demo");
});
