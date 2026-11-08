"use client";

import Link from "next/link";
import { useLoad } from "@/components/api";
import { Empty, ErrorBox, Loading, PageHeading, ProgressBar, Section, StateBadge } from "@/components/ui";
import type { CampaignView } from "@/lib/types";

export default function Home() {
  const { data, error, loading } = useLoad<{ campaigns: CampaignView[] }>("/v1/campaigns", 3000);
  const campaigns = data?.campaigns ?? [];
  const running = campaigns.filter(c => c.state === "RUNNING").length;
  return (
    <>
      <PageHeading eyebrow="Workspace" step="Campaigns" title="Campaigns"
        intro="Every campaign belongs to one approved contract and one fixture. Open one to follow it live or to read its evidence."
        actions={<Link className="button" href="/campaigns/new">New campaign <span className="arrow" aria-hidden="true">→</span></Link>} />
      <ErrorBox error={error} title="Could not load campaigns" />
      <Section title="All campaigns" index={1} tag={campaigns.length ? `${campaigns.length} total · ${running} running` : "Overview"}>
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
                    <td>{c.planner.method} <span className="hint">seed {c.seed}</span></td>
                    <td>{c.fixtureId}</td>
                    <td className="num">{c.budget.discoveryUsed} / {c.budget.discovery}
                      <ProgressBar value={c.budget.discovery ? c.budget.discoveryUsed / c.budget.discovery : 0} label="Discovery used" thin /></td>
                    <td className="num">{c.budget.verificationUsed} / {c.budget.verification}</td>
                    <td>{Object.entries(c.episodesByOutcome).map(([k, n]) => `${k} ${n}`).join(", ") || "none yet"}</td>
                    <td><Link href={`/campaigns/${c.id}/results`}>Results →</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Section>
      <p className="note"><strong>Honest results.</strong> A campaign result is a statement about the conditions that were tested, never about conditions that were not.</p>
    </>
  );
}
