"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { api, useLoad } from "@/components/api";
import { ErrorBox, Loading, Notice, PageHeading, Section, StateBadge } from "@/components/ui";
import { controlInputs, type ControlInput } from "@/lib/manual";
import { formatValue } from "@/lib/results";
import type { CampaignContract, CampaignView, CandidateResult, Conditions, EpisodeDetail, JsonValue, UiError } from "@/lib/types";

type Tried = { conditions: Conditions; result: CandidateResult };

function ControlField({ c, value, onChange }: { c: ControlInput; value: JsonValue; onChange: (v: JsonValue) => void }) {
  if (c.kind === "boolean") return <label className="check"><input type="checkbox" checked={value === true} onChange={e => onChange(e.target.checked)} />{c.name}</label>;
  if (c.kind === "choice") return <label>{c.name}<select value={String(value)} onChange={e => onChange(e.target.value)}>{c.values.map(v => <option key={v}>{v}</option>)}</select></label>;
  return (
    <label>{c.name} <span className="hint">({formatValue(c.min)}–{formatValue(c.max)} {c.unit}, step {formatValue(c.step)}{c.activeWhen ? `; only when ${c.activeWhen}` : ""})</span>
      <input type="range" min={c.min} max={c.max} step={c.step} value={Number(value)} onChange={e => onChange(Number(e.target.value))} aria-label={`${c.name} slider`} />
      <input type="text" inputMode="decimal" value={String(value)} onChange={e => onChange(e.target.value.trim() === "" || Number.isNaN(Number(e.target.value)) ? e.target.value : Number(e.target.value))} />
    </label>
  );
}

function Outcome({ episodeId }: { episodeId: string }) {
  const { data } = useLoad<EpisodeDetail>(`/v1/episodes/${encodeURIComponent(episodeId)}`, 2000);
  if (!data?.verdict) return <span className="chip">Running…</span>;
  const v = data.verdict;
  return <span className={`chip ${v.outcome === "PASS" ? "ok" : v.outcome === "DUT_FAILURE" ? "bad" : ""}`}>{v.outcome} · {v.reasonCode}</span>;
}

/** PRD §18.1 manual challenge: a person picks conditions; the same safety rules check every pick. */
export default function ManualPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const base = `/v1/campaigns/${encodeURIComponent(id)}`;
  const campaign = useLoad<CampaignView>(base, 3000);
  const info = useLoad<CampaignContract>(`${base}/contract`);
  const inputs = info.data ? controlInputs(info.data.contract) : [];
  const [values, setValues] = useState<Conditions>({});
  const [note, setNote] = useState("");
  const [tried, setTried] = useState<Tried[]>([]);
  const [error, setError] = useState<UiError | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (inputs.length && !Object.keys(values).length) setValues(Object.fromEntries(inputs.map(c => [c.name, c.nominal]))); }, [inputs, values]);
  if (campaign.loading || info.loading) return <Loading what="the contract controls" />;
  const c = campaign.data;
  async function submit() {
    setBusy(true); setError(null);
    const r = await api<CandidateResult>(`${base}/manual-candidates`, { method: "POST", body: { conditions: values, note: note.trim() } });
    setBusy(false);
    if (r.ok) setTried(t => [{ conditions: { ...values }, result: r.data }, ...t]); else setError(r.error);
  }
  return (
    <>
      <PageHeading eyebrow="Campaign" step="Manual challenge" title={<>Pick a test yourself {c ? <StateBadge state={c.state} /> : null}</>}
        intro={<>Choose any conditions. The same deterministic safety rules check your pick before anything reaches the bench, and an out-of-range value is refused, never run. <Link href={`/campaigns/${id}`}>Back to the live view</Link></>} />
      <ErrorBox error={campaign.error ?? info.error} title="Could not load the campaign" />
      {c && c.state !== "RUNNING" ? <Notice tone="warn">The campaign is {c.state}. Manual picks are accepted only while it is RUNNING.</Notice> : null}
      <Section title="Your conditions" index={1} tag="Checked by the safety rules">
        <div className="fields">{inputs.map(ci => <ControlField key={ci.name} c={ci} value={values[ci.name] ?? ci.nominal} onChange={v => setValues(s => ({ ...s, [ci.name]: v }))} />)}</div>
        <label style={{ marginTop: 18 }}>Note (optional)<input value={note} onChange={e => setNote(e.target.value)} placeholder="who picked it, and why" /></label>
        <ErrorBox error={error} title="Pick not submitted" />
        <div className="card-actions">
          <span className="action-note">A manual pick counts against the discovery budget and is labelled MANUAL in the report.</span>
          <button type="button" className="secondary" onClick={() => setValues(Object.fromEntries(inputs.map(ci => [ci.name, ci.nominal])))}>Reset to nominal</button>
          <button type="button" disabled={busy || c?.state !== "RUNNING"} onClick={() => void submit()}>{busy ? "Checking…" : "Check and run"} <span className="arrow" aria-hidden="true">→</span></button>
        </div>
      </Section>
      <Section title="Your picks" index={2} tag={`${tried.length} this session`}>
        {tried.length === 0 ? <p className="empty">Nothing picked yet.</p> : (
          <ol className="steps">{tried.map(t => (
            <li key={t.result.candidateId}>
              <span className="role">#{t.result.plannerSequence}</span>
              <span className="num">{Object.entries(t.conditions).map(([k, v]) => `${k}=${formatValue(v)}`).join(", ")}</span>
              <span>{t.result.state === "REJECTED"
                ? <span className="chip bad" title={t.result.violations.map(v => v.message).join("; ")}>Refused: {t.result.violations.map(v => v.code).join(", ")}</span>
                : t.result.episodeId ? <><Outcome episodeId={t.result.episodeId} /> <Link href={`/episodes/${t.result.episodeId}`}>open</Link></> : <span className="chip">{t.result.state}</span>}</span>
            </li>
          ))}</ol>
        )}
        <p className="hint" style={{ marginTop: 12 }}>This is illustrative, not a fair human-versus-planner experiment (PRD §18.1).</p>
      </Section>
    </>
  );
}
