"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/components/api";
import { ErrorBox, PageHeading, Section } from "@/components/ui";
import { PLANNERS, type ApiResult, type CampaignView, type UiError } from "@/lib/types";

export default function NewCampaignPage() {
  const router = useRouter();
  const [contractId, setContractId] = useState("");
  const [version, setVersion] = useState("1");
  const [fixtureId, setFixtureId] = useState("");
  const [planner, setPlanner] = useState<string>("tpe");
  const [seed, setSeed] = useState("1");
  const [discovery, setDiscovery] = useState("50");
  const [verification, setVerification] = useState("24");
  const [error, setError] = useState<UiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true); setError(null);
    const result: ApiResult<CampaignView> = await api<CampaignView>("/v1/campaigns", {
      method: "POST",
      body: {
        contractId: contractId.trim(), version: Number(version), fixtureId: fixtureId.trim(), planner,
        seed: Number(seed), discoveryBudget: Number(discovery), verificationBudget: Number(verification),
      },
    });
    setBusy(false);
    if (result.ok) router.push(`/campaigns/${result.data.id}`); else setError(result.error);
  }

  return (
    <>
      <PageHeading eyebrow="Configure" step="New campaign" title="Start a campaign"
        intro="Pick an approved contract, the fixture it runs on, a planner and its budgets. Nothing reaches the bench until you validate, arm and start." />
      <Section title="Setup" index={1} tag="Configuration">
        <form onSubmit={e => { e.preventDefault(); void submit(); }}>
          <div className="fields">
            <label className="wide">Contract id<input value={contractId} onChange={e => setContractId(e.target.value)} required placeholder="from the Contracts page" /></label>
            <label>Contract version<input type="number" min={1} value={version} onChange={e => setVersion(e.target.value)} required /></label>
            <label>Fixture id<input value={fixtureId} onChange={e => setFixtureId(e.target.value)} required placeholder="bench-A" /></label>
            <label>Planner
              <select value={planner} onChange={e => setPlanner(e.target.value)}>{PLANNERS.filter(p => p !== "manual").map(p => <option key={p}>{p}</option>)}</select>
            </label>
            <label>Seed<input type="number" value={seed} onChange={e => setSeed(e.target.value)} required /></label>
            <label>Discovery episodes<input type="number" min={1} value={discovery} onChange={e => setDiscovery(e.target.value)} required /></label>
            <label>Verification episodes<input type="number" min={0} value={verification} onChange={e => setVerification(e.target.value)} required /></label>
          </div>
          <ErrorBox error={error} title="Could not create the campaign" />
          <div className="card-actions">
            <span className="action-note">Next: validate and arm on the campaign page</span>
            <button type="submit" disabled={busy}>{busy ? "Creating…" : "Create campaign"} <span className="arrow" aria-hidden="true">→</span></button>
          </div>
        </form>
      </Section>
      <p className="note"><strong>Before you start.</strong> The contract must be approved and the fixture registered with a current calibration. Budgets are checked against the contract when you validate.</p>
    </>
  );
}
