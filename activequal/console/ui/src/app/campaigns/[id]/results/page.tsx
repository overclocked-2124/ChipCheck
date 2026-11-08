"use client";

import Link from "next/link";
import { use, useState } from "react";
import { api, useLoad } from "@/components/api";
import { ConditionsTable, Empty, ErrorBox, Loading, Notice, Section, StateBadge } from "@/components/ui";
import { formatValue, reproductionText, resultStatement } from "@/lib/results";
import { OUTCOME_STYLE, UNKNOWN_OUTCOME_STYLE } from "@/lib/series";
import type { CampaignView, Counterexample, EpisodesResponse, UiError } from "@/lib/types";

type Exported = { bundlePath: string; markdown: string };

const TONE = { counterexample: "bad", none: "ok", inconclusive: "warn", safety: "bad", running: "info" } as const;

export default function ResultsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const base = `/v1/campaigns/${encodeURIComponent(id)}`;
  const campaign = useLoad<CampaignView>(base, 5000);
  const eps = useLoad<EpisodesResponse>(`${base}/episodes`, 5000);
  const cxs = useLoad<{ counterexamples: Counterexample[] }>(`${base}/counterexamples`, 5000);
  const [exported, setExported] = useState<Exported | null>(null);
  const [exportError, setExportError] = useState<UiError | null>(null);
  const [exporting, setExporting] = useState(false);
  async function exportReport() {
    setExporting(true); setExportError(null);
    const r = await api<Exported>(`${base}/export`);
    setExporting(false);
    if (r.ok) setExported(r.data); else setExportError(r.error);
  }
  const c = campaign.data;
  if (campaign.loading) return <Loading what="results" />;
  if (!c) return <ErrorBox error={campaign.error} title="Could not load the campaign" />;
  const counterexamples = cxs.data?.counterexamples ?? [];
  const statement = resultStatement(c, counterexamples);
  const episodes = eps.data?.episodes ?? [];

  return (
    <>
      <div className="row"><h1>Results for <Link href={`/campaigns/${c.id}`}><code>{c.id.slice(0, 12)}</code></Link></h1><StateBadge state={c.state} /></div>
      <Notice tone={TONE[statement.kind]}>{statement.text}</Notice>
      <Section title="Counterexamples">
        {counterexamples.length === 0 ? <Empty>None recorded.</Empty> : counterexamples.map(cx => (
          <div key={cx.id} className="stack">
            <p>Original episode <code>{cx.originalEpisodeId.slice(0, 12)}</code>; {reproductionText(cx)}.</p>
            <h3>Minimized conditions</h3>
            <ConditionsTable conditions={cx.minimized.conditions} />
            <p className="hint">Removed (not needed): {cx.minimized.removed.join(", ") || "none"}. Kept: {cx.minimized.kept.join(", ") || "none"}.</p>
            <h3>Failure boundaries</h3>
            <table className="grid"><thead><tr><th>Control</th><th>Last failing low</th><th>First passing low</th><th>Last failing high</th><th>First passing high</th></tr></thead><tbody>
              {Object.entries(cx.intervals.intervals).map(([name, iv]) => (
                <tr key={name}><th scope="row">{name}</th>
                  <td>{formatValue(iv.sides.low.lastFail)}</td><td>{formatValue(iv.sides.low.firstPass)}</td>
                  <td>{formatValue(iv.sides.high.lastFail)}</td><td>{formatValue(iv.sides.high.firstPass)}</td></tr>
              ))}
            </tbody></table>
            {cx.intervals.budgetExhausted ? <p className="hint">The verification budget ran out before every boundary was narrowed.</p> : null}
          </div>
        ))}
      </Section>
      <Section title={`Episodes (${episodes.length})`}>
        <div className="table-wrap"><table className="grid">
          <thead><tr><th>Episode</th><th>Role</th><th>Outcome</th><th>Robustness</th><th>Conditions</th></tr></thead>
          <tbody>{episodes.map(e => {
            const style = e.outcome ? OUTCOME_STYLE[e.outcome] ?? UNKNOWN_OUTCOME_STYLE : UNKNOWN_OUTCOME_STYLE;
            return (
              <tr key={e.episodeId}><td><code>{e.episodeId.slice(0, 8)}</code></td><td>{e.role}</td><td>{style.label}</td>
                <td>{formatValue(e.robustness)}</td>
                <td>{Object.entries(e.conditions).map(([k, v]) => `${k}=${formatValue(v)}`).join(", ")}</td></tr>
            );
          })}</tbody>
        </table></div>
      </Section>
      <Section title="Report and evidence bundle">
        <button type="button" onClick={() => void exportReport()} disabled={exporting}>{exporting ? "Exporting..." : "Export report and evidence bundle"}</button>
        <ErrorBox error={exportError} title="Export failed" />
        {exported ? (
          <>
            <p className="hint">Bundle written on the control-plane machine: <code>{exported.bundlePath}</code></p>
            <pre className="report">{exported.markdown}</pre>
          </>
        ) : null}
      </Section>
      {(eps.data?.rejected.length ?? 0) > 0 ? (
        <Section title={`Rejected candidates (${eps.data!.rejected.length})`}>
          <ul>{eps.data!.rejected.slice(0, 20).map((r, i) => <li key={i}>{r.violations.map(v => `${v.code}: ${v.message}`).join("; ")}</li>)}</ul>
        </Section>
      ) : null}
    </>
  );
}
