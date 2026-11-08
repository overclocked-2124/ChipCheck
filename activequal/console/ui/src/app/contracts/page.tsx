"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, recentAdd, recentGet } from "@/components/api";
import { ErrorBox, KeyValues, Mono, Notice, PageHeading, Section } from "@/components/ui";
import { applyForm, EMPTY_FORM, parseContractText, prettyJson, readForm, type ContractForm } from "@/lib/contractForm";
import { OLED_TEMPLATE } from "@/lib/contractTemplate";
import type { ContractSummary, UiError } from "@/lib/types";

const FIELD_LABELS: [keyof ContractForm, string][] = [
  ["dut", "DUT"], ["firmwareSha256", "Firmware SHA-256"], ["fixture", "Fixture id"], ["fixtureRev", "Fixture revision"],
  ["budget", "Total budget (episodes)"], ["seed", "Seed"], ["maxTempC", "Max temperature (C)"], ["maxEpisodeS", "Max episode time (s)"],
];

export default function ContractsPage() {
  const router = useRouter();
  const [text, setText] = useState(() => prettyJson(OLED_TEMPLATE));
  const [contractId, setContractId] = useState("");
  const [saved, setSaved] = useState<ContractSummary | null>(null);
  const [error, setError] = useState<UiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [openId, setOpenId] = useState("");
  const [openVersion, setOpenVersion] = useState("1");
  const [recents, setRecents] = useState<string[]>([]);
  useEffect(() => setRecents(recentGet("contracts")), []);

  const parsed = useMemo(() => parseContractText(text), [text]);
  const form = parsed.ok ? readForm(parsed.value) : EMPTY_FORM;

  function onField(key: keyof ContractForm, value: string) {
    if (!parsed.ok) return;
    setText(prettyJson(applyForm(parsed.value, { ...EMPTY_FORM, [key]: value })));
  }

  async function save() {
    if (!parsed.ok) return;
    setBusy(true); setError(null); setSaved(null);
    const res = await api<ContractSummary>("/v1/contracts", { body: { contract: parsed.value, ...(contractId.trim() ? { contractId: contractId.trim() } : {}) } });
    setBusy(false);
    if (res.ok) { setSaved(res.data); recentAdd("contracts", `${res.data.contractId}@${res.data.version}`); setRecents(recentGet("contracts")); }
    else setError(res.error);
  }

  return (
    <>
      <PageHeading eyebrow="Configure" step="Contracts" title="Test contracts"
        intro="The contract defines the controls, limits and requirements of one setup. The planner cannot change it. Every save creates a version; approval is always on the canonical JSON the server stores." />
      <Section title="Contract editor" id="editor" index={1} tag="HLD 04 §12">
        <div className="stack">
          <div className="fields">
            {FIELD_LABELS.map(([key, label]) => (
              <label key={key}>{label}
                <input value={form[key]} disabled={!parsed.ok} onChange={e => onField(key, e.target.value)} />
              </label>
            ))}
            <label>Add a version to an existing contract id (optional)
              <input value={contractId} onChange={e => setContractId(e.target.value)} placeholder="leave empty for a new contract" />
            </label>
          </div>
          <label>Contract JSON (v2, HLD 04 §12)
            <textarea rows={22} value={text} onChange={e => { setText(e.target.value); setSaved(null); }} spellCheck={false} aria-invalid={!parsed.ok} aria-describedby="json-status" />
          </label>
          <div id="json-status">
            {parsed.ok ? <span className="ok-text">JSON looks like a v2 contract. The control plane has the final say.</span>
              : <span className="bad-text" role="alert">{parsed.error}</span>}
          </div>
          <div className="card-actions">
            <button type="button" className="secondary" onClick={() => setText(prettyJson(OLED_TEMPLATE))}>Load the ESP32-S3 OLED example</button>
            {parsed.ok ? <button type="button" className="secondary" onClick={() => setText(prettyJson(parsed.value))}>Reformat</button> : null}
            <button type="button" onClick={() => void save()} disabled={!parsed.ok || busy}>{busy ? "Saving…" : "Save contract version"} <span className="arrow" aria-hidden="true">→</span></button>
          </div>
          <ErrorBox error={error} title="The control plane rejected this contract" />
          {saved ? (
            <Notice tone={saved.approved ? "ok" : "info"}>
              <strong>Saved version {saved.version} of contract <Mono>{saved.contractId}</Mono>.</strong>
              <KeyValues rows={[
                ["Canonical hash", <Mono key="h">{saved.contractHash}</Mono>],
                ["Approval", `${saved.approvedBy.length} of ${saved.approvalsRequired} approvals${saved.approved ? " (approved)" : " (not approved yet)"}`],
              ]} />
              <p><Link href={`/contracts/${saved.contractId}/${saved.version}`}>Review the canonical JSON and approve</Link></p>
            </Notice>
          ) : null}
        </div>
      </Section>
      <Section title="Open a contract version" id="open" index={2} tag="Review">
        <form className="row openform" onSubmit={e => { e.preventDefault(); if (openId.trim()) router.push(`/contracts/${encodeURIComponent(openId.trim())}/${Number(openVersion) || 1}`); }}>
          <label style={{ flex: 1 }}>Contract id<input value={openId} onChange={e => setOpenId(e.target.value)} required /></label>
          <label>Version<input type="number" min={1} value={openVersion} onChange={e => setOpenVersion(e.target.value)} style={{ width: "6rem" }} /></label>
          <button type="submit">Open <span className="arrow" aria-hidden="true">→</span></button>
        </form>
        {recents.length ? <p className="hint">Recently used on this browser: {recents.map(r => { const [id, v] = r.split("@"); return <span key={r}><Link href={`/contracts/${id}/${v}`}>{r.slice(0, 20)}</Link>{" "}</span>; })}</p> : null}
        <p className="hint">The control plane has no contract list endpoint yet, so versions are opened by id.</p>
      </Section>
    </>
  );
}
