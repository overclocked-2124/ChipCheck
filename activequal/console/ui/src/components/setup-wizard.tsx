"use client";

import { useState } from "react";
import { emptyDraft, ProposalResponse, SetupDraft } from "@/lib/types";

const steps = ["Setup", "Controls", "Evidence", "Safety & budget", "Review"] as const;
type Key = keyof SetupDraft;

function Field({ label, name, value, onChange, hint, type = "text", required = true }: {
  label: string; name: Key; value: string; onChange: (name: Key, value: string) => void;
  hint?: string; type?: string; required?: boolean;
}) {
  return <label className="field"><span>{label}{required && <em> *</em>}</span>
    <input type={type} min={type === "number" ? "0" : undefined} step={type === "number" ? "any" : undefined}
      value={value} onChange={e => onChange(name, e.target.value)} placeholder={hint} />
    {hint && <small>{hint}</small>}
  </label>;
}

function Area({ label, name, value, onChange, hint, required = true }: {
  label: string; name: Key; value: string; onChange: (name: Key, value: string) => void;
  hint?: string; required?: boolean;
}) {
  return <label className="field wide"><span>{label}{required && <em> *</em>}</span>
    <textarea rows={3} value={value} onChange={e => onChange(name, e.target.value)} placeholder={hint} />
    {hint && <small>{hint}</small>}
  </label>;
}

const requiredByStep: Key[][] = [
  ["name", "dut", "firmware", "fixture"],
  ["railName", "railMin", "railMax", "railStep", "redLedOptions", "greenLedOptions", "workloads", "settleMs", "durationMs"],
  ["observations", "requirement"],
  ["maxVoltage", "maxCurrent", "maxTemperature", "safeState", "experimentBudget", "plannerSeed"],
  []
];

export function SetupWizard() {
  const [draft, setDraft] = useState<SetupDraft>(emptyDraft);
  const [step, setStep] = useState(0);
  const [error, setError] = useState("");
  const [proposal, setProposal] = useState<ProposalResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const change = (name: Key, value: string) => { setDraft(old => ({ ...old, [name]: value })); setError(""); setProposal(null); };
  const props = (name: Key) => ({ name, value: draft[name], onChange: change });
  const next = () => {
    if (requiredByStep[step].some(key => !draft[key].trim())) { setError("Complete the required fields to continue."); return; }
    if (step === 1 && Number(draft.railMin) >= Number(draft.railMax)) { setError("The minimum rail voltage must be below the maximum."); return; }
    if (step === 1 && (Number(draft.railStep) <= 0 || !draft.workloads.split(",").every(value => value.trim()))) { setError("Enter a positive rail step and comma-separated workloads."); return; }
    if (step === 1 && draft.sensorRailName.trim() && (!draft.sensorRailMin || !draft.sensorRailMax || !draft.sensorRailStep || Number(draft.sensorRailMin) >= Number(draft.sensorRailMax) || Number(draft.sensorRailStep) <= 0)) { setError("Complete the optional sensor rail with a valid range and step."); return; }
    if (step === 1 && [draft.redLedOptions, draft.greenLedOptions].some(value => value.split(",").some(option => !["on", "off"].includes(option.trim().toLowerCase())))) { setError("LED options must be on, off, or both separated by a comma."); return; }
    if (step === 3 && Number(draft.experimentBudget) < 1) { setError("Enter an experiment budget of at least 1."); return; }
    if (step === 3 && Number(draft.maxVoltage) < Math.max(Number(draft.railMax), draft.sensorRailName ? Number(draft.sensorRailMax) : 0)) { setError("The voltage ceiling must cover each selected rail range."); return; }
    setError(""); setStep(current => Math.min(current + 1, steps.length - 1));
  };
  const showProposals = async () => {
    setLoading(true); setError(""); setProposal(null);
    try {
      const response = await fetch("/api/proposals", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft) });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "Could not load proposed tests");
      setProposal({ source: body.source === "PROPOSAL_SOURCE_DECISION" ? "decision" : "backend", setupName: body.setupName, tests: body.tests, method: body.method, historyUsed: body.historyUsed });
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load proposed tests"); }
    finally { setLoading(false); }
  };

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">C<span>•</span></span><div><strong>CHIPCHECK</strong><small>Research console</small></div></div>
      <div className="side-caption">WORKSPACE</div>
      <div className="side-current"><span className="pulse" /> New test setup</div>
      <div className="side-caption flow-caption">SETUP FLOW</div>
      <nav aria-label="Setup steps" className="step-nav">{steps.map((name, i) => <button key={name} type="button" className={i === step ? "active" : ""} onClick={() => { if (i < step) { setStep(i); setError(""); setProposal(null); } }} disabled={i > step}><span>{String(i + 1).padStart(2, "0")}</span>{name}</button>)}</nav>
      <div className="side-foot">Configuration preview<br /><span>No hardware is controlled from this screen.</span></div>
    </aside>

    <main className="content">
      <header className="topbar"><span>CONFIGURE / NEW SETUP</span><span className="status"><i /> Draft</span></header>
      <div className="main-inner">
        <div className="eyebrow">SETUP BUILDER <span> / {String(step + 1).padStart(2, "0")}</span></div>
        <h1>{["Define your test setup", "Choose available controls", "Describe the evidence", "Set safety boundaries", "Review and preview"][step]}</h1>
        <p className="intro">{[
          "Start with the exact device, firmware, and fixture. Every proposed test will be tied to this setup.",
          "Tell ChipCheck which conditions the bench can vary. Separate multiple states or workloads with commas.",
          "Specify what the bench records and the public requirements used to judge behavior.",
          "Enter reviewed limits and the safe return state for this fixture. These values are configuration, not safety approval.",
          "Check the configuration before requesting candidates from the Decision Service. Proposals still need Backend and bench approval."
        ][step]}</p>
        <div className="progress" aria-label={`Step ${step + 1} of ${steps.length}`}><span style={{ width: `${((step + 1) / steps.length) * 100}%` }} /></div>

        <section className="card">
          <div className="card-heading"><div><span className="section-index">{String(step + 1).padStart(2, "0")}</span><h2>{steps[step]}</h2></div><span className="card-tag">{step === 4 ? "FINAL CHECK" : "CONFIGURATION"}</span></div>
          {step === 0 && <div className="grid">
            <Field label="Setup name" {...props("name")} hint="e.g. ESP32-S3 display sensor rig" />
            <Field label="DUT / board" {...props("dut")} hint="Board name and revision" />
            <Field label="Firmware version" {...props("firmware")} hint="Commit, build, or version" />
            <Field label="Fixture ID" {...props("fixture")} hint="Bench or fixture identifier" />
            <Area label="Wiring and peripherals" {...props("wiring")} required={false} hint="Describe connected peripherals and any setup changes" />
          </div>}
          {step === 1 && <div className="grid">
            <Field label="Variable rail name" {...props("railName")} hint="e.g. OLED rail" />
            <Field label="Minimum voltage (V)" {...props("railMin")} type="number" />
            <Field label="Maximum voltage (V)" {...props("railMax")} type="number" />
            <Field label="Adjustment step (V)" {...props("railStep")} type="number" />
            <Field label="Optional sensor rail name" {...props("sensorRailName")} required={false} hint="e.g. sensor rail" />
            <Field label="Sensor rail minimum (V)" {...props("sensorRailMin")} required={false} type="number" />
            <Field label="Sensor rail maximum (V)" {...props("sensorRailMax")} required={false} type="number" />
            <Field label="Sensor rail step (V)" {...props("sensorRailStep")} required={false} type="number" />
            <Field label="Red LED options" {...props("redLedOptions")} hint="on, off" />
            <Field label="Green LED options" {...props("greenLedOptions")} hint="on, off" />
            <Field label="Available workloads" {...props("workloads")} hint="e.g. oled_refresh, idle" />
            <Field label="Settling time (ms)" {...props("settleMs")} type="number" />
            <Field label="Workload duration (ms)" {...props("durationMs")} type="number" />
            <Area label="Forbidden combinations or sequence notes" {...props("forbiddenCombinations")} required={false} hint="Free-text restrictions cannot be checked for a preview yet; leave empty to request proposals" />
          </div>}
          {step === 2 && <div className="grid">
            <Area label="Required observations" {...props("observations")} hint="e.g. measured rail voltage, current, display latency, heartbeat, reset count" />
            <Area label="Public pass/fail requirement" {...props("requirement")} hint="e.g. OLED frame latency ≤ 120 ms with a usable reading" />
          </div>}
          {step === 3 && <div className="grid">
            <Field label="Maximum voltage (V)" {...props("maxVoltage")} type="number" />
            <Field label="Maximum current (A)" {...props("maxCurrent")} type="number" />
            <Field label="Maximum temperature (°C)" {...props("maxTemperature")} type="number" />
            <Field label="Experiment budget" {...props("experimentBudget")} type="number" />
            <label className="field"><span>Planner method *</span><select value={draft.plannerMethod} onChange={e => change("plannerMethod", e.target.value as SetupDraft["plannerMethod"])}><option value="tpe">Adaptive TPE</option><option value="random">Uniform random</option><option value="grid">Grid baseline</option></select></label>
            <Field label="Planner seed" {...props("plannerSeed")} type="number" />
            <Area label="Reviewed safe return state" {...props("safeState")} hint="Describe output and shutdown order for this fixture" />
          </div>}
          {step === 4 && <div className="review">
            <div className="review-row"><span>Setup</span><strong>{draft.name}</strong><small>{draft.dut} · firmware {draft.firmware} · {draft.fixture}</small></div>
            <div className="review-row"><span>Controls</span><strong>{draft.railName}: {draft.railMin}–{draft.railMax} V</strong><small>{draft.sensorRailName ? `${draft.sensorRailName}: ${draft.sensorRailMin}–${draft.sensorRailMax} V · ` : ""}{draft.workloads} · red: {draft.redLedOptions} · green: {draft.greenLedOptions}</small></div>
            <div className="review-row"><span>Evidence & requirement</span><strong>{draft.observations}</strong><small>{draft.requirement}</small></div>
            <div className="review-row"><span>Limits & budget</span><strong>{draft.experimentBudget} physical experiments</strong><small>{draft.maxVoltage} V / {draft.maxCurrent} A / {draft.maxTemperature} °C · {draft.safeState}</small></div>
            <div className="review-row"><span>Planner</span><strong>{draft.plannerMethod.toUpperCase()}</strong><small>Seed {draft.plannerSeed}; no measured history yet</small></div>
          </div>}
          {error && <p className="error" role="alert">{error}</p>}
          <div className="card-actions">{step > 0 && <button className="secondary" type="button" onClick={() => { setStep(step - 1); setProposal(null); setError(""); }}>Back</button>}
            {step < 4 ? <button className="primary" type="button" onClick={next}>Continue <span>→</span></button> : <button className="primary" type="button" disabled={loading} onClick={showProposals}>{loading ? "Loading…" : "Show proposed tests"} <span>→</span></button>}
          </div>
        </section>

        {proposal && <section className="proposal" aria-live="polite"><div className="proposal-title"><div><div className="eyebrow">PROPOSED TESTS</div><h2>Ready for review</h2></div><span className="mock-badge">DECISION · {proposal.method?.toUpperCase()}</span></div>
          <p>{proposal.historyUsed ? `${proposal.historyUsed} measured results informed this proposal. ` : "These are startup proposals; no measured results have been supplied yet. "}Candidates are unapproved and cannot execute hardware from this screen.</p>
          {proposal.tests.map((test, index) => <article className="test-card" key={test.id}><div className="test-number">{String(index + 1).padStart(2, "0")}</div><div><h3>{test.title}</h3><p>{test.reason || test.purpose}</p><div className="test-detail"><span>REQUESTED</span>{test.requested.join(" · ")}</div><div className="test-detail"><span>OBSERVE</span>{test.expectedObservations.join(" · ")}</div></div></article>)}
        </section>}
      </div>
    </main>
  </div>;
}
