"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, useLoad } from "@/components/api";
import { BenchStatusPanel } from "@/components/fixture-panel";
import { CopyBox, ErrorBox, KeyValues, Loading, Mono, Notice, PassphraseModal, Section, type PassphraseRequest } from "@/components/ui";
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
      <h1>Fixture <Mono>{id}</Mono></h1>
      <p><Link href="/fixtures">All fixtures</Link></p>
      {loading ? <Loading what="fixture" /> : null}
      <ErrorBox error={error} title="Could not load this fixture" />
      {data ? (
        <div className="grid2">
          <Section title="Health" id="health"><BenchStatusPanel fixture={data} /></Section>
          <Section title="Fixture" id="info">
            <KeyValues rows={[["Revision", data.revision], ["Capabilities", data.capabilities.join(", ")], ["Approved test-controller firmware", <Mono key="a">{data.approvedMcuFirmwareSha256 ?? "none set"}</Mono>]]} />
          </Section>
        </div>
      ) : null}
      {data ? (
        <Section title="Current calibration" id="current">
          {cal ? (
            <>
              <KeyValues rows={[["Meter", cal.meter], ["Operator", cal.operator], ["Recorded", cal.createdAt], ["Valid until", `${cal.validUntil}${Date.parse(cal.validUntil) <= Date.now() ? "  (EXPIRED)" : ""}`]]} />
              <table className="grid"><thead><tr><th>Channel</th><th>Gain</th><th>Offset</th><th>Uncertainty (U, k=2)</th></tr></thead>
                <tbody>{Object.entries(cal.channels).map(([k, v]) => <tr key={k}><td>{k}</td><td>{v.gain}</td><td>{v.offset}</td><td>{v.uncertainty}</td></tr>)}</tbody></table>
            </>
          ) : <p className="bad-text">No calibration recorded. A campaign cannot be armed without one.</p>}
        </Section>
      ) : null}
      <Section title="Record a calibration" id="calibrate">
        <form className="stack" onSubmit={e => { e.preventDefault(); void saveCalibration(); }}>
          <table className="grid"><thead><tr><th>Channel</th><th>Gain</th><th>Offset</th><th>Uncertainty U</th></tr></thead>
            <tbody>{rows.map((r, i) => (
              <tr key={i}>
                {(["channel", "gain", "offset", "uncertainty"] as const).map(k => (
                  <td key={k}><input aria-label={`${k} ${i + 1}`} value={r[k]} onChange={e => setRow(i, { [k]: e.target.value })} /></td>
                ))}
              </tr>))}</tbody></table>
          <div><button type="button" className="secondary" onClick={() => setRows(rs => [...rs, blankRow()])}>Add channel</button></div>
          <div className="fields">
            <label>Meter identity<input value={meter} onChange={e => setMeter(e.target.value)} required /></label>
            <label>Operator<input value={operator} onChange={e => setOperator(e.target.value)} required /></label>
            <label>Valid until<input type="datetime-local" value={validUntil} onChange={e => setValidUntil(e.target.value)} required /></label>
          </div>
          <div><button type="submit">Record calibration</button></div>
          <ErrorBox error={calError} title="Calibration not recorded" />
          {calOk ? <Notice tone="ok">{calOk}</Notice> : null}
        </form>
      </Section>
      <Section title="Bench token (reviewer)" id="token">
        <p className="hint">Use only if the bench token is lost or exposed. The new token is shown once.</p>
        <button type="button" className="secondary" onClick={rotate}>Rotate bench token</button>
        <ErrorBox error={rotateError} title="Rotation failed" />
        {token ? <Notice tone="warn"><strong>New bench token. It will not be shown again.</strong><CopyBox label="Bench token" value={token} /><button type="button" className="secondary" onClick={() => setToken(null)}>I have copied it; hide it</button></Notice> : null}
      </Section>
      {modal ? <PassphraseModal request={modal} onClose={() => setModal(null)} /> : null}
    </>
  );
}
