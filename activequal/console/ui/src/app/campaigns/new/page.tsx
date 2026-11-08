"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, useLoad } from "@/components/api";
import { NumberField, Select } from "@/components/controls";
import { ErrorBox, Notice, PageHeading, Section } from "@/components/ui";
import { numberProblem } from "@/lib/number";
import { PLANNERS, type ApiResult, type CampaignView, type ContractSummary, type FixtureView, type UiError } from "@/lib/types";

type Listed = ContractSummary & { dut: string | null; fixture: string | null };

const PLANNER_HINT: Record<string, string> = {
  tpe: "adaptive", gp: "adaptive", random: "baseline", grid: "baseline", fixed_corner: "baseline", coverage: "baseline",
};

export default function NewCampaignPage() {
  const router = useRouter();
  const contracts = useLoad<{ contracts: Listed[] }>("/v1/contracts");
  const fixtures = useLoad<{ fixtures: FixtureView[] }>("/v1/fixtures");
  const [contractId, setContractId] = useState("");
  const [version, setVersion] = useState("");
  const [fixtureId, setFixtureId] = useState("");
  const [planner, setPlanner] = useState<string>("tpe");
  const [seed, setSeed] = useState("1");
  const [discovery, setDiscovery] = useState("50");
  const [verification, setVerification] = useState("24");
  const [error, setError] = useState<UiError | null>(null);
  const [busy, setBusy] = useState(false);

  const all = contracts.data?.contracts ?? [];
  const ids = useMemo(() => [...new Set(all.map(c => c.contractId))], [all]);
  const versions = all.filter(c => c.contractId === contractId).sort((a, b) => b.version - a.version);
  const chosen = versions.find(v => String(v.version) === version) ?? null;
  const fixtureList = fixtures.data?.fixtures ?? [];

  // Default to the newest approved version, and to the fixture the contract names when it is registered.
  useEffect(() => { if (!contractId && ids.length) setContractId(ids[0]); }, [ids, contractId]);
  useEffect(() => {
    if (!versions.length || versions.some(v => String(v.version) === version)) return;
    setVersion(String((versions.find(v => v.approved) ?? versions[0]).version));
  }, [versions, version]);
  useEffect(() => {
    const named = chosen?.fixture;
    if (named && fixtureList.some(f => f.id === named)) setFixtureId(named);
    else if (!fixtureId && fixtureList.length) setFixtureId(fixtureList[0].id);
  }, [chosen?.fixture, fixtureList]); // eslint-disable-line react-hooks/exhaustive-deps

  const problems = [
    numberProblem(seed, { integer: true, min: 0 }),
    numberProblem(discovery, { integer: true, min: 1 }),
    numberProblem(verification, { integer: true, min: 0 }),
  ].filter(Boolean);
  const ready = !!contractId && !!version && !!fixtureId && problems.length === 0;

  async function submit() {
    if (!ready) return;
    setBusy(true); setError(null);
    const result: ApiResult<CampaignView> = await api<CampaignView>("/v1/campaigns", {
      method: "POST",
      body: {
        contractId, version: Number(version), fixtureId, planner,
        seed: Number(seed), discoveryBudget: Number(discovery), verificationBudget: Number(verification),
      },
    });
    setBusy(false);
    if (result.ok) router.push(`/campaigns/${result.data.id}`); else setError(result.error);
  }

  const loading = contracts.loading || fixtures.loading;
  return (
    <>
      <PageHeading eyebrow="Configure" step="New campaign" title="Start a campaign"
        intro="Pick an approved contract, the fixture it runs on, a planner and its budgets. Nothing reaches the bench until you validate, arm and start." />
      <ErrorBox error={contracts.error ?? fixtures.error} title="Could not load contracts and fixtures" />
      {!loading && !ids.length ? <Notice tone="warn">No contract exists yet. <Link href="/contracts">Create and approve one</Link> first.</Notice> : null}
      {!loading && ids.length && !fixtureList.length ? <Notice tone="warn">No fixture is registered. <Link href="/fixtures">Register the bench</Link> first.</Notice> : null}
      <Section title="Setup" index={1} tag="Configuration">
        <form onSubmit={e => { e.preventDefault(); void submit(); }}>
          <div className="fields">
            <Select label="Contract" value={contractId} onChange={v => { setContractId(v); setVersion(""); }} disabled={!ids.length}
              placeholder={loading ? "Loading…" : "No contracts"}
              options={ids.map(id => { const any = all.find(c => c.contractId === id); return { value: id, label: id, hint: any?.dut ?? undefined }; })} />
            <Select label="Version" value={version} onChange={setVersion} disabled={!versions.length} placeholder="Choose a contract"
              options={versions.map(v => ({ value: String(v.version), label: `v${v.version}`, hint: v.approved ? "approved" : `${v.approvedBy.length}/${v.approvalsRequired} approvals` }))} />
            <Select label="Fixture" value={fixtureId} onChange={setFixtureId} disabled={!fixtureList.length} placeholder={loading ? "Loading…" : "No fixtures"}
              options={fixtureList.map(f => ({ value: f.id, label: f.id, hint: f.revision }))} />
            <Select label="Planner" value={planner} onChange={setPlanner}
              options={PLANNERS.filter(p => p !== "manual").map(p => ({ value: p, label: p, hint: PLANNER_HINT[p] }))} />
            <NumberField label="Seed" value={seed} onChange={setSeed} rule={{ integer: true, min: 0 }} hint="Same seed, same proposals" />
            <NumberField label="Discovery episodes" value={discovery} onChange={setDiscovery} rule={{ integer: true, min: 1 }} step={5} />
            <NumberField label="Verification episodes" value={verification} onChange={setVerification} rule={{ integer: true, min: 0 }} step={2} />
          </div>
          {chosen && !chosen.approved ? (
            <Notice tone="warn">Version {chosen.version} has {chosen.approvedBy.length} of {chosen.approvalsRequired} approvals. Validation will refuse it until it is approved. <Link href={`/contracts/${chosen.contractId}/${chosen.version}`}>Review it</Link></Notice>
          ) : null}
          <ErrorBox error={error} title="Could not create the campaign" />
          <div className="card-actions">
            <span className="action-note">Next: validate and arm on the campaign page</span>
            <button type="submit" disabled={busy || !ready}>{busy ? "Creating…" : "Create campaign"} <span className="arrow" aria-hidden="true">→</span></button>
          </div>
        </form>
      </Section>
      <p className="note"><strong>Before you start.</strong> The fixture needs a current calibration. Budgets are checked against the contract when you validate.</p>
    </>
  );
}
