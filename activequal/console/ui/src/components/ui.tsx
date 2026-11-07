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

export function Section({ title, children, id, aside }: { title: string; children: ReactNode; id?: string; aside?: ReactNode }) {
  return (
    <section className="card" aria-labelledby={id ? id + "-h" : undefined}>
      <div className="card-head"><h2 id={id ? id + "-h" : undefined}>{title}</h2>{aside}</div>
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

export function Loading({ what }: { what: string }) {
  return <p className="loading" role="status">Loading {what}...</p>;
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
    <table className="grid"><tbody>
      {entries.map(([k, v]) => <tr key={k}><th scope="row">{k}</th><td>{typeof v === "string" ? v : JSON.stringify(v)}</td></tr>)}
    </tbody></table>
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
