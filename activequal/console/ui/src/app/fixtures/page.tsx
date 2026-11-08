"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, recentAdd, recentGet, useLoad, useNow } from "@/components/api";
import { CopyBox, Empty, ErrorBox, Loading, Notice, PageHeading, PassphraseModal, Section, type PassphraseRequest } from "@/components/ui";
import { ageSeconds, benchStatus, formatAge } from "@/lib/live";
import type { FixtureView } from "@/lib/types";
import type { ApiResult, UiError } from "@/lib/types";

type Registered = { fixtureId: string; token: string };

export default function FixturesPage() {
  const router = useRouter();
  const [fixtureId, setFixtureId] = useState("");
  const [revision, setRevision] = useState("A");
  const [capabilities, setCapabilities] = useState("supply.ch2, supply.ch3, dut, mcu");
  const [mcuSha, setMcuSha] = useState("");
  const [modal, setModal] = useState<PassphraseRequest | null>(null);
  const [error, setError] = useState<UiError | null>(null);
  const [token, setToken] = useState<Registered | null>(null);
  const [openId, setOpenId] = useState("");
  const [recents, setRecents] = useState<string[]>([]);
  useEffect(() => setRecents(recentGet("fixtures")), []);
  const fixtures = useLoad<{ fixtures: FixtureView[] }>("/v1/fixtures", 5000);
  const now = useNow(2000);

  function register() {
    setError(null); setToken(null);
    const caps = capabilities.split(",").map(c => c.trim()).filter(Boolean);
    setModal({
      title: "Register fixture",
      description: `Registering fixture ${fixtureId.trim()} issues its bench token. The token is shown once.`,
      confirmLabel: "Register",
      run: passphrase => api<Registered>("/v1/fixtures", { body: { fixtureId: fixtureId.trim(), revision: revision.trim(), capabilities: caps, ...(mcuSha.trim() ? { approvedMcuFirmwareSha256: mcuSha.trim() } : {}) }, passphrase }),
      onDone: (r: ApiResult<unknown>) => {
        if (r.ok) { const reg = r.data as Registered; setToken(reg); recentAdd("fixtures", reg.fixtureId); setRecents(recentGet("fixtures")); void fixtures.reload(); }
        else setError(r.error);
      },
    });
  }

  return (
    <>
      <PageHeading eyebrow="Configure" step="Fixtures" title="Fixtures and calibration"
        intro="A fixture is one physical bench and its wiring. Register it once, record a calibration against a trusted meter, and keep its health current." />
      <Section title="Fixtures" id="list" index={1} tag={`${fixtures.data?.fixtures.length ?? 0} registered`}>
        {fixtures.loading ? <Loading what="fixtures" /> : null}
        <ErrorBox error={fixtures.error} title="Could not list fixtures" />
        {fixtures.data && fixtures.data.fixtures.length === 0 ? <Empty>No fixtures yet. A reviewer registers one below.</Empty> : null}
        {fixtures.data?.fixtures.length ? (
          <div className="table-wrap"><table className="grid">
            <thead><tr><th>Fixture</th><th>Revision</th><th>Bench health</th><th>Reported</th><th>Calibration</th><th></th></tr></thead>
            <tbody>{fixtures.data.fixtures.map(f => {
              const bad = benchStatus(f).filter(l => l.ok !== true);
              const cal = f.calibration;
              const expired = cal ? Date.parse(cal.validUntil) <= now : true;
              return (
                <tr key={f.id}><td><code>{f.id}</code></td><td>{f.revision}</td>
                  <td>{f.health ? (bad.length ? <span className="badge badge-bad">{bad.map(l => l.label).join(", ")}</span> : <span className="badge badge-ok">healthy</span>) : <span className="badge badge-warn">not reported</span>}</td>
                  <td>{formatAge(ageSeconds(f.healthAt, now))}</td>
                  <td>{cal ? <span className={expired ? "bad-text" : undefined}>{expired ? "expired " : "valid until "}{cal.validUntil.slice(0, 10)}</span> : <span className="bad-text">none</span>}</td>
                  <td><Link href={`/fixtures/${encodeURIComponent(f.id)}`}>Open →</Link></td></tr>
              );
            })}</tbody>
          </table></div>
        ) : null}
      </Section>
      <Section title="Register a fixture" id="register" index={2} tag="Reviewer">
        <form onSubmit={e => { e.preventDefault(); register(); }}>
          <div className="fields">
            <label>Fixture id<input value={fixtureId} onChange={e => setFixtureId(e.target.value)} required placeholder="bench-A" /></label>
            <label>Revision<input value={revision} onChange={e => setRevision(e.target.value)} required /></label>
            <label className="wide">Capabilities (adapter targets, comma separated)<input value={capabilities} onChange={e => setCapabilities(e.target.value)} required /></label>
            <label className="wide">Approved test-controller firmware SHA-256 (optional)<input value={mcuSha} onChange={e => setMcuSha(e.target.value)} /></label>
          </div>
          <div className="card-actions">
            <span className="action-note">Asks for the reviewer passphrase. The bench token is shown once.</span>
            <button type="submit">Register fixture <span className="arrow" aria-hidden="true">→</span></button>
          </div>
        </form>
        <ErrorBox error={error} title="Registration failed" />
        {token ? (
          <Notice tone="warn">
            <strong>Bench token for {token.fixtureId}</strong>
            <p>Copy it into the bench process configuration now. <strong>It will not be shown again.</strong> The Console does not keep it; if it is lost, rotate it on the fixture page.</p>
            <CopyBox label="Bench token" value={token.token} />
            <p><button type="button" className="secondary" onClick={() => setToken(null)}>I have copied it; hide it</button>{" "}
              <Link href={`/fixtures/${encodeURIComponent(token.fixtureId)}`}>Open the fixture page</Link></p>
          </Notice>
        ) : null}
      </Section>
      <Section title="Open a fixture" id="open" index={3} tag="By id">
        <form className="row openform" onSubmit={e => { e.preventDefault(); if (openId.trim()) router.push(`/fixtures/${encodeURIComponent(openId.trim())}`); }}>
          <label style={{ flex: 1 }}>Fixture id<input value={openId} onChange={e => setOpenId(e.target.value)} required placeholder="bench-A" /></label>
          <button type="submit">Open <span className="arrow" aria-hidden="true">→</span></button>
        </form>
        {recents.length ? <p className="hint">Recently used on this browser: {recents.map(r => <span key={r}><Link href={`/fixtures/${encodeURIComponent(r)}`}>{r}</Link>{" "}</span>)}</p> : null}
      </Section>
      {modal ? <PassphraseModal request={modal} onClose={() => setModal(null)} /> : null}
    </>
  );
}
