"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, useLoad } from "@/components/api";
import { ErrorBox, KeyValues, Loading, Mono, Notice, PageHeading, PassphraseModal, Section, type PassphraseRequest } from "@/components/ui";
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
      <PageHeading eyebrow="Contracts" step={`Version ${version}`} title={<>Contract <code>{id.slice(0, 12)}</code></>}
        intro={<>Full id <Mono>{id}</Mono>. <Link href="/contracts">Back to the contract editor</Link></>} />
      {loading ? <Loading what="contract" /> : null}
      <ErrorBox error={error} title="Could not load this contract version" />
      {data ? (
        <>
          <Section title="Approval" id="approval" index={1} tag={data.approved ? "Approved" : "Awaiting review"}>
            <KeyValues rows={[
              ["Approvals", <strong key="a">{data.approvedBy.length} of {data.approvalsRequired} approvals{data.approved ? " (approved)" : " (not approved)"}</strong>],
              ["Approved by", data.approvedBy.length ? data.approvedBy.join(", ") : "nobody yet"],
              ["Canonical hash (SHA-256)", <Mono key="h">{data.contractHash}</Mono>],
            ]} />
            {done ? <Notice tone="ok">{done}</Notice> : null}
            <ErrorBox error={actionError} title="Approval failed" />
            <div className="card-actions">
              {data.approved ? <span className="action-note">Fully approved. Changing any field creates a new version that needs approval again.</span>
                : <span className="action-note">Asks for the reviewer passphrase.</span>}
              <button type="button" onClick={approve} disabled={data.approved}>Approve <span className="arrow" aria-hidden="true">→</span></button>
            </div>
          </Section>
          <Section title="Controls" id="controls" index={2} tag="Search domain">
            <div className="table-wrap"><table className="grid">
              <thead><tr><th>Control</th><th>Type</th><th>Range / values</th><th>Nominal</th></tr></thead>
              <tbody>{controlSummaries(data.contract).map(c => <tr key={c.name}><td><code>{c.name}</code></td><td>{c.type}</td><td className="num">{c.range}</td><td className="num">{c.nominal}</td></tr>)}</tbody>
            </table></div>
          </Section>
          <Section title="Canonical JSON" id="canonical" index={3} tag="Hashed and approved">
            <p className="hint">This exact text is hashed and approved.</p>
            <textarea readOnly rows={8} value={JSON.stringify(data.contract)} aria-label="Canonical contract JSON" />
            <p className="hint" style={{ marginTop: 14 }}>Readable copy:</p>
            <textarea readOnly rows={18} value={JSON.stringify(data.contract, null, 2)} aria-label="Formatted contract JSON" />
          </Section>
        </>
      ) : null}
      {modal ? <PassphraseModal request={modal} onClose={() => setModal(null)} /> : null}
    </>
  );
}
