import { SetupDraft } from "@/lib/types";

export function SetupContext({ draft }: { draft: SetupDraft }) {
  return <aside className="setup-context" aria-label="Setup reference">
    <p className="overline">On this bench</p>
    <h2>{draft.name || "A setup, precisely defined."}</h2>
    <p className="context-intro">One device, its controls, and the evidence that will judge its behavior.</p>
    <svg className="bench-diagram" viewBox="0 0 250 172" role="img" aria-labelledby="bench-title">
      <title id="bench-title">Device with independently configured primary and optional sensor rails</title>
      <path d="M90 48H48V84M160 48h42v36M108 117v24h55" fill="none" stroke="currentColor" strokeWidth="1" />
      <rect x="90" y="22" width="70" height="55" rx="3" /><text x="125" y="45" textAnchor="middle">DUT</text><text x="125" y="61" textAnchor="middle" className="diagram-small">fixed supply</text>
      <rect x="22" y="84" width="66" height="33" rx="2" /><text x="55" y="104" textAnchor="middle">Rail 01</text>
      <rect x="163" y="84" width="65" height="33" rx="2" /><text x="195" y="104" textAnchor="middle">Rail 02</text>
      <circle cx="108" cy="117" r="2" /><text x="166" y="144" className="diagram-small">observations</text>
    </svg>
    <dl className="context-facts">
      <div><dt>Primary rail</dt><dd>{draft.railName || "Not configured"}</dd>{draft.railMin && draft.railMax && <dd className="mono">{draft.railMin}–{draft.railMax} V</dd>}</div>
      <div><dt>Sensor rail</dt><dd>{draft.sensorRailName || "Optional"}</dd>{draft.sensorRailName && draft.sensorRailMin && draft.sensorRailMax && <dd className="mono">{draft.sensorRailMin}–{draft.sensorRailMax} V</dd>}</div>
      <div><dt>Campaign budget</dt><dd className="mono">{draft.experimentBudget ? `${draft.experimentBudget} experiments` : "Not set"}</dd></div>
    </dl>
    <div className="context-note"><span className="note-mark" aria-hidden="true">i</span><p>This console proposes conditions. Backend and bench checks approve physical execution.</p></div>
  </aside>;
}
