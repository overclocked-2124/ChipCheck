"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, useLoad } from "@/components/api";
import { ErrorBox, KeyValues, Loading, Mono, Notice, PageHeading, PassphraseModal, Section, type PassphraseRequest } from "@/components/ui";
import { controlSummaries } from "@/lib/contractForm";
import { describeRequirement, describeRule, jsonDiff } from "@/lib/contractView";
import { path } from "@/lib/client";
import type { ApiResult, ContractDetail, JsonValue, UiError } from "@/lib/types";

const obj = (v: JsonValue | undefined): Record<string, JsonValue> => (v && typeof v === "object" && !Array.isArray(v) ? v : {});
const list = (v: JsonValue | undefined): JsonValue[] => (Array.isArray(v) ? v : []);

export default function ContractDetailPage() {
  const params = useParams<{ id: string; version: string }>();
  const id = decodeURIComponent(params.id), version = Number(params.version);
  const { data, error, loading, reload } = useLoad<ContractDetail>(path.contract(id, version));
  const previous = useLoad<ContractDetail>(version > 1 ? path.contract(id, version - 1) : null);
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
          <Section title="Rules and evidence" id="rules" index={3} tag="What is judged">
            <div className="grid2">
              <div className="stack"><h3>Forbidden combinations</h3>
                {list(data.contract.forbidden).length ? <ul className="steps">{list(data.contract.forbidden).map((r, i) => <li key={i}><span className="role">never</span><span className="num">{describeRule(r)}</span><span /></li>)}</ul> : <p className="empty">None.</p>}
                <h3>Requirements</h3>
                <ul className="steps">{list(data.contract.requirements).map((r, i) => <li key={i}><span className="role">{String(obj(r).id ?? i)}</span><span className="num">{describeRequirement(r)}</span><span /></li>)}</ul>
              </div>
              <div className="stack"><h3>Observations</h3>
                <div className="table-wrap"><table className="grid"><thead><tr><th>Observation</th><th>Unit</th><th>Uncertainty</th></tr></thead>
                  <tbody>{Object.entries(obj(data.contract.observations)).map(([k, o]) => <tr key={k}><td><code>{k}</code></td><td>{String(obj(o).unit ?? "")}</td><td className="num">{String(obj(o).uncertainty ?? "—")}</td></tr>)}</tbody></table></div>
                <h3>Safety limits</h3>
                <KeyValues rows={[
                  ...Object.entries(obj(obj(data.contract.safety).channels)).map(([ch, l]): [string, string] => [ch, `≤ ${obj(l).maxV} V, ≤ ${obj(l).maxA} A`]),
                  ["Temperature", `≤ ${obj(data.contract.safety).maxTempC ?? "?"} °C`], ["Episode time", `≤ ${obj(data.contract.safety).maxEpisodeS ?? "?"} s`],
                  ["Campaign", `budget ${obj(data.contract.campaign).budget ?? "?"}, plan ${obj(data.contract.campaign).plan ?? "?"}, seed ${obj(data.contract.campaign).seed ?? "?"}`],
                ]} />
              </div>
            </div>
          </Section>
          {version > 1 ? (
            <Section title={`Changes from version ${version - 1}`} id="diff" index={4} tag="Review these">
              {previous.data ? (() => {
                const diff = jsonDiff(previous.data.contract, data.contract);
                return diff.length ? <div className="table-wrap"><table className="grid"><thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead>
                  <tbody>{diff.map(d => <tr key={d.path}><td><code>{d.path}</code></td><td className="num">{d.before}</td><td className="num"><strong>{d.after}</strong></td></tr>)}</tbody></table></div>
                  : <p className="empty">No differences.</p>;
              })() : <ErrorBox error={previous.error} title="Could not load the previous version" />}
            </Section>
          ) : null}
          <Section title="Canonical JSON" id="canonical" index={version > 1 ? 5 : 4} tag="Hashed and approved">
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
