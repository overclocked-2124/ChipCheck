// Result views assembled from control-plane responses. No statistics here: intervals, margins and
// reproduction counts are the Backend's and Agent's numbers, laid out for reading.

import type { CampaignView, Counterexample, EpisodeView, HistoryEpisode, JsonValue, Measured } from "./types.ts";

export type Replay = { episodeId: string; role: HistoryEpisode["role"]; outcome: HistoryEpisode["outcome"]; conditions: HistoryEpisode["conditions"] };

/** Verification episodes linked to each counterexample's original episode, in history order. */
export function replaysFor(episodes: HistoryEpisode[], cx: Counterexample): Replay[] {
  return episodes.filter(e => e.linkedEpisodeId === cx.originalEpisodeId && e.role !== "discovery")
    .map(e => ({ episodeId: e.episodeId, role: e.role, outcome: e.outcome, conditions: e.conditions }));
}

export function reproductionText(cx: Counterexample): string {
  return `reproduced ${cx.reproductions} of ${cx.attempts}`;
}

export type RequestedMeasuredRow = { name: string; requested: string; measured: string; uncertainty: string };

/** Requested vs measured, kept in separate columns (AGENTS.md: record requested and measured separately). */
export function requestedVsMeasured(ep: Pick<EpisodeView, "requested" | "measured">): { requested: [string, string][]; measured: RequestedMeasuredRow[] } {
  const requested = Object.entries(ep.requested).map(([k, v]): [string, string] => [k, formatValue(v)]);
  const measured = Object.entries(ep.measured).map(([name, m]: [string, Measured]) => ({
    name,
    requested: m.requested === null || m.requested === undefined ? "n/a" : formatValue(m.requested),
    measured: formatValue(m.value),
    uncertainty: m.uncertainty === null || m.uncertainty === undefined ? "n/a" : `+/- ${formatValue(m.uncertainty)}`,
  }));
  return { requested, measured };
}

export function formatValue(v: JsonValue | undefined): string {
  if (v === undefined || v === null) return "n/a";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Number(v.toPrecision(5)));
  return typeof v === "string" ? v : JSON.stringify(v);
}

/** PRD §19.2 result language. Never "safe", never "certified". */
export function resultStatement(campaign: CampaignView, counterexamples: Counterexample[]): { kind: "counterexample" | "none" | "inconclusive" | "safety" | "running"; text: string } {
  const by = campaign.episodesByOutcome;
  const total = Object.entries(by).filter(([k]) => k !== "IN_FLIGHT").reduce((a, [, n]) => a + n, 0);
  const invalid = by.INVALID_EXPERIMENT ?? 0, abort = by.SAFETY_ABORT ?? 0, valid = (by.PASS ?? 0) + (by.DUT_FAILURE ?? 0);
  const confirmed = counterexamples.filter(c => c.attempts > 0 && c.reproductions > 0);
  if (confirmed.length) {
    const c = confirmed[0];
    const label = c.origin === "seeded" ? " (seeded fault)" : c.origin === "natural" ? " (natural fault)" : "";
    return { kind: "counterexample", text: `Counterexample found${label}: a requirement failed at measured conditions; ${reproductionText(c)}.` };
  }
  if (campaign.state === "LOCKED_OUT") {
    return { kind: "safety", text: `Safety abort: ${abort} episode(s) ended by a safety trip; no further adaptive exploration was performed after it.` };
  }
  const failures = by.DUT_FAILURE ?? 0;
  if (campaign.state === "COMPLETED" || campaign.state === "ABORTED") {
    if (failures > 0) return { kind: "inconclusive", text: `Failure observed but not confirmed: ${failures} episode(s) failed, but no failure reproduced on replay.` };
    if (valid === 0 || (total > 0 && invalid / total >= 0.25)) return { kind: "inconclusive", text: `Campaign inconclusive: ${invalid}/${total} episodes invalid.` };
    const scope = campaign.state === "ABORTED" ? "before the campaign was aborted" : "within budget";
    const aborts = abort > 0 ? ` ${abort} episode(s) ended in a safety abort.` : "";
    return { kind: "none", text: `No counterexample found ${scope}: ${valid} valid episode(s) of ${total} run.${aborts} This says nothing about conditions that were not tested.` };
  }
  return { kind: "running", text: `Campaign is ${campaign.state}: ${total} episode(s) finished so far; no verdict on the campaign yet.` };
}
