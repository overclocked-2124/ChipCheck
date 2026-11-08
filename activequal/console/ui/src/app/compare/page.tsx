"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, useLoad } from "@/components/api";
import { Empty, ErrorBox, Notice, Section } from "@/components/ui";
import { compareCampaigns, type Comparison } from "@/lib/results";
import type { CampaignView, EpisodesResponse, UiError } from "@/lib/types";

const FINISHED = ["COMPLETED", "ABORTED", "LOCKED_OUT"];

export default function ComparePage() {
  const list = useLoad<{ campaigns: CampaignView[] }>("/v1/campaigns");
  const [picked, setPicked] = useState<string[]>([]);
  const [result, setResult] = useState<Comparison | null>(null);
  const [error, setError] = useState<UiError | null>(null);
  const campaigns = (list.data?.campaigns ?? []).filter(c => FINISHED.includes(c.state) || c.state === "RUNNING");

  useEffect(() => {
    let alive = true;
    async function load() {
      setError(null);
      const items = [];
      for (const id of picked) {
        const campaign = campaigns.find(c => c.id === id);
        const eps = await api<EpisodesResponse>(`/v1/campaigns/${encodeURIComponent(id)}/episodes`);
        if (!eps.ok) { if (alive) setError(eps.error); return; }
        if (campaign) items.push({ campaign, episodes: eps.data.episodes });
      }
      if (alive) setResult(items.length ? compareCampaigns(items) : null);
    }
    void load();
    return () => { alive = false; };
  }, [picked.join(","), list.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (id: string) => setPicked(p => p.includes(id) ? p.filter(x => x !== id) : [...p, id]);

  return (
    <>
      <h1>Compare campaigns</h1>
      <ErrorBox error={list.error ?? error} title="Could not load campaigns" />
      <Section title="Choose campaigns">
        {campaigns.length === 0 ? <Empty>No running or finished campaigns yet.</Empty> : (
          <ul>{campaigns.map(c => (
            <li key={c.id}><label><input type="checkbox" checked={picked.includes(c.id)} onChange={() => toggle(c.id)} />{" "}
              <code>{c.id.slice(0, 12)}</code> {c.planner.method} seed {c.seed} ({c.state})</label></li>
          ))}</ul>
        )}
      </Section>
      {result ? (
        <Section title="Episodes to the first failure">
          {result.warnings.map(w => <Notice key={w} tone="warn">{w}</Notice>)}
          <table className="grid">
            <thead><tr><th>Campaign</th><th>Planner</th><th>Seed</th><th>First failure at</th><th>Discovery used</th><th>Verification used</th></tr></thead>
            <tbody>{result.rows.map(r => (
              <tr key={r.campaignId}><td><Link href={`/campaigns/${r.campaignId}/results`}><code>{r.campaignId.slice(0, 12)}</code></Link></td>
                <td>{r.planner}</td><td>{r.seed}</td>
                <td>{r.firstFailureAt ?? `none within ${r.discoveryBudget} (censored)`}</td>
                <td>{r.discoveryEpisodes} / {r.discoveryBudget}</td><td>{r.verificationUsed}</td></tr>
            ))}</tbody>
          </table>
          <p className="hint">One campaign per planner proves nothing. The statistical comparison (log-rank, HLD 06 §8) is in the exported report.</p>
        </Section>
      ) : null}
    </>
  );
}
