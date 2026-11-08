"use client";

import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { actionSpec, stateTone, STATE_MEANING, type CampaignAction } from "@/lib/actions";
import { api } from "@/components/api";
import type { ApiResult, CampaignState, UiError } from "@/lib/types";

export function StateBadge({ state }: { state: CampaignState | string }) {
  const tone = stateTone(state as CampaignState);
  const title = STATE_MEANING[state as CampaignState] ?? "";
  return <span className={`badge badge-${tone}`} title={title}>{state}</span>;
}

export function ErrorBox({ error, title }: { error: UiError | null; title?: string }) {
  if (!error) return null;
  return (
    <div className="alert alert-bad" role="alert">
      <strong>{title ?? "Error"} <code>{error.code}</code></strong>
      <p>{error.message}</p>
      {error.reasons?.length ? (
        <ul>{error.reasons.map((r, i) => <li key={i}><code>{r.code}</code> {r.message}</li>)}</ul>
      ) : null}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "bad" | "ok"; children: ReactNode }) {
  return <div className={`alert alert-${tone}`} role={tone === "bad" ? "alert" : "status"}>{children}</div>;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** Eyebrow, display title and intro; optional actions on the right and a progress bar underneath. */
export function PageHeading({ eyebrow, step, title, intro, actions, progress }: {
  eyebrow: string; step?: string; title: ReactNode; intro?: ReactNode; actions?: ReactNode; progress?: number | null;
}) {
  return (
    <div className="page-heading-wrap">
      <div className="page-heading">
        <div className="page-heading-text">
          <div className="eyebrow">{eyebrow}{step ? <span> / {step}</span> : null}</div>
          <h1>{title}</h1>
          {intro ? <p className="intro">{intro}</p> : null}
        </div>
        {actions ? <div className="page-actions">{actions}</div> : null}
      </div>
      {progress !== undefined && progress !== null ? <ProgressBar value={progress} label="Progress" /> : null}
    </div>
  );
}

/** Card with a numbered badge, a display heading and a small upper-case tag (or custom content) on the right. */
export function Section({ title, children, id, aside, index, tag }: {
  title: string; children: ReactNode; id?: string; aside?: ReactNode; index?: number; tag?: string;
}) {
  return (
    <section className="card" id={id} aria-labelledby={id ? id + "-h" : undefined}>
      <div className="card-heading">
        <div>{index !== undefined ? <span className="section-index" aria-hidden="true">{pad(index)}</span> : null}<h2 id={id ? id + "-h" : undefined}>{title}</h2></div>
        {aside ?? (tag ? <span className="card-tag">{tag}</span> : null)}
      </div>
      {children}
    </section>
  );
}

/** Thin progress bar; `value` is a fraction from 0 to 1. */
export function ProgressBar({ value, label, thin }: { value: number; label: string; thin?: boolean }) {
  const pct = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0)) * 100;
  return (
    <div className={`progress${thin ? " thin" : ""}`} role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}

/** A labelled number tile, optionally with a progress bar (used for budgets). */
export function Stat({ label, value, sub, of, small }: { label: string; value: ReactNode; sub?: ReactNode; of?: number; small?: boolean }) {
  const n = typeof value === "number" ? value : NaN;
  return (
    <div className="stat">
      <span>{label}</span>
      <strong className={small ? "small" : undefined}>{value}{of !== undefined ? <small style={{ display: "inline", fontSize: 13 }}> / {of}</small> : null}</strong>
      {sub ? <small>{sub}</small> : null}
      {of !== undefined && of > 0 && Number.isFinite(n) ? <ProgressBar value={n / of} label={label} thin /> : null}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

export function Loading({ what }: { what: string }) {
  return <div className="skeleton" role="status"><p>Loading {what}…</p><div /><div /><div /></div>;
}

export function KeyValues({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="kv">{rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>;
}

export function Mono({ children }: { children: ReactNode }) { return <code className="mono">{children}</code>; }

/** A one-shot copy box, used for the bench token that is shown a single time. */
export function CopyBox({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div className="copybox">
      <label>{label}
        <input ref={ref} readOnly value={value} onFocus={e => e.currentTarget.select()} />
      </label>
      <button type="button" onClick={() => { ref.current?.select(); void navigator.clipboard?.writeText(value).then(() => setCopied(true), () => setCopied(false)); }}>
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

export function ConditionsTable({ conditions }: { conditions: Record<string, unknown> }) {
  const entries = Object.entries(conditions);
  if (!entries.length) return <Empty>No conditions.</Empty>;
  return (
    <div className="table-wrap"><table className="grid"><tbody>
      {entries.map(([k, v]) => <tr key={k}><th scope="row">{k}</th><td className="num">{typeof v === "string" ? v : JSON.stringify(v)}</td></tr>)}
    </tbody></table></div>
  );
}

// ---------------------------------------------------------------- reviewer passphrase modal

export type PassphraseRequest = {
  title: string;
  description: string;
  confirmLabel: string;
  /** Runs the call with the passphrase. The passphrase is not retained after this returns. */
  run: (passphrase: string) => Promise<ApiResult<unknown>>;
  onDone: (result: ApiResult<unknown>) => void;
};

/**
 * Asks for the reviewer passphrase for ONE action. The value lives only in the uncontrolled input element: it is read
 * on submit, passed to `run`, and the input is cleared. It is never put in React state, storage, cookies or logs.
 */
export function PassphraseModal({ request, onClose }: { request: PassphraseRequest; onClose: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<UiError | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    const passphrase = input.current?.value ?? "";
    if (!passphrase) return;
    setBusy(true); setError(null);
    const result = await request.run(passphrase);
    if (input.current) input.current.value = "";
    setBusy(false);
    if (result.ok) { request.onDone(result); onClose(); }
    else if (result.error.code === "PERMISSION_DENIED") setError(result.error);
    else { request.onDone(result); onClose(); }
  }
  return (
    <div className="modal-backdrop" onKeyDown={e => { if (e.key === "Escape") onClose(); }}>
      <form className="modal" role="dialog" aria-modal="true" aria-labelledby="pp-title" onSubmit={submit}>
        <h2 id="pp-title">{request.title}</h2>
        <p>{request.description}</p>
        <label>Reviewer passphrase
          <input ref={input} type="password" autoComplete="off" autoFocus required />
        </label>
        <p className="hint">The passphrase is sent with this one request and is not stored.</p>
        <ErrorBox error={error} title="Passphrase not accepted" />
        <div className="row">
          <button type="submit" disabled={busy}>{busy ? "Working..." : request.confirmLabel}</button>
          <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------- campaign action button

export function ActionButton({ action, campaignId, version, onResult, disabled, body }: {
  action: CampaignAction; campaignId: string; version: number; disabled?: boolean;
  onResult: (action: CampaignAction, result: ApiResult<unknown>) => void; body?: Record<string, unknown>;
}) {
  const spec = actionSpec(action);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  async function run() {
    setBusy(true); setConfirm(false);
    const result = await api<unknown>(`/v1/campaigns/${encodeURIComponent(campaignId)}:${action}`, { method: "POST", body: { campaignVersion: version, ...body } });
    setBusy(false);
    onResult(action, result);
  }
  if (spec.danger && !confirm) {
    return <button type="button" className="danger" disabled={busy || disabled} onClick={() => setConfirm(true)}>{spec.label}</button>;
  }
  if (spec.danger && confirm) {
    return (
      <span className="confirm-inline" role="group" aria-label={`Confirm ${spec.label}`}>
        <button type="button" className="danger" onClick={() => void run()} autoFocus>Yes, {action === "abort" ? "abort now" : action}</button>
        <button type="button" className="secondary" onClick={() => setConfirm(false)}>No</button>
      </span>
    );
  }
  return <button type="button" disabled={busy || disabled} onClick={() => void run()}>{busy ? "Working..." : spec.label}</button>;
}
