"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useLoad, useNow } from "@/components/api";
import { Empty, ErrorBox, KeyValues, Loading, Notice, Section, StateBadge, ActionButton } from "@/components/ui";
import { allowedActions, STATE_MEANING, type CampaignAction } from "@/lib/actions";
import { activeEpisode, ageSeconds, benchStatus, formatAge, lockoutInfo, stopExplanation } from "@/lib/live";
import type { ApiResult, CampaignEvent, CampaignView, FixtureView, UiError } from "@/lib/types";

export default function CampaignPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const campaign = useLoad<CampaignView>(`/v1/campaigns/${encodeURIComponent(id)}`, 2000);
  const events = useLoad<{ events: CampaignEvent[] }>(`/v1/campaigns/${encodeURIComponent(id)}/events`, 2000);
  const fixtureId = campaign.data?.fixtureId ?? null;
  const fixture = useLoad<FixtureView>(fixtureId ? `/v1/fixtures/${encodeURIComponent(fixtureId)}` : null, 3000);
  const now = useNow();
  const [actionError, setActionError] = useState<UiError | null>(null);
  const [reasons, setReasons] = useState<{ code: string; message: string }[]>([]);

  const c = campaign.data;
  if (campaign.loading) return <Loading what="campaign" />;
  if (!c) return <ErrorBox error={campaign.error} title="Could not load the campaign" />;
  const log = events.data?.events ?? [];
  const current = activeEpisode(log);
  const stop = stopExplanation(c.state, log);
  const lock = lockoutInfo(c.state, log);

  function done(action: CampaignAction, result: ApiResult<unknown>) {
    setActionError(null); setReasons([]);
    if (result.ok) { if (action === "validate") setReasons((result.data as CampaignView).reasons ?? []); void campaign.reload(); void events.reload(); }
    else { setActionError(result.error); setReasons(result.error.reasons ?? []); }
  }

  return (
    <>
      <div className="row"><h1>Campaign <code>{c.id.slice(0, 12)}</code></h1><StateBadge state={c.state} /></div>
      <p className="hint">{STATE_MEANING[c.state]}</p>
      <ErrorBox error={campaign.error} title="Showing the last known state" />
      {c.agentError ? <Notice tone="bad">Agent stopped: {c.agentError}</Notice> : null}
      <Section title="Actions">
        <div className="row">
          {allowedActions(c.state).filter(a => !a.reviewer).map(a =>
            <ActionButton key={a.action} action={a.action} campaignId={c.id} version={c.version} onResult={done} />)}
          <Link className="button secondary" href={`/campaigns/${c.id}/results`}>Results</Link>
        </div>
        <ErrorBox error={actionError} title="Action refused" />
        {reasons.length ? <Notice tone="warn"><ul>{reasons.map((r, i) => <li key={i}><code>{r.code}</code> {r.message}</li>)}</ul></Notice> : null}
      </Section>
      <Section title="Progress">
        <KeyValues rows={[
          ["Planner", `${c.planner.method} (seed ${c.seed})`],
          ["Fixture", c.fixtureId],
          ["Discovery", `${c.budget.discoveryUsed} / ${c.budget.discovery}`],
          ["Verification", `${c.budget.verificationUsed} / ${c.budget.verification}`],
          ["Rejected candidates", String(c.candidatesRejected)],
          ["Outcomes", Object.entries(c.episodesByOutcome).map(([k, n]) => `${k} ${n}`).join(", ") || "none yet"],
        ]} />
      </Section>
      <Section title="Current episode">
        {current ? <KeyValues rows={[
          ["Episode", <code key="e">{current.episodeId.slice(0, 12)}</code>],
          ["Phase", current.phase],
          ["Lease owner", current.leaseOwner ?? "unknown"],
          ["Last heartbeat", formatAge(ageSeconds(current.lastHeartbeat, now))],
          ...(current.leaseProblem ? [["Lease problem", current.leaseProblem] as [string, string]] : []),
        ]} /> : <Empty>No episode is running.</Empty>}
      </Section>
      {stop ? <Notice tone="info"><strong>{stop.headline}</strong> <code>{stop.reasonCode}</code> {stop.reason} ({stop.actor})</Notice> : null}
      {lock ? (
        <Notice tone="bad"><strong>Locked out: {lock.cause}</strong>
          <ul>{lock.checklist.map(item => <li key={item}>{item}</li>)}</ul>
          <p>Clearing a lockout needs a reviewer and is done from the fixture page.</p>
        </Notice>
      ) : null}
      <Section title="Bench">
        <ul>{benchStatus(fixture.data).map(l => <li key={l.id}>{l.ok === null ? "?" : l.ok ? "OK" : "NOT OK"} {l.label}: {l.detail}</li>)}</ul>
      </Section>
      <Section title="Event log">
        <div className="table-wrap"><table className="grid"><tbody>
          {[...log].reverse().slice(0, 40).map(e => (
            <tr key={e.id}><td>{e.backendTs.slice(11, 19)}</td><td>{e.entity}</td><td>{e.newState}</td><td><code>{e.reasonCode}</code></td><td>{e.reason}</td></tr>
          ))}
        </tbody></table></div>
      </Section>
    </>
  );
}
