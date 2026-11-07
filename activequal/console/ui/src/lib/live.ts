// Derived live-campaign facts, computed only from the campaign's own event log and the fixture health.
// HLD 03 §22: current episode and phase, lease owner and heartbeat, shutdown confirmation, lockout cause, why it stopped.

import type { BenchHealth, CampaignEvent, CampaignState, FixtureView } from "./types.ts";

export type ConnectionState = "live" | "polling" | "unreachable" | "loading";

/** Merge events by id, keeping them ordered. Safe to call with duplicates from SSE plus polling. */
export function mergeEvents(current: CampaignEvent[], incoming: CampaignEvent[]): CampaignEvent[] {
  if (!incoming.length) return current;
  const byId = new Map<number, CampaignEvent>(current.map(e => [e.id, e]));
  for (const e of incoming) byId.set(e.id, e);
  return [...byId.values()].sort((a, b) => a.id - b.id);
}

export const lastEventId = (events: CampaignEvent[]): number => events.length ? events[events.length - 1].id : 0;

const PHASES = ["PREFLIGHT", "CONFIGURING", "SETTLING", "EXECUTING", "OBSERVING", "SHUTTING_DOWN", "EMERGENCY_CUTOFF", "LOCKOUT"];

export type ActiveEpisode = {
  episodeId: string; attempt: number | null; phase: string; phaseSince: string;
  leaseOwner: string | null; leaseIssuedAt: string | null; lastHeartbeat: string | null; lastHeartbeatKind: "phase report" | "lease issued" | null;
  leaseProblem: string | null;
};

/** The newest episode that is not FINALIZED, from the episode events. */
export function activeEpisode(events: CampaignEvent[]): ActiveEpisode | null {
  const last = new Map<string, CampaignEvent>();
  for (const e of events) if (e.entity === "episode" && e.episodeId) last.set(e.episodeId, e);
  let current: CampaignEvent | null = null;
  for (const e of last.values()) if (e.newState !== "FINALIZED" && (!current || e.id > current.id)) current = e;
  if (!current || !current.episodeId) return null;
  const mine = events.filter(e => e.episodeId === current!.episodeId);
  const issued = [...mine].reverse().find(e => e.reasonCode === "LEASE_ISSUED") ?? null;
  const owner = issued ? /leased to (.+)$/.exec(issued.reason)?.[1] ?? null : null;
  const beat = [...mine].reverse().find(e => e.reasonCode === "PHASE_REPORTED") ?? null;
  const lease = [...mine].reverse().find(e => e.entity === "lease") ?? null;
  const problem = lease && lease.newState === "NEEDS_RECONCILIATION" ? lease.reason : null;
  return {
    episodeId: current.episodeId, attempt: current.attempt, phase: current.newState, phaseSince: current.backendTs,
    leaseOwner: owner, leaseIssuedAt: issued?.backendTs ?? null,
    lastHeartbeat: (beat ?? issued)?.backendTs ?? null, lastHeartbeatKind: beat ? "phase report" : issued ? "lease issued" : null,
    leaseProblem: problem,
  };
}

export const isPhase = (state: string): boolean => PHASES.includes(state);

/** Latest campaign-level event: the reason the campaign is in its current state. */
export function finalCampaignEvent(events: CampaignEvent[]): CampaignEvent | null {
  return [...events].reverse().find(e => e.entity === "campaign" && e.newState !== "COUNTEREXAMPLE_RECORDED") ?? null;
}

export type StopExplanation = { headline: string; reasonCode: string; reason: string; actor: string; at: string };

const STOPPED: CampaignState[] = ["COMPLETED", "ABORTED", "LOCKED_OUT", "PAUSED", "ABORTING", "PAUSING"];

/** Why the campaign is not running, in words, from the final campaign event. Null while it is running or not started. */
export function stopExplanation(state: CampaignState, events: CampaignEvent[]): StopExplanation | null {
  if (!STOPPED.includes(state)) return null;
  const e = [...events].reverse().find(ev => ev.entity === "campaign" && ev.newState === state) ?? finalCampaignEvent(events);
  if (!e) return { headline: `Campaign is ${state}, but no event explains why.`, reasonCode: "NO_EVENT", reason: "The event log has no entry for this state.", actor: "unknown", at: "" };
  const headline = state === "COMPLETED" ? "Completed" : state === "ABORTED" ? "Aborted" : state === "LOCKED_OUT" ? "Locked out" : state === "PAUSED" ? "Paused" : state === "PAUSING" ? "Pausing" : "Aborting";
  return { headline, reasonCode: e.reasonCode, reason: e.reason, actor: e.actorId, at: e.backendTs };
}

export type ShutdownStatus = { confirmed: boolean | null; text: string };

/** Shutdown confirmation: the bench's own "outputs in shutdown" flag, plus a confirmed abort-ack event if any. */
export function shutdownStatus(health: BenchHealth | null, events: CampaignEvent[], state: CampaignState): ShutdownStatus {
  const ack = [...events].reverse().find(e => e.reasonCode === "ABORT_ACKNOWLEDGED");
  if (state === "ABORTING" && !ack) return { confirmed: false, text: "Waiting for the bench to confirm shutdown." };
  if (ack && (state === "ABORTED" || state === "ABORTING")) return { confirmed: true, text: `Bench confirmed shutdown at ${ack.backendTs}.` };
  if (!health) return { confirmed: null, text: "The bench has not reported its health, so outputs are not confirmed off." };
  return health.outputsInShutdown
    ? { confirmed: true, text: "Bench reports programmable outputs in shutdown (as of its last health report)." }
    : { confirmed: false, text: "Bench reports programmable outputs are NOT in shutdown." };
}

export type BenchLine = { id: string; label: string; ok: boolean | null; detail: string };

export function benchStatus(fixture: FixtureView | null): BenchLine[] {
  const h = fixture?.health ?? null;
  const flag = (id: string, label: string, v: boolean | undefined, good: string, bad: string): BenchLine =>
    ({ id, label, ok: v === undefined ? null : v, detail: v === undefined ? "not reported" : v ? good : bad });
  return [
    flag("estop", "E-stop", h?.estopReleased, "released", "PRESSED"),
    flag("watchdog", "Watchdog", h?.watchdogHealthy, "healthy", "NOT healthy"),
    flag("interlock", "Interlock", h?.interlockHealthy, "healthy", "NOT healthy"),
    flag("trip", "Trip", h === null ? undefined : !h.tripActive, "none active", "TRIP ACTIVE"),
  ];
}

export function ageSeconds(iso: string | null | undefined, now: number): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : Math.max(0, (now - t) / 1000);
}

export function formatAge(seconds: number | null): string {
  if (seconds === null) return "never";
  if (seconds < 90) return `${seconds.toFixed(0)} s ago`;
  if (seconds < 5400) return `${(seconds / 60).toFixed(0)} min ago`;
  return `${(seconds / 3600).toFixed(1)} h ago`;
}

export type LockoutInfo = { cause: string; code: string; at: string; actor: string; checklist: string[] };

export const LOCKOUT_CHECKLIST = [
  "Confirm the programmable supplies are off and no output is energized.",
  "Inspect the DUT, wiring and connectors for heat, damage or loose leads.",
  "Check what tripped (E-stop, over-current, over-voltage, temperature, watchdog) and fix the cause.",
  "Reset the hardware interlock by hand at the fixture.",
  "Review the preserved measurements for the last episode before clearing.",
];

/** Lockout cause from the LOCKED_OUT event. HLD 03 §13: the Console displays the reason and the physical checks. */
export function lockoutInfo(state: CampaignState, events: CampaignEvent[]): LockoutInfo | null {
  if (state !== "LOCKED_OUT") return null;
  const e = [...events].reverse().find(ev => ev.entity === "campaign" && ev.newState === "LOCKED_OUT");
  return { cause: e?.reason ?? "No event explains the lockout; treat the fixture as unsafe until inspected.", code: e?.reasonCode ?? "UNKNOWN", at: e?.backendTs ?? "", actor: e?.actorId ?? "", checklist: LOCKOUT_CHECKLIST };
}

/** Never imply the bench is stopped or safe when the control plane cannot be reached. */
export function connectionBanner(conn: ConnectionState, lastKnown: CampaignState | null, lastOkAt: number | null, now: number): string | null {
  if (conn !== "unreachable") return null;
  const when = lastOkAt ? ` Last contact ${Math.round((now - lastOkAt) / 1000)} s ago` + (lastKnown ? `, when the campaign was ${lastKnown}.` : ".") : "";
  return "Control plane unreachable: bench state unknown." + when + " Do not assume the bench has stopped or is safe; check the fixture and the E-stop in person.";
}
