"use client";

import { useEffect, useId, useRef, useState } from "react";
import { oledExample } from "@/lib/oled-example";
import { ProposalPreview } from "./proposal-preview";
import { SetupContext } from "./setup-context";
import { emptyDraft, ProposalResponse, SetupDraft } from "@/lib/types";

const steps = ["Device & fixture", "Controls", "Evidence", "Limits & planner", "Review"] as const;
const storageKey = "chipcheck.setup-draft.v1";
type Key = keyof SetupDraft;

function Field({ label, name, value, onChange, hint, type = "text", required = true }: {
  label: string; name: Key; value: string; onChange: (name: Key, value: string) => void;
  hint?: string; type?: string; required?: boolean;
}) {
  const id = useId();
  return <label className="field" htmlFor={id}><span>{label}{required && <em aria-hidden="true"> *</em>}</span>
    <input id={id} aria-required={required} aria-describedby={hint ? `${id}-hint` : undefined} type={type} min={type === "number" ? "0" : undefined} step={type === "number" ? "any" : undefined}
      value={value} onChange={e => onChange(name, e.target.value)} placeholder={hint} />
    {hint && <small id={`${id}-hint`}>{hint}</small>}
  </label>;
}

function Area({ label, name, value, onChange, hint, required = true }: {
  label: string; name: Key; value: string; onChange: (name: Key, value: string) => void;
  hint?: string; required?: boolean;
}) {
  const id = useId();
  return <label className="field wide" htmlFor={id}><span>{label}{required && <em aria-hidden="true"> *</em>}</span>
    <textarea id={id} aria-required={required} aria-describedby={hint ? `${id}-hint` : undefined} rows={3} value={value} onChange={e => onChange(name, e.target.value)} placeholder={hint} />
    {hint && <small id={`${id}-hint`}>{hint}</small>}
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
  const [restored, setRestored] = useState(false);
  const [exampleLoaded, setExampleLoaded] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey) || "null");
      if (saved && typeof saved.draft === "object" && saved.draft) {
        const valid = Object.keys(emptyDraft).every(key => typeof saved.draft[key] === "string") && ["tpe", "random", "grid"].includes(saved.draft.plannerMethod);
        if (valid) {
          setDraft(saved.draft);
          setStep(Number.isInteger(saved.step) && saved.step >= 0 && saved.step <= 4 ? saved.step : 0);
          setExampleLoaded(saved.exampleLoaded === true);
        }
      }
    } catch { /* Storage can be unavailable; the form still works. */ }
    setRestored(true);
  }, []);
  useEffect(() => {
    if (!restored) return;
    try { sessionStorage.setItem(storageKey, JSON.stringify({ draft, step, exampleLoaded })); }
    catch { /* Draft persistence is optional. */ }
  }, [draft, step, exampleLoaded, restored]);
  const focusHeading = () => requestAnimationFrame(() => headingRef.current?.focus());
  const goBack = (target: number) => { setStep(target); setProposal(null); setError(""); focusHeading(); };
  const loadExample = () => { setDraft({ ...oledExample }); setExampleLoaded(true); setProposal(null); setError(""); };
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
    setError(""); setStep(current => Math.min(current + 1, steps.length - 1)); focusHeading();
  };
  const showProposals = async () => {
    setLoading(true); setError(""); setProposal(null);
    try {
      const response = await fetch("/api/proposals", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(draft) });
      const body = await response.json();
      if (!response.ok) {
        const message = String(body.error || "Could not load proposed tests");
        if (message.includes("grid baseline exceeds")) throw new Error("Grid supports up to 10,000 combinations. Narrow the rail ranges, increase the steps, or choose TPE or Random.");
        if (response.status === 503) throw new Error("The planner could not be reached. Try again once the local services are running.");
        throw new Error(message.replace(/^Could not load proposed tests:\s*\d+ [A-Z_]+:\s*/, ""));
      }
      setProposal({ source: body.source === "PROPOSAL_SOURCE_DECISION" ? "decision" : "backend", setupName: body.setupName, tests: body.tests, method: body.method, historyUsed: body.historyUsed });
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load proposed tests"); }
    finally { setLoading(false); }
  };

  return <div className="shell">
    <a className="skip-link" href="#setup-content">Skip to setup</a>
    <header className="app-header">
      <a className="brand" href="/" aria-label="ChipCheck console home"><span className="brand-mark" aria-hidden="true"><span /></span><strong>ChipCheck</strong></a>
      <span className="header-divider" aria-hidden="true" /><span className="header-caption">Research console</span>
      <div className="header-meta"><span className="local-label"><i aria-hidden="true" />Local preview</span><span className="draft-label">Draft</span></div>
    </header>
    <div className="workspace">
      <aside className="workflow-nav">
        <p className="overline">Configuration</p><h2>New test setup</h2>
        <nav aria-label="Setup steps"><ol className="step-nav">{steps.map((name, i) => <li key={name}>
          <button type="button" className={i === step ? "active" : i < step ? "complete" : ""} aria-current={i === step ? "step" : undefined} onClick={() => { if (i < step) goBack(i); }} disabled={loading || i > step}>
            <span className="step-index">{i < step ? <svg viewBox="0 0 16 16" width="12" height="12" role="img" aria-label="Completed"><path d="m3 8 3 3 7-7" fill="none" stroke="currentColor" strokeWidth="1.4" /></svg> : String(i + 1).padStart(2, "0")}</span><span>{name}</span>
          </button>
        </li>)}</ol></nav>
        <p className="nav-foot">Define the setup.<br />Review the conditions.<br />Keep the evidence.</p>
      </aside>
      <main id="setup-content" className="content" tabIndex={-1}>
        <div className="page-heading"><p className="overline">Test setup <span className="step-count">{String(step + 1).padStart(2, "0")} / 05</span></p>
          <h1 ref={headingRef} tabIndex={-1}>{["Define the bench.", "Set the control domain.", "Make behavior measurable.", "Bound the experiment.", "Review your setup."][step]}</h1>
          <p className="intro">{[
            "Identify the device, firmware and wiring that each experiment will belong to.",
            "Specify what this bench can change. Keep the device’s fixed supply separate from the programmable rails.",
            "Record what happened, then judge it against a public requirement.",
            "Declare the limits and budget for this setup. Select how the planner proposes conditions.",
            "Check the configuration, then request conditions from the Decision Service."
          ][step]}</p>
        </div>
        <section className="form-section" aria-labelledby="form-title">
          <div className="form-heading"><h2 id="form-title">{steps[step]}</h2><span>Required fields <span aria-hidden="true">*</span></span></div>
          {step === 0 && <>
            <div className="example-strip"><div><strong>Start with the OLED demo</strong><p>Load the ESP32-S3 example from your project docs.</p></div><button className="text-button" type="button" onClick={loadExample}>Use OLED example <span aria-hidden="true">↗</span></button></div>
            <div className="field-grid">
              <Field label="Setup name" {...props("name")} hint="A name you will recognize in the results" />
              <Field label="DUT / board" {...props("dut")} hint="Board name and revision" />
              <Field label="Firmware version" {...props("firmware")} hint="Commit, build or firmware hash" />
              <Field label="Fixture ID" {...props("fixture")} hint="The bench and wiring used for this setup" />
              <Area label="Wiring and peripherals" {...props("wiring")} required={false} hint="Connected peripherals, supply topology and isolation" />
            </div>
          </>}
          {step === 1 && <>
            <fieldset className="field-group"><legend>Primary rail</legend><div className="field-grid rail-grid">
              <Field label="Variable rail name" {...props("railName")} hint="e.g. OLED rail" />
              <Field label="Minimum voltage (V)" {...props("railMin")} type="number" />
              <Field label="Maximum voltage (V)" {...props("railMax")} type="number" />
              <Field label="Adjustment step (V)" {...props("railStep")} type="number" />
            </div></fieldset>
            <fieldset className="field-group"><legend>Sensor rail <span>Optional</span></legend><div className="field-grid rail-grid">
              <Field label="Optional sensor rail name" {...props("sensorRailName")} required={false} hint="Leave empty for a single variable rail" />
              <Field label="Sensor rail minimum (V)" {...props("sensorRailMin")} required={false} type="number" />
              <Field label="Sensor rail maximum (V)" {...props("sensorRailMax")} required={false} type="number" />
              <Field label="Sensor rail step (V)" {...props("sensorRailStep")} required={false} type="number" />
            </div></fieldset>
            <fieldset className="field-group"><legend>States & timing</legend><div className="field-grid">
              <Field label="Red LED options" {...props("redLedOptions")} hint="on, off, or both separated by a comma" />
              <Field label="Green LED options" {...props("greenLedOptions")} hint="on, off, or both separated by a comma" />
              <div className="wide"><Field label="Available workloads" {...props("workloads")} hint="Comma-separated: oled_refresh, idle" /></div>
              <Field label="Settling time (ms)" {...props("settleMs")} type="number" />
              <Field label="Workload duration (ms)" {...props("durationMs")} type="number" />
              <Area label="Forbidden combinations or sequence notes" {...props("forbiddenCombinations")} required={false} hint="Free-text restrictions are not supported by the preview. Leave empty to request conditions." />
            </div></fieldset>
          </>}
          {step === 2 && <div className="field-grid">
            <Area label="Required observations" {...props("observations")} hint="Measured rails, current, display latency, heartbeat and resets" />
            <Area label="Public pass/fail requirement" {...props("requirement")} hint="e.g. OLED frame latency ≤ 120 ms with usable evidence" />
          </div>}
          {step === 3 && <>
            <fieldset className="field-group"><legend>Operating limits</legend><div className="field-grid limits-grid">
              <Field label="Maximum voltage (V)" {...props("maxVoltage")} type="number" />
              <Field label="Maximum current (A)" {...props("maxCurrent")} type="number" />
              <Field label="Maximum temperature (°C)" {...props("maxTemperature")} type="number" />
              <Area label="Reviewed safe return state" {...props("safeState")} hint="Output isolation, shutdown order and verification for this fixture" />
            </div></fieldset>
            <fieldset className="field-group"><legend>Campaign & selection</legend><div className="field-grid">
              <Field label="Experiment budget" {...props("experimentBudget")} type="number" />
              <Field label="Planner seed" {...props("plannerSeed")} type="number" />
              <label className="field wide"><span>Planner method <em aria-hidden="true">*</em></span><select aria-required="true" value={draft.plannerMethod} onChange={e => change("plannerMethod", e.target.value as SetupDraft["plannerMethod"])}><option value="tpe">Adaptive TPE</option><option value="random">Uniform random</option><option value="grid">Grid baseline</option></select><small>TPE starts with broad samples until measured feedback is available.</small></label>
            </div></fieldset>
          </>}
          {step === 4 && <dl className="review-list">
            <div><dt>Device & fixture</dt><dd><strong>{draft.name}</strong><span>{draft.dut}</span><span>Firmware: {draft.firmware}</span><span>Fixture: {draft.fixture}</span>{draft.wiring && <p>{draft.wiring}</p>}</dd></div>
            <div><dt>Control domain</dt><dd><strong className="mono">{draft.railName} · {draft.railMin}–{draft.railMax} V</strong><span>Step {draft.railStep} V{draft.sensorRailName ? ` · ${draft.sensorRailName}: ${draft.sensorRailMin}–${draft.sensorRailMax} V, step ${draft.sensorRailStep} V` : ""}</span><span>Red: {draft.redLedOptions} · Green: {draft.greenLedOptions}</span><span>Workload: {draft.workloads}</span><span>Settle {draft.settleMs} ms · Duration {draft.durationMs} ms</span>{draft.forbiddenCombinations && <p>{draft.forbiddenCombinations}</p>}</dd></div>
            <div><dt>Observations</dt><dd><p>{draft.observations}</p></dd></div>
            <div><dt>Requirements</dt><dd><p>{draft.requirement}</p></dd></div>
            <div><dt>Limits & return</dt><dd><strong className="mono">{draft.maxVoltage} V · {draft.maxCurrent} A · {draft.maxTemperature} °C</strong><p>{draft.safeState}</p></dd></div>
            <div><dt>Campaign</dt><dd><strong>{draft.experimentBudget} experiments · {draft.plannerMethod.toUpperCase()}</strong><span className="mono">Seed {draft.plannerSeed}</span><span>No measured history supplied</span></dd></div>
          </dl>}
          {exampleLoaded && <p className="example-note"><strong>Documentation example.</strong> PRD §9.2 and HLD 04 §11. Hardware identities and limits still need bench confirmation. Settling and duration values are preview placeholders.</p>}
          {error && <p className="error" role="alert">{error}</p>}
          <div className="form-actions"><span className="action-note">{step === 4 ? "Proposals do not operate hardware." : `Next: ${steps[step + 1]}`}</span><div>
            {step > 0 && <button className="secondary" type="button" disabled={loading} onClick={() => goBack(step - 1)}>Back</button>}
            {step < 4 ? <button className="primary" type="button" onClick={next}>Continue <span aria-hidden="true">→</span></button> : <button className="primary" type="button" disabled={loading} onClick={showProposals}>{loading ? "Choosing conditions…" : proposal ? "Refresh proposals" : "Show proposed tests"}<span aria-hidden="true">→</span></button>}
          </div></div>
        </section>
        <ProposalPreview proposal={proposal} draft={draft} loading={loading} />
        <footer className="content-foot"><span>ChipCheck / Experiment configuration</span><span>Requested ≠ measured</span></footer>
      </main>
      <SetupContext draft={draft} />
    </div>
  </div>;
}
