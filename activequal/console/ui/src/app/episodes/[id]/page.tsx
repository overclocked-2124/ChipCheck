"use client";

import Link from "next/link";
import { use } from "react";
import { useLoad } from "@/components/api";
import { Empty, ErrorBox, KeyValues, Loading, Mono, Notice, PageHeading, Section } from "@/components/ui";
import { formatValue, requestedVsMeasured } from "@/lib/results";
import { OUTCOME_STYLE, UNKNOWN_OUTCOME_STYLE } from "@/lib/series";
import type { EpisodeDetail } from "@/lib/types";

const TONE: Record<string, "ok" | "bad" | "warn" | "info"> = { PASS: "ok", DUT_FAILURE: "bad", INVALID_EXPERIMENT: "warn", SAFETY_ABORT: "bad" };
const yesNo = (v: unknown) => (v === true ? "yes" : v === false ? "NO" : "not reported");

/** One episode (HLD 09 §5, PRD §12.2): requested beside measured, the verdict and margins, bench quality, lease. */
export default function EpisodePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: e, error, loading } = useLoad<EpisodeDetail>(`/v1/episodes/${encodeURIComponent(id)}`, 4000);
  if (loading) return <Loading what="episode" />;
  if (!e) return <ErrorBox error={error} title="Could not load the episode" />;
  const rows = requestedVsMeasured(e);
  const outcome = e.outcome ? OUTCOME_STYLE[e.outcome] ?? UNKNOWN_OUTCOME_STYLE : null;
  const q = e.quality ?? {};
  const timeouts = Array.isArray(q.timeouts) ? q.timeouts : [];
  const lease = e.leases[e.leases.length - 1] ?? null;
  return (
    <>
      <PageHeading eyebrow="Episode" step={e.role} title={<>Episode <code>{e.id.slice(0, 12)}</code></>}
        intro={<>Part of campaign <Link href={`/campaigns/${e.campaignId}`}><code>{e.campaignId.slice(0, 12)}</code></Link>
          {e.linkedEpisodeId ? <> · follows up <Link href={`/episodes/${e.linkedEpisodeId}`}><code>{e.linkedEpisodeId.slice(0, 12)}</code></Link></> : null}
          {" "}· <Link href={`/campaigns/${e.campaignId}/results`}>Results</Link></>} />
      <ErrorBox error={error} title="Showing the last known episode record" />
      {e.verdict ? (
        <Notice tone={TONE[e.verdict.outcome] ?? "info"}>
          <strong>{outcome?.label ?? e.verdict.outcome}</strong> <code>{e.verdict.reasonCode}</code> {e.verdict.reason}
          {e.verdict.robustness !== null ? <> · robustness {formatValue(e.verdict.robustness)}</> : null}
        </Notice>
      ) : <Notice tone="info"><strong>In progress.</strong> State {e.state}; no verdict yet.</Notice>}
      <div className="grid2">
        <Section title="Requested" index={1} tag="Approved conditions">
          <div className="table-wrap"><table className="grid"><tbody>
            {rows.requested.map(([k, v]) => <tr key={k}><th scope="row">{k}</th><td className="num">{v}</td></tr>)}
          </tbody></table></div>
        </Section>
        <Section title="Planner and safety" index={2} tag={e.planner?.reasonCode ?? "—"}>
          <KeyValues rows={[
            ["Why this point", e.planner?.reason ?? "not recorded"],
            ["Planner", `${e.planner?.method ?? "?"}${e.discoveryIndex ? ` · discovery #${e.discoveryIndex}` : ""} · sequence ${e.plannerSequence ?? "?"}`],
            ["Safety decision", "approved by the deterministic rules (refused candidates never become episodes)"],
            ["Contract hash", <Mono key="h">{e.contractHash.slice(0, 16)}…</Mono>],
          ]} />
        </Section>
      </div>
      <Section title="Measured" index={3} tag="Requested ≠ measured">
        {rows.measured.length ? (
          <div className="table-wrap"><table className="grid">
            <thead><tr><th>Observation</th><th>Requested</th><th>Measured</th><th>Uncertainty</th></tr></thead>
            <tbody>{rows.measured.map(m => <tr key={m.name}><td><code>{m.name}</code></td><td className="num">{m.requested}</td><td className="num"><strong>{m.measured}</strong></td><td className="num">{m.uncertainty}</td></tr>)}</tbody>
          </table></div>
        ) : <Empty>No measurements recorded{e.outcome ? "" : " yet"}.</Empty>}
      </Section>
      {e.verdict ? (
        <Section title="Requirements" index={4} tag="Normalized margins">
          <div className="table-wrap"><table className="grid">
            <thead><tr><th>Requirement</th><th>Result</th><th>Margin</th></tr></thead>
            <tbody>{Object.entries(e.verdict.margins).map(([rid, m]) => {
              const status = typeof e.verdict!.requirements === "object" && e.verdict!.requirements && !Array.isArray(e.verdict!.requirements)
                ? String((e.verdict!.requirements as Record<string, unknown>)[rid] ?? "") : "";
              return <tr key={rid}><td><code>{rid}</code></td><td className={status === "FAIL" ? "bad-text" : undefined}>{status}</td><td className="num">{formatValue(m)}</td></tr>;
            })}</tbody>
          </table></div>
          <p className="hint">Margins are normalized to [-1, 1]; negative means the limit was crossed.</p>
        </Section>
      ) : null}
      <div className="grid2">
        <Section title="Bench quality" index={5} tag={e.safetyTrip ? "Safety trip" : "Evidence"}>
          <KeyValues rows={[
            ["Rail settled", yesNo(q.railSettled)], ["Shutdown confirmed", yesNo(q.shutdownConfirmed)],
            ["Instrument fault", q.instrumentFault === true ? "YES" : q.instrumentFault === false ? "no" : "not reported"],
            ["Timeouts", timeouts.length ? timeouts.join(", ") : "none"], ["Safety trip", e.safetyTrip ?? "none"],
            ["Traces", e.traces.length ? `${e.traces.length} file(s)` : "none"],
          ]} />
        </Section>
        <Section title="Lease" index={6} tag={lease?.state ?? "None"}>
          {lease ? <KeyValues rows={[["Owner", lease.owner], ["Issued", lease.issuedAt], ["Last heartbeat", lease.lastHeartbeatAt], ["Expires", lease.expiresAt]]} />
            : <Empty>Never leased.</Empty>}
        </Section>
      </div>
      {e.benchEvents.length ? (
        <Section title="Bench events" index={7} tag="Controller clock">
          <div className="table-wrap timeline"><table className="grid"><tbody>
            {e.benchEvents.map((ev, i) => <tr key={i}><td>{formatValue(ev.controllerTimeMs as number | undefined)} ms</td><td><code>{String(ev.type ?? "event")}</code></td>
              <td>{Object.entries(ev).filter(([k]) => k !== "type" && k !== "controllerTimeMs").map(([k, v]) => `${k}=${formatValue(v)}`).join(", ")}</td></tr>)}
          </tbody></table></div>
        </Section>
      ) : null}
    </>
  );
}
