"use client";

import { useState } from "react";
import { api, useNow } from "@/components/api";
import { ActionButton, KeyValues, Mono, PassphraseModal, Section, type PassphraseRequest } from "@/components/ui";
import type { CampaignAction } from "@/lib/actions";
import { buildChecklist } from "@/lib/arming";
import type { ApiResult, CampaignContract, CampaignView, FixtureView, JsonValue, Reason } from "@/lib/types";

const minutes = (s: number | null) => (s === null ? "unknown" : s < 120 ? `${s.toFixed(0)} s` : `${(s / 60).toFixed(0)} min`);
const short = (h: unknown) => (typeof h === "string" && h ? `${h.slice(0, 12)}…` : "not stated");
const obj = (v: JsonValue | undefined): Record<string, JsonValue> => (v && typeof v === "object" && !Array.isArray(v) ? v : {});

/** PRD §15.2 step 2: what the operator confirms before Arm (limits, hashes, calibration, expected runtime). */
function ArmIdentity({ info, fixture }: { info: CampaignContract | null; fixture: FixtureView | null }) {
  if (!info) return <p className="hint">Loading the contract identity…</p>;
  const setup = obj(info.contract.setup), safety = obj(info.contract.safety), channels = obj(safety.channels);
  const limits = Object.entries(channels).map(([ch, l]) => `${ch} ≤ ${obj(l).maxV} V, ${obj(l).maxA} A`).join("; ");
  return (
    <KeyValues rows={[
      ["Contract", <span key="c">{info.contractId.slice(0, 12)} v{info.version} · <Mono>{short(info.contractHash)}</Mono></span>],
      ["Approved by", info.approvals.map(a => a.reviewer).join(", ") || "nobody"],
      ["DUT firmware (contract / bench)", <span key="d"><Mono>{short(setup.firmwareSha256)}</Mono> / <Mono>{short(fixture?.health?.dutFirmwareSha256)}</Mono></span>],
      ["Test-controller firmware (approved / bench)", <span key="m"><Mono>{short(fixture?.approvedMcuFirmwareSha256)}</Mono> / <Mono>{short(fixture?.health?.mcuFirmwareSha256)}</Mono></span>],
      ["Calibration", fixture?.calibration ? `${fixture.calibration.meter}, valid until ${fixture.calibration.validUntil.slice(0, 10)}` : "none"],
      ["Hard limits", `${limits || "none"}; ${safety.maxTempC ?? "?"} °C; ${safety.maxEpisodeS ?? "?"} s per episode`],
      ["Expected maximum runtime", `${minutes(info.expectedMaxRuntimeS)} (every remaining episode at its ${info.maxEpisodeS ?? "?"} s cap)`],
    ]} />
  );
}

const MARK = { pass: "✓", fail: "✕", unknown: "?" } as const;
const SAY = { pass: "OK", fail: "Not OK", unknown: "Unknown" } as const;

/** HLD 03 §6.2: Arm is offered only inside the checklist, and only when every condition passes. */
export function ArmChecklist({ campaign, fixture, info, serverReasons, onResult }: {
  campaign: CampaignView; fixture: FixtureView | null; info: CampaignContract | null; serverReasons: Reason[] | null;
  onResult: (action: CampaignAction, result: ApiResult<unknown>) => void;
}) {
  const now = useNow();
  const [wiring, setWiring] = useState(false);
  const contract = info ? { approved: info.approvals.length >= info.approvalsRequired, approvedBy: info.approvals.map(a => a.reviewer), approvalsRequired: info.approvalsRequired } : null;
  const list = buildChecklist({ campaign, contract, fixture, serverReasons, now, wiringConfirmed: wiring });
  return (
    <Section title="Arming checklist" index={2} tag={list.armable ? "Ready to arm" : "Arm blocked"}>
      <ArmIdentity info={info} fixture={fixture} />
      <ul className="checklist" style={{ marginTop: 18 }}>{list.conditions.map(c => (
        <li key={c.id} className={c.status}>
          <span className="mark" aria-hidden="true">{MARK[c.status]}</span>
          <div><strong><span className="sr-only">{SAY[c.status]}: </span>{c.label}</strong>{c.messages.length ? <small>{c.messages.join("; ")}</small> : null}</div>
        </li>
      ))}
      {list.other.map((r, i) => (
        <li key={`o${i}`} className="fail"><span className="mark" aria-hidden="true">✕</span>
          <div><strong><span className="sr-only">Not OK: </span><code>{r.code}</code></strong><small>{r.message}</small></div></li>
      ))}</ul>
      <div className="card-actions">
        <label className="check action-note"><input type="checkbox" checked={wiring} onChange={e => setWiring(e.target.checked)} />
          I checked that the fixture wiring matches the contract</label>
        <ActionButton action="arm" campaignId={campaign.id} version={campaign.version} disabled={!list.armable} onResult={onResult} />
      </div>
      {list.armable ? null : <p className="hint">Arm stays disabled until: {list.blockers.join(" ")}</p>}
    </Section>
  );
}

/** HLD 03 §13 step 7: a reviewer confirms the physical inspection, then the campaign returns to DRAFT. */
export function ClearLockout({ campaign, onDone }: { campaign: CampaignView; onDone: (result: ApiResult<unknown>) => void }) {
  const [inspected, setInspected] = useState(false);
  const [note, setNote] = useState("");
  const [modal, setModal] = useState<PassphraseRequest | null>(null);
  function open() {
    setModal({
      title: "Clear lockout",
      description: "Only after the fixture has been inspected in person and the interlock reset by hand. The campaign returns to DRAFT and must be validated and armed again.",
      confirmLabel: "Clear lockout",
      run: passphrase => api(`/v1/campaigns/${encodeURIComponent(campaign.id)}:clear-lockout`, {
        method: "POST", passphrase, body: { campaignVersion: campaign.version, physicalInspection: true, note: note.trim() } }),
      onDone,
    });
  }
  return (
    <Section title="Clear the lockout" index={2} tag="Reviewer">
      <div className="stack">
        <label className="check"><input type="checkbox" checked={inspected} onChange={e => setInspected(e.target.checked)} />
          I inspected the fixture in person and reset the interlock by hand</label>
        <label>What was found and fixed<input value={note} onChange={e => setNote(e.target.value)} /></label>
      </div>
      <div className="card-actions">
        <span className="action-note">Asks for the reviewer passphrase. The campaign returns to DRAFT.</span>
        <button type="button" disabled={!inspected || !note.trim()} onClick={open}>Clear lockout <span className="arrow" aria-hidden="true">→</span></button>
      </div>
      {modal ? <PassphraseModal request={modal} onClose={() => setModal(null)} /> : null}
    </Section>
  );
}
