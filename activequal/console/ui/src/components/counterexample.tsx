"use client";

import Link from "next/link";
import { ConditionsTable, KeyValues, Section } from "@/components/ui";
import { formatValue } from "@/lib/results";
import type { ReportCounterexample } from "@/lib/types";

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "?" : `${Math.round(v * 100)}%`);
const ep = (id: string | null) => (id ? <Link href={`/episodes/${id}`}><code>{id.slice(0, 8)}</code></Link> : <span className="hint">refused</span>);

/** PRD §19.3 counterexample record: measured conditions, violated requirement and margin, original and minimized
 *  conditions, the bracketed interval, reproduction rate with its interval, verification steps and the seeded label. */
export function CounterexampleCard({ cx, index }: { cx: ReportCounterexample; index: number }) {
  const r = cx.reproduction;
  const ci = r.wilson95 ? `${pct(r.wilson95[0])}–${pct(r.wilson95[1])}` : "n/a";
  return (
    <Section title={`Counterexample ${index}`} index={index} aside={<span className={`badge badge-${cx.origin === "seeded" ? "warn" : cx.origin === "natural" ? "bad" : "muted"}`}>{cx.originLabel.split(" (")[0]}</span>}>
      <div className="stack">
        <p className="note"><strong>{cx.originLabel}.</strong> {cx.origin === "seeded" ? "This failure was programmed on purpose to prove the pipeline; the planner never saw its rule." : null}</p>
        <div className="stats">
          <div className="stat"><span>Reproduced</span><strong>{r.numerator}<small style={{ display: "inline", fontSize: 13 }}> / {r.denominator}</small></strong><small>95% interval {ci}{r.meetsTenReplays ? "" : " · fewer than 10 replays"}</small></div>
          {cx.violated.map(v => (
            <div className="stat" key={v.requirement}><span>Violated: {v.requirement}</span><strong className="small">{formatValue(v.measuredValue)} {v.unit ?? ""}</strong>
              <small>{v.metric} · margin {formatValue(v.margin)}{v.uncertainty !== null ? ` · ±${formatValue(v.uncertainty)}` : ""}</small></div>
          ))}
          <div className="stat"><span>Found at</span><strong className="small">discovery #{cx.original.discoveryIndex ?? "?"}</strong><small>{ep(cx.originalEpisodeId)}</small></div>
        </div>
        <div className="grid2">
          <div className="stack"><h3>Original conditions (requested)</h3><ConditionsTable conditions={cx.original.requested} /></div>
          <div className="stack"><h3>Minimized conditions</h3><ConditionsTable conditions={cx.minimized.conditions} />
            <p className="hint">Returned to nominal without losing the failure: {cx.minimized.removed.join(", ") || "none"}. Kept: {cx.minimized.kept.join(", ") || "none"}.
              {Object.keys(cx.minimized.necessity).length ? ` Necessity probes: ${Object.entries(cx.minimized.necessity).map(([k, v]) => `${k} ${v}`).join(", ")}.` : ""}</p></div>
        </div>
        <h3>Failure interval</h3>
        <div className="table-wrap"><table className="grid">
          <thead><tr><th>Control</th><th>Failing range</th><th>Low side</th><th>High side</th></tr></thead>
          <tbody>{Object.entries(cx.intervals).map(([name, iv]) => (
            <tr key={name}><td><code>{name}</code></td><td className="num">{formatValue(iv.low)} – {formatValue(iv.high)}</td>
              {(["low", "high"] as const).map(side => <td key={side}>{iv.sides[side].firstPass !== null ? `passes at ${formatValue(iv.sides[side].firstPass)}` : "—"}<br /><span className="hint">{iv.sides[side].note}</span></td>)}</tr>
          ))}</tbody>
        </table></div>
        {cx.budgetExhausted ? <p className="hint">The verification budget ran out before every boundary was narrowed.</p> : null}
        <h3>Verification steps</h3>
        <ol className="steps">{cx.verification.episodes.map(s => (
          <li key={s.sequence}><span className="role">{s.role.replace("_", " ")}</span>
            <span className="num">{Object.entries(s.conditions).filter(([k, v]) => cx.original.requested[k] !== v).map(([k, v]) => `${k}=${formatValue(v)}`).join(", ") || "same as original"}</span>
            <span>{s.outcome === "DUT_FAILURE" ? <span className="chip bad">Fail</span> : s.outcome === "PASS" ? <span className="chip ok">Pass</span> : <span className="chip">{s.outcome ?? "running"}</span>} {ep(s.episodeId)}</span></li>
        ))}</ol>
        <KeyValues rows={[["Nearby passing points", String(cx.nearbyPassing.length)], ["Planner reason for the original", cx.original.plannerReason]]} />
      </div>
    </Section>
  );
}
