"use client";

import Link from "next/link";
import { useState } from "react";
import { api, useNow } from "@/components/api";
import { Empty, ErrorBox, KeyValues, Notice, PassphraseModal, Section, type PassphraseRequest } from "@/components/ui";
import { ageSeconds, formatAge, type ActiveEpisode } from "@/lib/live";
import { countBy, type Tracks } from "@/lib/region";
import { formatValue } from "@/lib/results";
import { OUTCOME_STYLE } from "@/lib/series";
import type { ApiResult, EpisodeRecord, LeaseView, RejectedRecord, UiError } from "@/lib/types";

/** HLD 03 §22: current episode and physical phase, lease owner, the real last heartbeat, remaining episode time. */
export function CurrentEpisode({ index, current, lease, maxEpisodeS }: {
  index: number; current: ActiveEpisode | null; lease: LeaseView | null; maxEpisodeS: number | null;
}) {
  const now = useNow(1000);
  if (!current && !lease) return <Section title="Current episode" index={index} tag="Idle"><Empty>No episode is running.</Empty></Section>;
  const issued = lease ? Date.parse(lease.issuedAt) : NaN;
  const elapsed = Number.isFinite(issued) ? Math.max(0, (now - issued) / 1000) : null;
  const remaining = elapsed !== null && maxEpisodeS !== null ? Math.max(0, maxEpisodeS - elapsed) : null;
  const beat = ageSeconds(lease?.lastHeartbeatAt, now);
  return (
    <Section title="Current episode" index={index} tag={current?.phase ?? lease?.state ?? "—"}>
      <KeyValues rows={[
        ["Episode", current || lease ? <Link key="e" href={`/episodes/${current?.episodeId ?? lease!.episodeId}`}><code>{(current?.episodeId ?? lease!.episodeId).slice(0, 12)}</code></Link> : "—"],
        ["Physical phase", current?.phase ?? "unknown"],
        ["Lease owner", lease?.owner ?? current?.leaseOwner ?? "unknown"],
        ["Last heartbeat", lease ? <span key="b" className={beat !== null && beat > 5 ? "bad-text" : undefined}>{formatAge(beat)}</span> : "no live lease"],
        ["Episode time left", remaining === null ? "unknown" : `${remaining.toFixed(0)} s of ${maxEpisodeS} s`],
        ["Lease expires", lease?.expiresAt ?? "—"],
      ]} />
    </Section>
  );
}

/** An expired lease stops the campaign until a reviewer says what happened (HLD 03 §9). */
export function ReconcileLease({ lease, onDone }: { lease: LeaseView; onDone: () => void }) {
  const [resolution, setResolution] = useState("not_executed");
  const [note, setNote] = useState("");
  const [modal, setModal] = useState<PassphraseRequest | null>(null);
  const [error, setError] = useState<UiError | null>(null);
  function open() {
    setModal({
      title: "Reconcile the expired lease",
      description: "Record what happened to this episode. It finishes as INVALID and the campaign locks out for a physical inspection.",
      confirmLabel: "Reconcile",
      run: passphrase => api(`/v1/leases/${encodeURIComponent(lease.id)}:reconcile`, { method: "POST", passphrase, body: { resolution, note: note.trim() } }),
      onDone: (r: ApiResult<unknown>) => { if (r.ok) onDone(); else setError(r.error); },
    });
  }
  return (
    <Notice tone="bad">
      <strong>The bench stopped reporting during an episode (lease {lease.id.slice(0, 12)} needs reconciliation).</strong>
      <p>Nothing else runs on this fixture until a reviewer records what happened. Check the fixture first.</p>
      <div className="fields" style={{ marginTop: 10 }}>
        <label>What happened
          <select value={resolution} onChange={e => setResolution(e.target.value)}>
            <option value="not_executed">The episode did not run (no power was applied)</option>
            <option value="evidence_lost">It may have run, but its evidence is lost</option>
          </select>
        </label>
        <label>Note<input value={note} onChange={e => setNote(e.target.value)} placeholder="what you checked at the bench" /></label>
      </div>
      <div className="row" style={{ marginTop: 12 }}><button type="button" disabled={!note.trim()} onClick={open}>Reconcile (reviewer)</button></div>
      <ErrorBox error={error} title="Reconciliation refused" />
      {modal ? <PassphraseModal request={modal} onClose={() => setModal(null)} /> : null}
    </Notice>
  );
}

/** The latest finished episode: outcome and reason, with requested and measured values side by side. */
export function LatestOutcome({ index, records, tracks }: { index: number; records: EpisodeRecord[]; tracks: Tracks }) {
  const done = records.filter(r => r.outcome).sort((a, b) => b.plannerSequence - a.plannerSequence);
  const last = done[0];
  if (!last) return <Section title="Latest outcome" index={index} tag="None yet"><Empty>No episode has finished.</Empty></Section>;
  const label = OUTCOME_STYLE[last.outcome!]?.label ?? last.outcome;
  const rows: [string, string][] = Object.entries(last.requested).map(([k, v]) => {
    const metric = tracks[k];
    const m = metric ? last.measured[metric] : undefined;
    return [k, m ? `${formatValue(v)} requested · ${formatValue(m.value)} measured` : formatValue(v)];
  });
  return (
    <Section title="Latest outcome" index={index} tag={`#${last.plannerSequence} ${last.role}`}>
      <p><span className={`chip ${last.outcome === "PASS" ? "ok" : last.outcome === "DUT_FAILURE" || last.outcome === "SAFETY_ABORT" ? "bad" : ""}`}>{label}</span>{" "}
        <code>{last.verdict?.reasonCode}</code> {last.verdict?.reason}
        {last.verdict?.robustness !== null && last.verdict?.robustness !== undefined ? <> · robustness {formatValue(last.verdict.robustness)}</> : null}</p>
      <p className="hint">Planner: {last.planner.reason}</p>
      <KeyValues rows={rows} />
      <p style={{ marginTop: 12 }}><Link href={`/episodes/${last.episodeId}`}>Open the episode →</Link></p>
    </Section>
  );
}

/** Why candidates were refused and why episodes were invalid (HLD 03 §22): never only in logs. */
export function Reasons({ index, records, rejected }: { index: number; records: EpisodeRecord[]; rejected: RejectedRecord[] }) {
  const refused = countBy(rejected.flatMap(r => r.violations), v => v.code);
  const invalid = records.filter(r => r.outcome === "INVALID_EXPERIMENT" || r.outcome === "SAFETY_ABORT");
  const invalidCounts = countBy(invalid, r => r.verdict?.reasonCode);
  return (
    <Section title="Refusals and invalid episodes" index={index} tag={`${rejected.length} refused · ${invalid.length} invalid or aborted`}>
      <div className="grid2">
        <div className="stack">
          <h3>Candidates refused by the safety rules</h3>
          {refused.length ? <ul className="steps">{refused.map(([code, n]) => <li key={code}><span className="role">{n}×</span><code>{code}</code><span /></li>)}</ul>
            : <Empty>None refused. Refused candidates never reach the bench and spend no budget.</Empty>}
          {rejected.slice(-3).map(r => <p key={r.candidateId} className="hint">#{r.plannerSequence}: {r.violations.map(v => v.message).join("; ")}</p>)}
        </div>
        <div className="stack">
          <h3>Invalid or safety-aborted episodes</h3>
          {invalidCounts.length ? <ul className="steps">{invalidCounts.map(([code, n]) => <li key={code}><span className="role">{n}×</span><code>{code}</code><span /></li>)}</ul>
            : <Empty>None. Invalid episodes never train the planner as pass or fail.</Empty>}
          {invalid.slice(-3).map(r => <p key={r.episodeId} className="hint"><Link href={`/episodes/${r.episodeId}`}>#{r.plannerSequence}</Link>: {r.verdict?.reason}</p>)}
        </div>
      </div>
    </Section>
  );
}
