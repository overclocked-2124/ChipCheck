"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Select } from "@/components/controls";
import { formatValue } from "@/lib/results";
import { buildSeries, OUTCOME_STYLE, scale, UNKNOWN_OUTCOME_STYLE, type SeriesPoint } from "@/lib/series";
import { outcomeStrip } from "@/lib/region";
import type { EpisodeRecord, HistoryEpisode, KaplanMeier } from "@/lib/types";

const style = (outcome: string | null) => (outcome ? OUTCOME_STYLE[outcome] : null) ?? UNKNOWN_OUTCOME_STYLE;

function Mark({ x, y, outcome, verification }: { x: number; y: number; outcome: string | null; verification: boolean }) {
  const s = style(outcome);
  const common = { stroke: s.color, strokeWidth: 1.8, fill: verification ? "#fff" : s.color };
  if (s.shape === "cross") return <path d={`M${x - 5} ${y - 5}L${x + 5} ${y + 5}M${x + 5} ${y - 5}L${x - 5} ${y + 5}`} stroke={s.color} strokeWidth={2.4} />;
  if (s.shape === "square") return <rect x={x - 4.5} y={y - 4.5} width={9} height={9} {...common} />;
  if (s.shape === "triangle") return <path d={`M${x} ${y - 6}L${x + 6} ${y + 5}L${x - 6} ${y + 5}Z`} {...common} />;
  if (s.shape === "diamond") return <path d={`M${x} ${y - 6}L${x + 6} ${y}L${x} ${y + 6}L${x - 6} ${y}Z`} {...common} />;
  return <circle cx={x} cy={y} r={5} {...common} />;
}

export function Legend() {
  return (
    <div className="legend">
      {Object.entries(OUTCOME_STYLE).map(([k, s]) => (
        <span key={k}><svg width="14" height="14" aria-hidden="true"><Mark x={7} y={7} outcome={k} verification={false} /></svg> {s.label}</span>
      ))}
      <span><svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="#fff" stroke="var(--c-pass)" strokeWidth="1.8" /></svg> Hollow: verification episode</span>
    </div>
  );
}

const W = 760, H = 320, PAD = { l: 56, r: 18, t: 18, b: 64 };

/** Failure region (HLD 09 §5): one continuous control against robustness, filtered by discrete state. */
export function RegionChart({ history, measuredControls }: { history: HistoryEpisode[]; measuredControls: string[] }) {
  const [control, setControl] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  const series = useMemo(() => buildSeries(history, control), [history, control]);
  const keys = useMemo(() => [...new Set(series.points.map(p => p.discrete))].sort(), [series]);
  const shown = series.points.filter(p => filter === "all" || p.discrete === filter);
  if (!series.control || !series.xRange) return <p className="empty">No finished episodes with a numeric control yet.</p>;
  const pad = (series.xRange[1] - series.xRange[0]) * 0.04 || 0.5;
  const xd: [number, number] = [series.xRange[0] - pad, series.xRange[1] + pad];
  const x = (v: number) => scale(v, xd, [PAD.l, W - PAD.r]);
  const y = (v: number) => scale(v, series.yRange, [H - PAD.b, PAD.t]);
  const stripY = H - 22;
  const ticks = Array.from({ length: 6 }, (_, i) => xd[0] + ((xd[1] - xd[0]) * i) / 5);
  const measured = measuredControls.includes(series.control);
  return (
    <div className="stack">
      <div className="row">
        <Select compact label="Control" value={series.control} onChange={setControl} options={series.numericControls} />
        <Select compact label="Discrete state" value={filter} onChange={setFilter}
          options={[{ value: "all", label: `All combinations (${series.points.length})` }, ...keys.map(k => ({ value: k, label: k }))]} />
      </div>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Robustness against ${series.control}`}>
        {[series.yRange[0], 0, series.yRange[1]].map(v => (
          <g key={v}><line className={v === 0 ? "axis" : "gridline"} x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} strokeDasharray={v === 0 ? "5 4" : undefined} />
            <text x={PAD.l - 8} y={y(v) + 4} textAnchor="end">{formatValue(v)}</text></g>
        ))}
        <text x={W - PAD.r} y={y(0) - 6} textAnchor="end">requirement boundary (0)</text>
        {ticks.map(t => <text key={t} x={x(t)} y={H - PAD.b + 18} textAnchor="middle">{formatValue(Number(t.toPrecision(4)))}</text>)}
        <text x={(PAD.l + W - PAD.r) / 2} y={H - PAD.b + 36} textAnchor="middle">{series.control} ({measured ? "measured" : "requested"})</text>
        <text x={14} y={(PAD.t + H - PAD.b) / 2} transform={`rotate(-90 14 ${(PAD.t + H - PAD.b) / 2})`} textAnchor="middle">robustness</text>
        <line className="gridline" x1={PAD.l} x2={W - PAD.r} y1={stripY - 10} y2={stripY - 10} />
        <text x={PAD.l - 8} y={stripY + 4} textAnchor="end">no margin</text>
        {shown.map((p: SeriesPoint) => (
          <Link key={p.episodeId} href={`/episodes/${p.episodeId}`}>
            <g><title>{`${p.role} ${style(p.outcome).label}: ${series.control}=${formatValue(p.x)}, robustness ${formatValue(p.robustness)}; ${p.discrete}`}</title>
              <Mark x={x(p.x)} y={p.robustness === null ? stripY : y(p.robustness)} outcome={p.outcome} verification={p.role !== "discovery"} /></g>
          </Link>
        ))}
      </svg>
      <Legend />
      <p className="hint">Below the dashed line a requirement was violated. Invalid and safety-aborted episodes have no margin and sit on the bottom strip, never at zero. Click a point to open its episode.</p>
    </div>
  );
}

/** Outcome timeline (HLD 09 §5 Live campaign): every episode in planner order; verification episodes are hollow. */
export function OutcomeStrip({ records }: { records: EpisodeRecord[] }) {
  const cells = outcomeStrip(records);
  if (!cells.length) return <p className="empty">No episodes yet.</p>;
  return (
    <div className="strip" role="list" aria-label="Episode outcomes in order">
      {cells.map(c => (
        <Link key={c.episodeId} role="listitem" href={`/episodes/${c.episodeId}`} title={c.label} aria-label={c.label}
          className={`cell${c.role === "discovery" ? "" : " verify"}`} style={{ ["--c" as string]: style(c.outcome).color }} />
      ))}
    </div>
  );
}

/** Robustness history over planner order: the signal the adaptive planner learns from. */
export function HistoryChart({ records }: { records: EpisodeRecord[] }) {
  const cells = outcomeStrip(records).filter(c => c.robustness !== null);
  if (cells.length < 2) return <p className="empty">Robustness history appears after two scored episodes.</p>;
  const h = 150, w = 760, l = 44, b = 22;
  const ys = cells.map(c => c.robustness as number);
  const yd: [number, number] = [Math.min(-1, ...ys), Math.max(1, ...ys)];
  const xd: [number, number] = [cells[0].sequence, cells[cells.length - 1].sequence];
  const X = (v: number) => scale(v, xd, [l, w - 10]), Y = (v: number) => scale(v, yd, [h - b, 8]);
  const discovery = cells.filter(c => c.role === "discovery");
  return (
    <svg className="chart" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Robustness by episode">
      <line className="axis" x1={l} x2={w - 10} y1={Y(0)} y2={Y(0)} strokeDasharray="5 4" />
      <text x={l - 6} y={Y(0) + 4} textAnchor="end">0</text>
      <text x={l - 6} y={Y(yd[1]) + 4} textAnchor="end">{formatValue(yd[1])}</text>
      <text x={l - 6} y={Y(yd[0]) + 4} textAnchor="end">{formatValue(yd[0])}</text>
      {discovery.length > 1 ? <polyline fill="none" stroke="var(--green-mid)" strokeWidth="1.5" strokeOpacity=".5"
        points={discovery.map(c => `${X(c.sequence)},${Y(c.robustness as number)}`).join(" ")} /> : null}
      {cells.map(c => <g key={c.episodeId}><title>{c.label}</title><Mark x={X(c.sequence)} y={Y(c.robustness as number)} outcome={c.outcome} verification={c.role !== "discovery"} /></g>)}
      <text x={w - 10} y={h - 4} textAnchor="end">planner order →</text>
    </svg>
  );
}

const PLANNER_COLORS = ["#1d4d36", "#c27a1f", "#2d5f7a", "#7a5ca8", "#c0392b", "#4f8e56"];

/** Kaplan–Meier: share of campaigns with no confirmed failure yet, by discovery episode (server-computed steps). */
export function KMChart({ curves, budget }: { curves: Record<string, KaplanMeier>; budget: number }) {
  const w = 760, h = 280, l = 48, b = 40;
  const X = (v: number) => scale(v, [0, Math.max(1, budget)], [l, w - 16]), Y = (v: number) => scale(v, [0, 1], [h - b, 12]);
  return (
    <svg className="chart" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Kaplan-Meier curves of episodes to first confirmed failure">
      {[0, 0.5, 1].map(v => <g key={v}><line className="gridline" x1={l} x2={w - 16} y1={Y(v)} y2={Y(v)} /><text x={l - 6} y={Y(v) + 4} textAnchor="end">{v}</text></g>)}
      <text x={(l + w) / 2} y={h - 8} textAnchor="middle">discovery episodes (budget {budget})</text>
      {Object.entries(curves).map(([planner, km], i) => {
        let path = `M${X(0)} ${Y(1)}`, prev = 1;
        for (const s of km.steps) { path += `L${X(s.time)} ${Y(prev)}L${X(s.time)} ${Y(s.survival)}`; prev = s.survival; }
        path += `L${X(budget)} ${Y(prev)}`;
        return <g key={planner}><path d={path} fill="none" stroke={PLANNER_COLORS[i % PLANNER_COLORS.length]} strokeWidth="2.2" /><title>{planner}</title></g>;
      })}
    </svg>
  );
}
export const plannerColor = (i: number) => PLANNER_COLORS[i % PLANNER_COLORS.length];
