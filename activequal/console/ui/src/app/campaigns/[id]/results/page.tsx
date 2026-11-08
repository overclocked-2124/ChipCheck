"use client";

import Link from "next/link";
import { use, useMemo, useState } from "react";
import { api, useLoad } from "@/components/api";
import { RegionChart } from "@/components/charts";
import { CounterexampleCard } from "@/components/counterexample";
import { Empty, ErrorBox, Loading, Notice, PageHeading, Section, Stat, StateBadge } from "@/components/ui";
import { toHistory, tracksFrom } from "@/lib/region";
import { formatValue } from "@/lib/results";
import { OUTCOME_STYLE, UNKNOWN_OUTCOME_STYLE } from "@/lib/series";
import type { CampaignContract, RecordsResponse, ReportView, UiError } from "@/lib/types";

type Exported = { bundlePath: string; markdown: string };
const TONE: Record<string, "bad" | "ok" | "warn" | "info"> = {
  COUNTEREXAMPLE_FOUND: "bad", NO_COUNTEREXAMPLE_FOUND: "ok", FAILURE_OBSERVED_NOT_CONFIRMED: "warn", CAMPAIGN_INCONCLUSIVE: "warn", SAFETY_ABORT: "bad",
};

/** Report page (HLD 09 §5): the server's PRD §19.2 statement, counterexamples, failure region, requirements, episodes. */
export default function ResultsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const base = `/v1/campaigns/${encodeURIComponent(id)}`;
  const rep = useLoad<ReportView>(`${base}/report`, 5000);
  const records = useLoad<RecordsResponse>(`${base}/records`, 5000);
  const info = useLoad<CampaignContract>(`${base}/contract`);
  const [exported, setExported] = useState<Exported | null>(null);
  const [exportError, setExportError] = useState<UiError | null>(null);
  const [exporting, setExporting] = useState(false);
  const tracks = useMemo(() => tracksFrom(info.data?.contract), [info.data]);
  const history = useMemo(() => toHistory(records.data?.episodes ?? [], tracks), [records.data, tracks]);
  async function exportReport() {
    setExporting(true); setExportError(null);
    const r = await api<Exported>(`${base}/export`);
    setExporting(false);
    if (r.ok) setExported(r.data); else setExportError(r.error);
  }
  const r = rep.data;
  if (rep.loading) return <Loading what="results" />;
  if (!r) return <ErrorBox error={rep.error} title="Could not load the report" />;
  const eps = records.data?.episodes ?? [];
  let n = Math.max(1, r.counterexamples.length);   // counterexample cards take the first section numbers
  const next = () => ++n;
  return (
    <>
      <PageHeading eyebrow="Campaign" step="Results" title={<>Results <code>{id.slice(0, 12)}</code><StateBadge state={r.state} /></>}
        intro={<>{r.identity.planner.method} seed {r.identity.planner.seed} · contract {r.identity.contractId.slice(0, 12)} v{r.identity.contractVersion} · fixture {r.identity.fixtureId}. <Link href={`/campaigns/${id}`}>Live view</Link></>}
        actions={<button type="button" className="secondary" onClick={() => void exportReport()} disabled={exporting}>{exporting ? "Exporting…" : "Export report"}</button>} />
      <ErrorBox error={rep.error} title="Report not current" />
      <Notice tone={TONE[r.result.kind] ?? "info"}>
        <strong>{r.result.headline}</strong>
        {r.result.statements.slice(1).map((s, i) => <p key={i}>{s.text}</p>)}
        {r.partial ? <p>The campaign is still {r.state}; this report is partial.</p> : null}
      </Notice>
      <div className="stats">
        <Stat label="Discovery used" value={r.budget.discovery.used} of={r.budget.discovery.allowed} />
        <Stat label="Verification used" value={r.budget.verification.used} of={r.budget.verification.allowed} />
        <Stat label="First confirmed failure" value={r.metrics.episodesToFirstConfirmedFailure ?? "none"} small
          sub={r.metrics.episodesToFirstConfirmedFailure ? "discovery episode index" : `censored at ${r.metrics.censoredAtBudget}`} />
        <Stat label="Valid episodes" value={r.outcomes.valid} of={r.outcomes.total} />
      </div>
      {r.counterexamples.length === 0 ? <Section title="Counterexamples" index={1} tag="None"><Empty>None recorded.</Empty></Section>
        : r.counterexamples.map((cx, i) => <CounterexampleCard key={cx.id} cx={cx} index={i + 1} />)}
      <Section title="Failure region" index={next()} tag="Observed, not predicted">
        <RegionChart history={history} measuredControls={Object.keys(tracks)} />
      </Section>
      <Section title="Requirements" index={next()} tag="Worst margin">
        <div className="table-wrap"><table className="grid">
          <thead><tr><th>Requirement</th><th>Rule</th><th>Pass</th><th>Fail</th><th>Inconclusive</th><th>Smallest margin</th></tr></thead>
          <tbody>{r.requirements.map(q => (
            <tr key={q.id}><td><code>{q.id}</code></td><td className="num">{q.metric} {q.op} {Object.values(q.limit).join("–")}</td>
              <td className="num">{q.pass}</td><td className={q.fail ? "num bad-text" : "num"}>{q.fail}</td><td className="num">{q.inconclusive}</td>
              <td className="num">{formatValue(q.minMargin)} {q.minMarginEpisodeId ? <Link href={`/episodes/${q.minMarginEpisodeId}`}>→</Link> : null}</td></tr>
          ))}</tbody>
        </table></div>
      </Section>
      <Section title="Episodes" index={next()} tag={`${eps.length} run · ${r.outcomes.candidatesRejected.count} refused`}>
        <div className="table-wrap"><table className="grid">
          <thead><tr><th>#</th><th>Role</th><th>Outcome</th><th>Reason</th><th>Robustness</th><th>Requested conditions</th></tr></thead>
          <tbody>{eps.map(e => {
            const s = e.outcome ? OUTCOME_STYLE[e.outcome] ?? UNKNOWN_OUTCOME_STYLE : UNKNOWN_OUTCOME_STYLE;
            return (
              <tr key={e.episodeId}><td><Link href={`/episodes/${e.episodeId}`}>{e.plannerSequence}</Link></td><td>{e.role.replace("_", " ")}</td>
                <td><span style={{ color: s.color, fontWeight: 700 }}>{s.label}</span></td><td><code>{e.verdict?.reasonCode ?? e.state}</code></td>
                <td className="num">{formatValue(e.verdict?.robustness)}</td>
                <td className="num">{Object.entries(e.requested).map(([k, v]) => `${k}=${formatValue(v)}`).join(", ")}</td></tr>
            );
          })}</tbody>
        </table></div>
      </Section>
      <Section title="Report and evidence bundle" index={next()} tag="Export">
        <div className="row"><button type="button" onClick={() => void exportReport()} disabled={exporting}>{exporting ? "Exporting…" : "Export report and evidence bundle"} <span className="arrow" aria-hidden="true">→</span></button></div>
        <ErrorBox error={exportError} title="Export failed" />
        {exported ? <><p className="hint" style={{ marginTop: 14 }}>Bundle written on the control-plane machine: <code>{exported.bundlePath}</code></p><pre className="report">{exported.markdown}</pre></> : null}
        <h3>Limitations</h3>
        <ul className="hint">{r.limitations.map(l => <li key={l}>{l}</li>)}</ul>
      </Section>
    </>
  );
}
