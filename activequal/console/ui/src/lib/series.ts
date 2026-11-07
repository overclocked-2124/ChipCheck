// Observed-points series for the Results chart. Only reshapes numbers the Backend already computed
// (conditions, robustness, outcome); it does no statistics.

import type { HistoryEpisode, Outcome } from "./types.ts";

export type SeriesPoint = {
  episodeId: string;
  index: number;                 // 1-based order in the history
  x: number;
  robustness: number | null;     // null when the verdict has no margin (invalid, safety abort)
  outcome: Outcome | null;
  role: HistoryEpisode["role"];
  discrete: string;              // the discrete conditions, for filtering
};

export type Series = {
  control: string | null;
  numericControls: string[];
  points: SeriesPoint[];
  xRange: [number, number] | null;
  yRange: [number, number];
  noMargin: SeriesPoint[];       // plotted on a separate strip, never at robustness 0
};

export function numericControls(episodes: HistoryEpisode[]): string[] {
  const order: string[] = [];
  const numeric = new Map<string, boolean>();
  for (const ep of episodes) {
    for (const [name, value] of Object.entries(ep.conditions)) {
      if (!numeric.has(name)) { order.push(name); numeric.set(name, true); }
      if (typeof value !== "number") numeric.set(name, false);
    }
  }
  return order.filter(n => numeric.get(n));
}

/** Prefer a voltage-like control (name ends in V or contains "volt"), else the first numeric control. */
export function defaultControl(controls: string[]): string | null {
  return controls.find(c => /volt|rail.*v$|v$/i.test(c) && !/^dwell/i.test(c)) ?? controls[0] ?? null;
}

export function discreteKey(conditions: HistoryEpisode["conditions"]): string {
  return Object.entries(conditions).filter(([, v]) => typeof v !== "number").map(([k, v]) => `${k}=${String(v)}`).sort().join(", ") || "(none)";
}

export function buildSeries(episodes: HistoryEpisode[], control?: string | null, roles?: HistoryEpisode["role"][]): Series {
  const controls = numericControls(episodes);
  const chosen = control && controls.includes(control) ? control : defaultControl(controls);
  const points: SeriesPoint[] = [];
  if (chosen) {
    episodes.forEach((ep, i) => {
      if (roles && !roles.includes(ep.role)) return;
      const x = ep.conditions[chosen];
      if (typeof x !== "number") return;
      points.push({ episodeId: ep.episodeId, index: i + 1, x, robustness: ep.robustness, outcome: ep.outcome, role: ep.role, discrete: discreteKey(ep.conditions) });
    });
  }
  const xs = points.map(p => p.x);
  const ys = points.map(p => p.robustness).filter((v): v is number => typeof v === "number");
  const yMin = Math.min(-1, ...ys), yMax = Math.max(1, ...ys);
  return {
    control: chosen, numericControls: controls, points,
    xRange: xs.length ? [Math.min(...xs), Math.max(...xs)] : null,
    yRange: [yMin, yMax],
    noMargin: points.filter(p => p.robustness === null),
  };
}

/** Linear scale helper shared by the SVG chart and its test. A zero-width domain maps to the middle. */
export function scale(value: number, domain: [number, number], range: [number, number]): number {
  const span = domain[1] - domain[0];
  if (span === 0) return (range[0] + range[1]) / 2;
  return range[0] + ((value - domain[0]) / span) * (range[1] - range[0]);
}

export const OUTCOME_STYLE: Record<string, { label: string; color: string; shape: "circle" | "cross" | "square" | "diamond" | "triangle" }> = {
  PASS: { label: "Pass", color: "var(--c-pass)", shape: "circle" },
  DUT_FAILURE: { label: "Failure", color: "var(--c-fail)", shape: "cross" },
  INVALID_EXPERIMENT: { label: "Invalid", color: "var(--c-invalid)", shape: "square" },
  SAFETY_ABORT: { label: "Safety abort", color: "var(--c-abort)", shape: "triangle" },
};
export const UNKNOWN_OUTCOME_STYLE = { label: "Unknown", color: "var(--c-muted)", shape: "diamond" as const };
