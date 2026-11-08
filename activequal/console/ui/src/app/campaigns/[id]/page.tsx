"use client";

import Link from "next/link";
import { use, useMemo, useState } from "react";
import { useLoad, useNow } from "@/components/api";
import { ArmChecklist, ClearLockout } from "@/components/campaign-controls";
import { HistoryChart, Legend, OutcomeStrip } from "@/components/charts";
import { CurrentEpisode, LatestOutcome, Reasons, ReconcileLease } from "@/components/live-panels";
import { useCampaignEvents } from "@/components/use-events";
import { ErrorBox, KeyValues, Loading, Notice, PageHeading, Section, Stat, StateBadge, ActionButton } from "@/components/ui";
import { allowedActions, STATE_MEANING, type CampaignAction } from "@/lib/actions";
import { HEALTH_MAX_AGE_S } from "@/lib/arming";
import { activeEpisode, ageSeconds, benchStatus, formatAge, lockoutInfo, shutdownStatus, stopExplanation } from "@/lib/live";
import { tracksFrom } from "@/lib/region";
import type { ApiResult, CampaignContract, CampaignView, FixtureView, LeaseView, RecordsResponse, UiError } from "@/lib/types";

export default function CampaignPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const base = `/v1/campaigns/${encodeURIComponent(id)}`;
  const campaign = useLoad<CampaignView>(base, 2000);
  const events = useCampaignEvents(id);
  const lease = useLoad<{ lease: LeaseView | null }>(`${base}/lease`, 2000);
  const records = useLoad<RecordsResponse>(`${base}/records`, 3000);
  const info = useLoad<CampaignContract>(`${base}/contract`, 15000);
  const fixtureId = campaign.data?.fixtureId ?? null;
  const fixture = useLoad<FixtureView>(fixtureId ? `/v1/fixtures/${encodeURIComponent(fixtureId)}` : null, 3000);
  const [actionError, setActionError] = useState<UiError | null>(null);
  const [reasons, setReasons] = useState<{ code: string; message: string }[]>([]);
  const [serverReasons, setServerReasons] = useState<{ code: string; message: string }[] | null>(null);
  const tracks = useMemo(() => tracksFrom(info.data?.contract), [info.data]);
  const now = useNow(1000);

  const c = campaign.data;
  if (campaign.loading) return <Loading what="campaign" />;
  if (!c) return <ErrorBox error={campaign.error} title="Could not load the campaign" />;
  const log = events.events;
  const stop = stopExplanation(c.state, log);
  const lock = lockoutInfo(c.state, log);
  const shutdown = shutdownStatus(fixture.data?.health ?? null, log, c.state);
  const live = lease.data?.lease ?? null;
  const eps = records.data?.episodes ?? [];
  const rejected = records.data?.rejected ?? [];
  const healthAge = ageSeconds(fixture.data?.healthAt, now);
  const healthStale = healthAge === null || healthAge > HEALTH_MAX_AGE_S;

  function done(action: CampaignAction, result: ApiResult<unknown>) {
    setActionError(null); setReasons([]);
    if (result.ok) {
      if (action === "validate") { const r = (result.data as CampaignView).reasons ?? []; setReasons(r); setServerReasons(r); }
      void campaign.reload(); void events.reload(); void lease.reload(); void records.reload();
    } else {
      // HLD 09 §6: on a stale version, refresh and say so, so the person sees what changed before acting again.
      const stale = result.error.code === "STALE_VERSION";
      setActionError(stale ? { ...result.error, message: `${result.error.message}. The page has refreshed to the current state; check it before acting again.` } : result.error);
      setReasons(result.error.reasons ?? []); if (action === "arm") setServerReasons(result.error.reasons ?? []);
      if (stale) { void campaign.reload(); void events.reload(); }
    }
  }
  let n = c.state === "READY" || c.state === "LOCKED_OUT" ? 2 : 1;   // the checklist or lockout card is section 02
  const next = () => ++n;

  return (
    <>
      <PageHeading eyebrow="Campaign" step="Live" title={<>Campaign <code>{c.id.slice(0, 12)}</code><StateBadge state={c.state} /></>}
        intro={STATE_MEANING[c.state]} progress={c.budget.discovery ? c.budget.discoveryUsed / c.budget.discovery : null}
        actions={c.state === "RUNNING" ? <Link className="button secondary" href={`/campaigns/${c.id}/manual`}>Manual challenge</Link> : null} />
      <ErrorBox error={campaign.error} title="Showing the last known state" />
      <ErrorBox error={events.error} title="Event log not current: episode and stop details below may be stale" />
      <ErrorBox error={fixture.error} title="Bench status not current" />
      {c.agentError ? <Notice tone="bad">Agent stopped: {c.agentError}</Notice> : null}
      {live?.state === "NEEDS_RECONCILIATION" ? <ReconcileLease lease={live} onDone={() => done("abort", { ok: true, data: null })} /> : null}
      {lock ? (
        <Notice tone="bad"><strong id="lockout">Locked out: {lock.cause}</strong> <code>{lock.code}</code>
          <ul>{lock.checklist.map(item => <li key={item}>{item}</li>)}</ul>
          <p>Clearing the lockout needs a reviewer; see below.</p>
        </Notice>
      ) : null}
      {stop && !lock ? <Notice tone={c.state === "COMPLETED" ? "ok" : c.state === "LOCKED_OUT" ? "bad" : "info"}><strong>{stop.headline}.</strong> <code>{stop.reasonCode}</code> {stop.reason} ({stop.actor})</Notice> : null}
      <Section title="Actions" index={1} tag="Operator">
        <div className="row">
          {allowedActions(c.state).filter(a => !a.reviewer && !a.checklistOnly).map(a =>
            <ActionButton key={a.action} action={a.action} campaignId={c.id} version={c.version} onResult={done} />)}
          <Link className="button secondary" href={`/campaigns/${c.id}/results`}>Results <span className="arrow" aria-hidden="true">→</span></Link>
        </div>
        <p className="hint" style={{ marginTop: 10 }}>The physical E-stop is always faster than any button here.</p>
        <ErrorBox error={actionError} title="Action refused" />
        {reasons.length ? <Notice tone="warn"><ul>{reasons.map((r, i) => <li key={i}><code>{r.code}</code> {r.message}</li>)}</ul></Notice> : null}
      </Section>
      {c.state === "READY" ? <ArmChecklist campaign={c} fixture={fixture.data} info={info.data} serverReasons={serverReasons} onResult={done} /> : null}
      {c.state === "LOCKED_OUT" ? <ClearLockout campaign={c} onDone={r => done("clear-lockout", r)} /> : null}
      <Section title="Progress" index={next()} tag="Budget">
        <div className="stats">
          <Stat label="Discovery" value={c.budget.discoveryUsed} of={c.budget.discovery} />
          <Stat label="Verification" value={c.budget.verificationUsed} of={c.budget.verification} />
          <Stat label="Refused candidates" value={c.candidatesRejected} sub="counted, never executed" />
          <Stat label="Planner" value={c.planner.method} sub={`seed ${c.seed} · fixture ${c.fixtureId}`} small />
        </div>
        <KeyValues rows={[["Outcomes", Object.entries(c.episodesByOutcome).map(([k, v]) => `${k} ${v}`).join(", ") || "none yet"]]} />
      </Section>
      <div className="grid2">
        <CurrentEpisode index={next()} current={activeEpisode(log)} lease={live} maxEpisodeS={info.data?.maxEpisodeS ?? null} />
        <Section title="Bench" index={next()} tag={c.fixtureId}>
          {healthStale ? <Notice tone="warn"><strong>Bench state unknown.</strong> The last health report is {formatAge(healthAge)}; the tiles below show that old report, not the bench now. Check the fixture and the E-stop in person.</Notice> : null}
          <div className="bench" role="list" aria-label="Bench status" style={healthStale ? { opacity: 0.55, marginTop: 14 } : undefined}>
            <div role="listitem" className={healthStale ? "unk" : "ok"}>Health report<small>{formatAge(healthAge)}{healthStale ? " (stale)" : ""}</small></div>
            {benchStatus(fixture.data).map(l => (
              <div key={l.id} role="listitem" className={l.ok === null || healthStale ? "unk" : l.ok ? "ok" : "bad"}>{l.label}<small>{l.detail}{healthStale ? " (last known)" : ""}</small></div>
            ))}
            <div role="listitem" className={shutdown.confirmed === null || (healthStale && shutdown.confirmed) ? "unk" : shutdown.confirmed ? "ok" : "bad"}>Shutdown<small>{shutdown.text}</small></div>
          </div>
        </Section>
      </div>
      <LatestOutcome index={next()} records={eps} tracks={tracks} />
      <Section title="Outcome timeline" index={next()} tag={`${eps.length} episodes`}>
        <div className="stack">
          <OutcomeStrip records={eps} />
          <HistoryChart records={eps} />
          <Legend />
        </div>
      </Section>
      <Reasons index={next()} records={eps} rejected={rejected} />
      <Section title="Event log" index={next()} tag={`${log.length} events`}>
        <div className="table-wrap timeline"><table className="grid"><tbody>
          {[...log].reverse().slice(0, 60).map(e => (
            <tr key={e.id}><td>{e.backendTs.slice(11, 19)}</td><td>{e.entity}</td><td>{e.newState}</td><td><code>{e.reasonCode}</code></td>
              <td>{e.episodeId ? <Link href={`/episodes/${e.episodeId}`}>{e.reason}</Link> : e.reason}</td></tr>
          ))}
        </tbody></table></div>
      </Section>
    </>
  );
}
