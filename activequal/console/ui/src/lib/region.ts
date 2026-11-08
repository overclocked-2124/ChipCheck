// Episode records reshaped for the charts. Analysis uses measured values (PRD §11.5): a control that an observation
// tracks (the contract's validity rules) is plotted at its measured value; any other control at its requested value.
// No statistics: robustness, outcomes and conditions are the Backend's numbers.

import type { EpisodeRecord, HistoryEpisode, JsonValue } from "./types.ts";

export type Tracks = Record<string, string>;     // control -> observation that measures it

/** control -> observation, from the contract's `validity` rules (`{ metric, tracks }`). */
export function tracksFrom(contract: Record<string, JsonValue> | null | undefined): Tracks {
  const rules = contract && Array.isArray(contract.validity) ? contract.validity : [];
  const out: Tracks = {};
  for (const r of rules) {
    if (r && typeof r === "object" && !Array.isArray(r) && typeof r.tracks === "string" && typeof r.metric === "string") out[r.tracks] = r.metric;
  }
  return out;
}

/** Records as chart history; tracked controls take their measured value when the bench reported one. */
export function toHistory(records: EpisodeRecord[], tracks: Tracks): HistoryEpisode[] {
  return records.filter(r => r.state === "FINALIZED").map(r => {
    const conditions: HistoryEpisode["conditions"] = { ...r.requested };
    for (const [control, metric] of Object.entries(tracks)) {
      const m = r.measured[metric];
      if (m && typeof m.value === "number" && Number.isFinite(m.value)) conditions[control] = m.value;
    }
    const robustness = r.outcome === "PASS" || r.outcome === "DUT_FAILURE" ? r.verdict?.robustness ?? null : null;
    return { episodeId: r.episodeId, role: r.role, outcome: r.outcome, linkedEpisodeId: r.linkedEpisodeId, conditions, robustness };
  });
}

export type StripCell = { episodeId: string; sequence: number; outcome: EpisodeRecord["outcome"]; role: EpisodeRecord["role"];
  robustness: number | null; label: string };

/** One cell per episode in planner order, for the outcome timeline. */
export function outcomeStrip(records: EpisodeRecord[]): StripCell[] {
  return [...records].sort((a, b) => a.plannerSequence - b.plannerSequence).map(r => ({
    episodeId: r.episodeId, sequence: r.plannerSequence, outcome: r.outcome, role: r.role,
    robustness: r.verdict?.robustness ?? null,
    label: `#${r.plannerSequence} ${r.role}: ${r.outcome ?? r.state}${r.verdict ? ` (${r.verdict.reasonCode})` : ""}`,
  }));
}

/** Counts of invalid-experiment reasons and of refused-candidate codes, most frequent first. */
export function countBy<T>(items: T[], key: (item: T) => string | null | undefined): [string, number][] {
  const counts = new Map<string, number>();
  for (const item of items) { const k = key(item); if (k) counts.set(k, (counts.get(k) ?? 0) + 1); }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

/** Verification episodes grouped under the discovery episode they follow up, in order. */
export function verificationGroups(records: EpisodeRecord[]): { trigger: string; steps: EpisodeRecord[] }[] {
  const groups = new Map<string, EpisodeRecord[]>();
  for (const r of [...records].sort((a, b) => a.plannerSequence - b.plannerSequence)) {
    if (r.role === "discovery" || !r.linkedEpisodeId) continue;
    groups.set(r.linkedEpisodeId, [...(groups.get(r.linkedEpisodeId) ?? []), r]);
  }
  return [...groups.entries()].map(([trigger, steps]) => ({ trigger, steps }));
}
