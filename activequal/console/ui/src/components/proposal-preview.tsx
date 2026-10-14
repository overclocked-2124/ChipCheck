import { ProposalResponse, SetupDraft } from "@/lib/types";

export function ProposalPreview({ proposal, draft, loading }: {
  proposal: ProposalResponse | null; draft: SetupDraft; loading: boolean;
}) {
  if (!proposal && !loading) return null;
  return <section className="proposal-section" aria-labelledby="proposal-title" aria-live="polite" aria-busy={loading}>
    <div className="section-heading">
      <div><p className="overline">Decision preview</p><h2 id="proposal-title">Proposed conditions</h2></div>
      <span className="subtle-tag">{loading ? "Requesting" : proposal?.method?.toUpperCase()}</span>
    </div>
    {loading ? <div className="proposal-skeleton"><p>Choosing conditions from your configured domain…</p><div /><div /><div /></div> : proposal && <>
      <p className="section-description">{proposal.historyUsed ? `${proposal.historyUsed} measured results informed this selection.` : "Startup selection. No measured results have been supplied."} These candidates need approval before execution.</p>
      {proposal.tests.length ? <><p className="table-hint">Scroll across to compare every condition.</p><div className="table-scroll" tabIndex={0} role="region" aria-label="Proposed conditions table">
        <table className="candidate-table">
          <caption className="sr-only">Requested test conditions, not measured results</caption>
          <thead><tr><th scope="col">Candidate</th><th scope="col">{draft.railName || "Primary rail"}</th>{draft.sensorRailName && <th scope="col">{draft.sensorRailName}</th>}<th scope="col">Red LED</th><th scope="col">Green LED</th><th scope="col">Workload</th></tr></thead>
          <tbody>{proposal.tests.map((test, index) => <tr key={test.id}>
            <th scope="row"><span className="candidate-index">{String(index + 1).padStart(2, "0")}</span></th>
            <td>{test.conditions ? `${test.conditions.railVolts.toFixed(2)} V` : "Unavailable"}</td>
            {draft.sensorRailName && <td>{test.conditions?.sensorRailVolts !== undefined ? `${test.conditions.sensorRailVolts.toFixed(2)} V` : "Unavailable"}</td>}
            <td>{test.conditions?.redLed ?? "Unavailable"}</td><td>{test.conditions?.greenLed ?? "Unavailable"}</td>
            <td>{test.conditions?.workload ?? test.requested.join(" · ")}</td>
          </tr>)}</tbody>
        </table>
      </div></> : <div className="empty-proposals"><h3>No new candidates</h3><p>The planner returned no new conditions for this domain. Review the controls and available combinations.</p></div>}
      <div className="selection-notes"><h3>Selection notes</h3>{proposal.tests.map((test, i) => <p key={test.id}><span className="mono">{String(i + 1).padStart(2, "0")}</span>{test.reason || test.purpose}</p>)}</div>
      <div className="evidence-note"><span className="overline">Evidence to collect</span><p>{draft.observations}</p></div>
      <p className="table-footnote">Requested conditions only. No measurements, pass/fail outcomes or hardware actions.</p>
    </>}
  </section>;
}
