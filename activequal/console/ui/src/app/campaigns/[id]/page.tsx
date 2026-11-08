"use client";

import Link from "next/link";
import { use, useState } from "react";
import { useLoad, useNow } from "@/components/api";
import { ArmChecklist, ClearLockout } from "@/components/campaign-controls";
import { useCampaignEvents } from "@/components/use-events";
import { Empty, ErrorBox, KeyValues, Loading, Notice, PageHeading, Section, Stat, StateBadge, ActionButton } from "@/components/ui";
import { allowedActions, STATE_MEANING, type CampaignAction } from "@/lib/actions";
import { activeEpisode, ageSeconds, benchStatus, formatAge, lockoutInfo, stopExplanation } from "@/lib/live";
import type { ApiResult, CampaignEvent, CampaignView, FixtureView, UiError } from "@/lib/types";

export default function CampaignPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const campaign = useLoad<CampaignView>(`/v1/campaigns/${encodeURIComponent(id)}`, 2000);
  const events = useCampaignEvents(id);
  const fixtureId = campaign.data?.fixtureId ?? null;
  const fixture = useLoad<FixtureView>(fixtureId ? `/v1/fixtures/${encodeURIComponent(fixtureId)}` : null, 3000);
  const now = useNow();
  const [actionError, setActionError] = useState<UiError | null>(null);
  const [reasons, setReasons] = useState<{ code: string; message: string }[]>([]);
  const [serverReasons, setServerReasons] = useState<{ code: string; message: string }[] | null>(null);

  const c = campaign.data;
  if (campaign.loading) return <Loading what="campaign" />;
  if (!c) return <ErrorBox error={campaign.error} title="Could not load the campaign" />;
  const log = events.events;
  const current = activeEpisode(log);
  const stop = stopExplanation(c.state, log);
  const lock = lockoutInfo(c.state, log);

  function done(action: CampaignAction, result: ApiResult<unknown>) {
    setActionError(null); setReasons([]);
    if (result.ok) {
      if (action === "validate") { const r = (result.data as CampaignView).reasons ?? []; setReasons(r); setServerReasons(r); }
      void campaign.reload(); void events.reload();
    } else { setActionError(result.error); setReasons(result.error.reasons ?? []); if (action === "arm") setServerReasons(result.error.reasons ?? []); }
  }

  const extra = c.state === "READY" || c.state === "LOCKED_OUT" ? 1 : 0;   // the checklist or lockout card takes section 02
  const outcomes = Object.entries(c.episodesByOutcome).map(([k, n]) => `${k} ${n}`).join(", ") || "none yet";
  return (
    <>
      <PageHeading eyebrow="Campaign" step="Live" title={<>Campaign <code>{c.id.slice(0, 12)}</code><StateBadge state={c.state} /></>}
        intro={STATE_MEANING[c.state]} progress={c.budget.discovery ? c.budget.discoveryUsed / c.budget.discovery : null} />
      <ErrorBox error={campaign.error} title="Showing the last known state" />
      <ErrorBox error={events.error} title="Event log not current: episode and stop details below may be stale" />
      <ErrorBox error={fixture.error} title="Bench status not current" />
      {c.agentError ? <Notice tone="bad">Agent stopped: {c.agentError}</Notice> : null}
      {lock ? (
        <Notice tone="bad"><strong id="lockout">Locked out: {lock.cause}</strong>
          <ul>{lock.checklist.map(item => <li key={item}>{item}</li>)}</ul>
          <p>Clearing the lockout needs a reviewer; see below.</p>
        </Notice>
      ) : null}
      {stop ? <Notice tone="info"><strong>{stop.headline}</strong> <code>{stop.reasonCode}</code> {stop.reason} ({stop.actor})</Notice> : null}
      <Section title="Actions" index={1} tag="Operator">
        <div className="row">
          {allowedActions(c.state).filter(a => !a.reviewer && !a.checklistOnly).map(a =>
            <ActionButton key={a.action} action={a.action} campaignId={c.id} version={c.version} onResult={done} />)}
          <Link className="button secondary" href={`/campaigns/${c.id}/results`}>Results <span className="arrow" aria-hidden="true">→</span></Link>
        </div>
        <ErrorBox error={actionError} title="Action refused" />
        {reasons.length ? <Notice tone="warn"><ul>{reasons.map((r, i) => <li key={i}><code>{r.code}</code> {r.message}</li>)}</ul></Notice> : null}
      </Section>
      {c.state === "READY" ? <ArmChecklist campaign={c} fixture={fixture.data} serverReasons={serverReasons} onResult={done} /> : null}
      {c.state === "LOCKED_OUT" ? <ClearLockout campaign={c} onDone={r => done("clear-lockout", r)} /> : null}
      <Section title="Progress" index={2 + extra} tag="Budget">
        <div className="stats">
          <Stat label="Discovery" value={c.budget.discoveryUsed} of={c.budget.discovery} />
          <Stat label="Verification" value={c.budget.verificationUsed} of={c.budget.verification} />
          <Stat label="Rejected candidates" value={c.candidatesRejected} sub="counted, never executed" />
          <Stat label="Planner" value={c.planner.method} sub={`seed ${c.seed} · fixture ${c.fixtureId}`} small />
        </div>
        <KeyValues rows={[["Outcomes", outcomes]]} />
      </Section>
      <div className="grid2">
        <Section title="Current episode" index={3 + extra} tag={current ? current.phase : "Idle"}>
          {current ? <KeyValues rows={[
            ["Episode", <code key="e">{current.episodeId.slice(0, 12)}</code>],
            ["Phase", current.phase],
            ["Lease owner", current.leaseOwner ?? "unknown"],
            ["Last heartbeat", formatAge(ageSeconds(current.lastHeartbeat, now))],
            ...(current.leaseProblem ? [["Lease problem", current.leaseProblem] as [string, string]] : []),
          ]} /> : <Empty>No episode is running.</Empty>}
        </Section>
        <Section title="Bench" index={4 + extra} tag={c.fixtureId}>
          <div className="bench" role="list" aria-label="Bench status">
            {benchStatus(fixture.data).map(l => (
              <div key={l.id} role="listitem" className={l.ok === null ? "unk" : l.ok ? "ok" : "bad"}>{l.label}<small>{l.detail}</small></div>
            ))}
          </div>
        </Section>
      </div>
      <Section title="Event log" index={5 + extra} tag={`${log.length} events`}>
        <div className="table-wrap timeline"><table className="grid"><tbody>
          {[...log].reverse().slice(0, 40).map(e => (
            <tr key={e.id}><td>{e.backendTs.slice(11, 19)}</td><td>{e.entity}</td><td>{e.newState}</td><td><code>{e.reasonCode}</code></td><td>{e.reason}</td></tr>
          ))}
        </tbody></table></div>
      </Section>
    </>
  );
}
