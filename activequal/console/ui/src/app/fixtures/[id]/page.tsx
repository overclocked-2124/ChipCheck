"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, useLoad } from "@/components/api";
import { BenchStatusPanel } from "@/components/fixture-panel";
import { CopyBox, ErrorBox, KeyValues, Loading, Mono, Notice, PageHeading, PassphraseModal, Section, type PassphraseRequest } from "@/components/ui";
import { path } from "@/lib/client";
import type { ApiResult, FixtureView, UiError } from "@/lib/types";

type Row = { channel: string; gain: string; offset: string; uncertainty: string };
const blankRow = (): Row => ({ channel: "", gain: "1", offset: "0", uncertainty: "" });

export default function FixturePage() {
  const params = useParams<{ id: string }>();
  const id = decodeURIComponent(params.id);
  const { data, error, loading, reload } = useLoad<FixtureView>(path.fixture(id), 2000);
  const [rows, setRows] = useState<Row[]>([{ channel: "supply.ch2", gain: "1", offset: "0", uncertainty: "0.01" }, blankRow()]);
  const [meter, setMeter] = useState("");
  const [operator, setOperator] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [calError, setCalError] = useState<UiError | null>(null);
  const [calOk, setCalOk] = useState<string | null>(null);
  const [modal, setModal] = useState<PassphraseRequest | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [rotateError, setRotateError] = useState<UiError | null>(null);

  const setRow = (i: number, patch: Partial<Row>) => setRows(rs => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  async function saveCalibration() {
    setCalError(null); setCalOk(null);
    const channels: Record<string, { gain: number; offset: number; uncertainty: number }> = {};
    for (const r of rows.filter(r => r.channel.trim())) {
      const gain = Number(r.gain), offset = Number(r.offset), uncertainty = Number(r.uncertainty);
      if (![gain, offset, uncertainty].every(Number.isFinite) || r.uncertainty.trim() === "") {
        setCalError({ code: "INVALID_ARGUMENT", status: 400, message: `Channel ${r.channel}: gain, offset and uncertainty must all be numbers.` }); return;
      }
      channels[r.channel.trim()] = { gain, offset, uncertainty };
    }
    const until = new Date(validUntil);
    if (!validUntil || Number.isNaN(until.getTime())) { setCalError({ code: "INVALID_ARGUMENT", status: 400, message: "Choose when this calibration stops being valid." }); return; }
    const res = await api<{ calibrationId: string }>(path.calibrations(id), { body: { channels, meterIdentity: meter, operator, validUntil: until.toISOString() } });
    if (res.ok) { setCalOk(`Calibration ${res.data.calibrationId} recorded.`); void reload(); } else setCalError(res.error);
  }

  function rotate() {
    setRotateError(null); setToken(null);
    setModal({
      title: "Rotate bench token", description: `The old bench token for ${id} stops working immediately. Update the bench process after copying the new one.`, confirmLabel: "Rotate",
      run: passphrase => api<{ fixtureId: string; token: string }>(path.rotate(id), { method: "POST", body: {}, passphrase }),
      onDone: (r: ApiResult<unknown>) => { if (r.ok) setToken((r.data as { token: string }).token); else setRotateError(r.error); },
    });
  }

  const cal = data?.calibration ?? null;
  return (
    <>
      <PageHeading eyebrow="Fixtures" step="Bench" title={<>Fixture <code>{id}</code></>}
        intro={<>Health, calibration and the bench token for this fixture. <Link href="/fixtures">All fixtures</Link></>} />
      {loading ? <Loading what="fixture" /> : null}
      <ErrorBox error={error} title="Could not load this fixture" />
      {data ? (
        <div className="grid2">
          <Section title="Health" id="health" index={1} tag="Live"><BenchStatusPanel fixture={data} /></Section>
          <Section title="Fixture" id="info" index={2} tag={`Revision ${data.revision}`}>
            <KeyValues rows={[["Revision", data.revision], ["Capabilities", data.capabilities.join(", ")], ["Approved test-controller firmware", <Mono key="a">{data.approvedMcuFirmwareSha256 ?? "none set"}</Mono>]]} />
          </Section>
        </div>
      ) : null}
      {data ? (
        <Section title="Current calibration" id="current" index={3} tag={cal ? "Recorded" : "Missing"}>
          {cal ? (
            <>
              <KeyValues rows={[["Meter", cal.meter], ["Operator", cal.operator],
                ["Age", `${Math.max(0, Math.floor((Date.now() - Date.parse(cal.createdAt)) / 86400000))} day(s) (recorded ${cal.createdAt.slice(0, 16).replace("T", " ")})`],
                ["Valid until", `${cal.validUntil.slice(0, 16).replace("T", " ")}${Date.parse(cal.validUntil) <= Date.now() ? "  (EXPIRED: arming is refused)" : ""}`]]} />
              <div className="table-wrap" style={{ marginTop: 16 }}><table className="grid"><thead><tr><th>Channel</th><th>Gain</th><th>Offset</th><th>Uncertainty (U, k=2)</th></tr></thead>
                <tbody>{Object.entries(cal.channels).map(([k, v]) => <tr key={k}><td><code>{k}</code></td><td className="num">{v.gain}</td><td className="num">{v.offset}</td><td className="num">{v.uncertainty}</td></tr>)}</tbody></table></div>
            </>
          ) : <p className="bad-text">No calibration recorded. A campaign cannot be armed without one.</p>}
        </Section>
      ) : null}
      <Section title="Record a calibration" id="calibrate" index={4} tag="Trusted meter">
        <div className="note" style={{ marginBottom: 18 }}><strong>Running a calibration.</strong> Measure each rail with a trusted meter at its minimum, midpoint and maximum
          test values (PRD §11.5), save the readings as JSON, then fit and record them with
          <pre className="report" style={{ margin: "10px 0" }}>python -m activequal.tools.calibrate points.json --operator NAME --fixture-id {id} --post</pre>
          The tool refuses fewer than three points or a gain more than 5% from 1. You can also type a fitted result below.</div>
        <form className="stack" onSubmit={e => { e.preventDefault(); void saveCalibration(); }}>
          <div className="table-wrap"><table className="grid"><thead><tr><th>Channel</th><th>Gain</th><th>Offset</th><th>Uncertainty U</th></tr></thead>
            <tbody>{rows.map((r, i) => (
              <tr key={i}>
                {(["channel", "gain", "offset", "uncertainty"] as const).map(k => (
                  <td key={k}><input aria-label={`${k} ${i + 1}`} value={r[k]} onChange={e => setRow(i, { [k]: e.target.value })} /></td>
                ))}
              </tr>))}</tbody></table></div>
          <div><button type="button" className="secondary" onClick={() => setRows(rs => [...rs, blankRow()])}>+ Add channel</button></div>
          <div className="fields">
            <label>Meter identity<input value={meter} onChange={e => setMeter(e.target.value)} required /></label>
            <label>Operator<input value={operator} onChange={e => setOperator(e.target.value)} required /></label>
            <label>Valid until<input type="datetime-local" value={validUntil} onChange={e => setValidUntil(e.target.value)} required /></label>
          </div>
          <ErrorBox error={calError} title="Calibration not recorded" />
          <div className="card-actions" style={{ marginTop: 6 }}>
            <span className="action-note">Fit it with the calibration tool, then record the result here.</span>
            <button type="submit">Record calibration <span className="arrow" aria-hidden="true">→</span></button>
          </div>
          {calOk ? <Notice tone="ok">{calOk}</Notice> : null}
        </form>
      </Section>
      <Section title="Bench token" id="token" index={5} tag="Reviewer">
        <p className="hint">Use only if the bench token is lost or exposed. The new token is shown once.</p>
        <div className="row"><button type="button" className="secondary" onClick={rotate}>Rotate bench token</button></div>
        <ErrorBox error={rotateError} title="Rotation failed" />
        {token ? <Notice tone="warn"><strong>New bench token. It will not be shown again.</strong><CopyBox label="Bench token" value={token} /><button type="button" className="secondary" onClick={() => setToken(null)}>I have copied it; hide it</button></Notice> : null}
      </Section>
      {modal ? <PassphraseModal request={modal} onClose={() => setModal(null)} /> : null}
    </>
  );
}
