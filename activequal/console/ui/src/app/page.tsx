"use client";

import Link from "next/link";
import { useLoad } from "@/components/api";
import { Empty, ErrorBox, Loading, Section, StateBadge } from "@/components/ui";
import type { CampaignView } from "@/lib/types";

export default function Home() {
  const { data, error, loading } = useLoad<{ campaigns: CampaignView[] }>("/v1/campaigns", 3000);
  const campaigns = data?.campaigns ?? [];
  return (
    <>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>Campaigns</h1>
        <Link className="button" href="/campaigns/new">New campaign</Link>
      </div>
      <ErrorBox error={error} title="Could not load campaigns" />
      <Section title="All campaigns">
        {loading ? <Loading what="campaigns" /> : null}
        {!loading && !error && campaigns.length === 0 ? (
          <Empty>No campaigns yet. Start with a contract (Contracts), a fixture with a calibration (Fixtures), then create a campaign.</Empty>
        ) : null}
        {campaigns.length > 0 ? (
          <div className="table-wrap">
            <table className="grid">
              <thead><tr><th>Campaign</th><th>State</th><th>Planner</th><th>Fixture</th><th>Discovery</th><th>Verification</th><th>Outcomes</th><th></th></tr></thead>
              <tbody>
                {campaigns.map(c => (
                  <tr key={c.id}>
                    <td><Link href={`/campaigns/${c.id}`}><code>{c.id.slice(0, 12)}</code></Link></td>
                    <td><StateBadge state={c.state} /></td>
                    <td>{c.planner.method} (seed {c.seed})</td>
                    <td>{c.fixtureId}</td>
                    <td>{c.budget.discoveryUsed} / {c.budget.discovery}</td>
                    <td>{c.budget.verificationUsed} / {c.budget.verification}</td>
                    <td>{Object.entries(c.episodesByOutcome).map(([k, n]) => `${k} ${n}`).join(", ") || "none yet"}</td>
                    <td><Link href={`/campaigns/${c.id}/results`}>Results</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Section>
      <p className="hint">A campaign result is a statement about the conditions that were tested, never about conditions that were not.</p>
    </>
  );
}
