"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, useLoad } from "@/components/api";
import { ErrorBox, KeyValues, Loading, Mono, Notice, PassphraseModal, Section, type PassphraseRequest } from "@/components/ui";
import { controlSummaries } from "@/lib/contractForm";
import { path } from "@/lib/client";
import type { ApiResult, ContractDetail, UiError } from "@/lib/types";

export default function ContractDetailPage() {
  const params = useParams<{ id: string; version: string }>();
  const id = decodeURIComponent(params.id), version = Number(params.version);
  const { data, error, loading, reload } = useLoad<ContractDetail>(path.contract(id, version));
  const [modal, setModal] = useState<PassphraseRequest | null>(null);
  const [actionError, setActionError] = useState<UiError | null>(null);
  const [done, setDone] = useState<string | null>(null);

  function approve() {
    setActionError(null); setDone(null);
    setModal({
      title: "Approve this contract version",
      description: "You are approving exactly the canonical JSON shown on this page (hash shown above it). Approval needs the reviewer passphrase. A new contract or a change to limits needs two approvals.",
      confirmLabel: "Approve",
      run: passphrase => api(path.approve(id, version), { method: "POST", body: {}, passphrase }),
      onDone: (r: ApiResult<unknown>) => { if (r.ok) { setDone("Approval recorded."); void reload(); } else setActionError(r.error); },
    });
  }

  return (
    <>
      <h1>Contract <Mono>{id}</Mono> version {version}</h1>
      <p><Link href="/contracts">Back to the contract editor</Link></p>
      {loading ? <Loading what="contract" /> : null}
      <ErrorBox error={error} title="Could not load this contract version" />
      {data ? (
        <>
          <Section title="Approval" id="approval">
            <KeyValues rows={[
              ["Approvals", <strong key="a">{data.approvedBy.length} of {data.approvalsRequired} approvals{data.approved ? " (approved)" : " (not approved)"}</strong>],
              ["Approved by", data.approvedBy.length ? data.approvedBy.join(", ") : "nobody yet"],
              ["Canonical hash (SHA-256)", <Mono key="h">{data.contractHash}</Mono>],
            ]} />
            {done ? <Notice tone="ok">{done}</Notice> : null}
            <ErrorBox error={actionError} title="Approval failed" />
            <div className="row" style={{ marginTop: ".6rem" }}>
              <button type="button" onClick={approve} disabled={data.approved}>Approve (reviewer)</button>
              {data.approved ? <span className="hint">Fully approved. Changing any field creates a new version that needs approval again.</span> : null}
            </div>
          </Section>
          <Section title="Controls" id="controls">
            <div className="table-wrap"><table className="grid">
              <thead><tr><th>Control</th><th>Type</th><th>Range / values</th><th>Nominal</th></tr></thead>
              <tbody>{controlSummaries(data.contract).map(c => <tr key={c.name}><td>{c.name}</td><td>{c.type}</td><td>{c.range}</td><td>{c.nominal}</td></tr>)}</tbody>
            </table></div>
          </Section>
          <Section title="Canonical JSON (the text that is hashed and approved)" id="canonical">
            <textarea readOnly rows={18} value={JSON.stringify(data.contract)} aria-label="Canonical contract JSON" />
            <p className="hint">Readable copy:</p>
            <textarea readOnly rows={18} value={JSON.stringify(data.contract, null, 2)} aria-label="Formatted contract JSON" />
          </Section>
        </>
      ) : null}
      {modal ? <PassphraseModal request={modal} onClose={() => setModal(null)} /> : null}
    </>
  );
}
