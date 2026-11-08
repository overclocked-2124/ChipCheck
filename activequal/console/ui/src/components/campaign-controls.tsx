"use client";

import { useState } from "react";
import { api, useNow } from "@/components/api";
import { ActionButton, PassphraseModal, Section, type PassphraseRequest } from "@/components/ui";
import type { CampaignAction } from "@/lib/actions";
import { buildChecklist } from "@/lib/arming";
import type { ApiResult, CampaignView, FixtureView, Reason } from "@/lib/types";

const MARK = { pass: "OK", fail: "NOT OK", unknown: "?" } as const;

/** HLD 03 §6.2: Arm is offered only inside the checklist, and only when every condition passes. */
export function ArmChecklist({ campaign, fixture, serverReasons, onResult }: {
  campaign: CampaignView; fixture: FixtureView | null; serverReasons: Reason[] | null;
  onResult: (action: CampaignAction, result: ApiResult<unknown>) => void;
}) {
  const now = useNow();
  const [wiring, setWiring] = useState(false);
  const list = buildChecklist({ campaign, contract: null, fixture, serverReasons, now, wiringConfirmed: wiring });
  return (
    <Section title="Arming checklist">
      <ul>{list.conditions.map(c => (
        <li key={c.id}>{MARK[c.status]} {c.label}{c.messages.length ? `: ${c.messages.join("; ")}` : ""}</li>
      ))}</ul>
      {list.other.length ? <ul>{list.other.map((r, i) => <li key={i}>NOT OK <code>{r.code}</code> {r.message}</li>)}</ul> : null}
      <label><input type="checkbox" checked={wiring} onChange={e => setWiring(e.target.checked)} />{" "}
        I checked that the fixture wiring matches the contract</label>
      {list.armable ? null : <p className="hint">Arm stays disabled until: {list.blockers.join(" ")}</p>}
      <div><ActionButton action="arm" campaignId={campaign.id} version={campaign.version} disabled={!list.armable} onResult={onResult} /></div>
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
    <Section title="Clear the lockout (reviewer)">
      <label><input type="checkbox" checked={inspected} onChange={e => setInspected(e.target.checked)} />{" "}
        I inspected the fixture in person and reset the interlock by hand</label>
      <label>What was found and fixed<input value={note} onChange={e => setNote(e.target.value)} /></label>
      <div><button type="button" disabled={!inspected || !note.trim()} onClick={open}>Clear lockout (asks for the reviewer passphrase)</button></div>
      {modal ? <PassphraseModal request={modal} onClose={() => setModal(null)} /> : null}
    </Section>
  );
}
