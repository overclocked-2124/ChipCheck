"use client";

import Link from "next/link";
import { useState } from "react";
import { useLoad } from "@/components/api";
import { KMChart, plannerColor } from "@/components/charts";
import { Empty, ErrorBox, Loading, Notice, PageHeading, Section, StateBadge } from "@/components/ui";
import { formatValue } from "@/lib/results";
import type { CampaignView, CompareResponse, Proportion } from "@/lib/types";

const FINISHED = ["COMPLETED", "ABORTED", "LOCKED_OUT", "RUNNING", "PAUSED"];
const rate = (p: Proportion | undefined) => !p || p.rate === null ? "n/a"
  : `${p.numerator}/${p.denominator} (${Math.round(p.rate * 100)}%${p.wilson95 ? `, 95% CI ${Math.round(p.wilson95[0] * 100)}–${Math.round(p.wilson95[1] * 100)}%` : ""})`;

/** HLD 09 §5 Compare: first *confirmed* failure per campaign (PRD §21.5), Kaplan–Meier, discovery at 30 and 50,
 *  log-rank. Every number comes from the server (HLD 09 §9); the page only draws it. */
export default function ComparePage() {
  const list = useLoad<{ campaigns: CampaignView[] }>("/v1/campaigns");
  const [picked, setPicked] = useState<string[]>([]);
  const result = useLoad<CompareResponse>(picked.length ? `/v1/compare?campaigns=${picked.join(",")}` : null);
  const campaigns = (list.data?.campaigns ?? []).filter(c => FINISHED.includes(c.state));
  const toggle = (id: string) => setPicked(p => p.includes(id) ? p.filter(x => x !== id) : [...p, id]);
  const data = result.data;
  const profiles = data ? Object.entries(data.comparison.profiles) : [];
  return (
    <>
      <PageHeading eyebrow="Research" step="Compare" title="Compare campaigns"
        intro="How many discovery episodes each planner needed before its first confirmed failure. Campaigns are compared only within one contract version; a campaign that found nothing is censored at its budget, never dropped." />
      <ErrorBox error={list.error} title="Could not load campaigns" />
      <Section title="Choose campaigns" index={1} tag={`${picked.length} selected`}>
        {list.loading ? <Loading what="campaigns" /> : campaigns.length === 0 ? <Empty>No running or finished campaigns yet.</Empty> : (
          <ul className="picklist">{campaigns.map(c => (
            <li key={c.id}><label className="check"><input type="checkbox" checked={picked.includes(c.id)} onChange={() => toggle(c.id)} />
              <code>{c.id.slice(0, 12)}</code> <span>{c.planner.method} · seed {c.seed} · contract {c.contractHash.slice(0, 8)}</span> <StateBadge state={c.state} /></label></li>
          ))}</ul>
        )}
      </Section>
      <ErrorBox error={result.error} title="Comparison failed" />
      {data ? (
        <Section title="Episodes to the first confirmed failure" index={2} tag="Censored at budget">
          <div className="table-wrap"><table className="grid">
            <thead><tr><th>Campaign</th><th>Planner</th><th>Seed</th><th>Contract</th><th>Confirmed at</th><th>First observed</th><th>Discovery used</th><th>State</th></tr></thead>
            <tbody>{data.campaigns.map(r => (
              <tr key={r.campaignId}><td><Link href={`/campaigns/${r.campaignId}/results`}><code>{r.campaignId.slice(0, 12)}</code></Link></td>
                <td>{r.planner}</td><td className="num">{r.seed}</td><td className="num">{r.contract.slice(0, 8)}</td>
                <td className="num"><strong>{r.firstConfirmedFailureAt ?? `none (censored at ${r.censoredAt})`}</strong></td>
                <td className="num">{r.firstObservedFailureAt ?? "—"}</td>
                <td className="num">{r.discoveryUsed} / {r.discoveryBudget}{r.stoppedEarly ? " · stopped early" : ""}</td><td><StateBadge state={r.state} /></td></tr>
            ))}</tbody>
          </table></div>
          {data.campaigns.some(r => r.state === "RUNNING" || r.state === "PAUSED") ? <Notice tone="warn">Some campaigns are still running; their rows are not final.</Notice> : null}
        </Section>
      ) : null}
      {profiles.map(([profile, p], pi) => {
        const planners = Object.entries(p.planners);
        const budget = Math.max(...(data?.campaigns.filter(c => c.contract.startsWith(profile)).map(c => c.discoveryBudget) ?? [50]));
        return (
          <Section key={profile} title={`Planners on contract ${profile.slice(0, 8)}`} index={3 + pi} tag={data!.comparison.primaryMetric.split(",")[0]}>
            <div className="stack">
              <KMChart curves={Object.fromEntries(planners.map(([k, v]) => [k, v.kaplanMeier]))} budget={budget} />
              <div className="legend">{planners.map(([k], i) => <span key={k}><span className="chip" style={{ background: plannerColor(i), color: "#fff" }}>{k}</span></span>)}</div>
              <div className="table-wrap"><table className="grid">
                <thead><tr><th>Planner</th><th>Campaigns</th><th>Median episodes</th>{data!.comparison.checkpoints.map(b => <th key={b}>Found within {b}</th>)}</tr></thead>
                <tbody>{planners.map(([k, v]) => (
                  <tr key={k}><td>{k}</td><td className="num">{v.campaigns}</td><td className="num">{v.kaplanMeier.median ?? "not reached"}</td>
                    {data!.comparison.checkpoints.map(b => <td key={b} className="num">{rate(v.discoveryRates[String(b)])}</td>)}</tr>
                ))}</tbody>
              </table></div>
              {p.logRank.length ? (
                <div className="table-wrap"><table className="grid">
                  <thead><tr><th>Pair</th><th>Log-rank χ²</th><th>p</th><th>p (Bonferroni)</th></tr></thead>
                  <tbody>{p.logRank.map(t => <tr key={t.a + t.b}><td>{t.a} vs {t.b}</td><td className="num">{formatValue(t.chiSquare)}</td><td className="num">{formatValue(t.p)}</td><td className="num">{formatValue(t.pBonferroni)}</td></tr>)}</tbody>
                </table></div>
              ) : <p className="hint">Pick campaigns from at least two planners on this contract for a log-rank test.</p>}
              <p className="hint">One campaign per planner proves nothing; HLD 06 §8 pre-registers repeated seeds per planner.</p>
            </div>
          </Section>
        );
      })}
    </>
  );
}
