# ActiveQual HLD 08: Persistence, Telemetry, and Observability

**Project:** ActiveQual: AI-Driven Adaptive Physical Testing for Embedded Systems  
**Document type:** High-Level Design  
**Status:** Initial draft for team review  
**Depends on:** HLD 01 (data ownership), HLD 03 (lifecycle, audit events), HLD 04 (contract, robustness), HLD 05 (APIs)

## 1. Purpose and scope

This document defines what ActiveQual stores, where, and how it can be queried, exported, and audited. It covers the campaign database, raw traces, the bench's local spool, the evidence bundle, logs, and metrics.

## 2. Principles

1. **Requested and measured values are stored separately** and analysis uses measured values (HLD 01 principle 5).
2. **Append-only history:** every state transition is an event; current-state columns exist for fast reads (HLD 03 §19).
3. **Immutable evidence:** raw traces are content-addressed by SHA-256 and never edited. Corrections create a new derived record (PRD §22.4).
4. **Every result is traceable** to one contract version, fixture, firmware, calibration, planner configuration, and software version (CTX-01).
5. **Nothing is silently dropped:** invalid, aborted, and inconclusive episodes are stored like any other.

## 3. Storage choices

**Recommended:**

| Data | Store | Reason |
|---|---|---|
| Campaign metadata and audit history | SQLite in WAL mode, behind a repository interface | One workstation, one writer process (the control plane), zero setup; the interface allows PostgreSQL later |
| Raw traces | Local filesystem, content-addressed (`traces/ab/cd/<sha256>`) | Large binary files do not belong in rows (HLD 01 §11) |
| Bench spool | Local directory on the bench process, one file per pending result | Survives control-plane outages (HLD 03 §8, `EVIDENCE_PENDING`) |

Optuna studies are not a store of record. The Decision Service rebuilds its model from the history the Agent supplies on every call.

## 4. Entities

| Entity | Key fields |
|---|---|
| `project` | id, name; every entity below belongs to exactly one project (HLD 01 §10) |
| `contract_version` | id, project_id, version, canonical JSON, `contract_hash`, created_by, approved_by, approved_at |
| `fixture` | id, project_id, revision, registered capabilities, current `calibration_id` |
| `calibration` | id, fixture_id, per-channel gain/offset, uncertainty, meter identity, operator, date |
| `campaign` | id, project_id, state, `version` (optimistic concurrency), contract_version, fixture, planner method, planner config, seed, plan (HLD 04 §14), budgets, software version |
| `candidate` | id, campaign, planner_sequence, conditions, planner reason, state, rejection reason |
| `episode` | id, campaign, candidate, attempt, lifecycle state, outcome, linked_episode (for replays), role (`discovery`, `confirm`, `minimize`, `bracket`, `necessity_probe`) |
| `lease` | id, episode, controller instance, fixture, issued_at, expires_at, last_heartbeat_at, contract_hash |
| `observation` | episode, metric, requested value (if a control), measured value, uncertainty, quality flags |
| `verdict` | episode, per-requirement margins (Option A), robustness, guard-banded result per requirement (Option B), outcome, reason |
| `event` | id, campaign, episode, attempt, previous_state, new_state, actor_type, actor_id, reason_code, human reason, backend and controller timestamps, contract_hash, fixture_id |
| `trace` | sha256, episode, media type, bytes, capture metadata, storage path |
| `counterexample` | id, original episode, minimized conditions, bracketed intervals with resolution, reproduction count and rate, seeded/natural/unknown |

Candidates, episodes, leases, observations, verdicts, events, traces and counterexamples inherit their project through their campaign; every read checks it (HLD 01 §10).

The `role` field on `episode` lets every report separate the discovery budget from the verification budget (HLD 04 §14), which the research metrics depend on (HLD 06).

## 5. Episode record example

```json
{
  "episodeId": "e42", "campaignId": "c7", "attempt": 1, "role": "discovery",
  "requested": {"oledRailV": 3.24, "redLed": true, "greenLed": false, "workload": "oled_refresh"},
  "measured": {"measuredOledRailV": {"value": 3.238, "uncertainty": 0.01},
               "oledLatencyMs": {"value": 151, "uncertainty": 5},
               "maxHeartbeatGapMs": {"value": 203, "uncertainty": 10}, "resetCount": {"value": 0}},
  "verdict": {"margins": {"latency": -0.35, "heartbeat": 0.99, "reset": 1.0}, "robustness": -0.35,
              "requirements": {"latency": "FAIL", "heartbeat": "PASS", "reset": "PASS"},
              "outcome": "DUT_FAILURE", "reason": "latency 151 ms > 120 + 5 ms (guard band)"},
  "planner": {"method": "tpe", "reason": "TPE selected this from prior measured robustness"},
  "traces": ["9f2c…"], "contractHash": "…", "fixtureId": "bench-A", "software": "git:7723790"
}
```

## 6. Evidence bundle

Exported per campaign as a directory or archive:

```text
campaign-<id>/
├── manifest.json          ids, versions, hashes, software commits, export time
├── contract.json          canonical contract and approvals
├── calibration.json
├── planner.json           method, seed, plan
├── episodes.jsonl         one record per episode (section 5), including invalid and aborted
├── events.jsonl           full audit history
├── counterexamples/       original and minimized counterexamples
├── traces/                raw traces referenced by hash
├── report.md              generated report (HLD 09)
└── checksums.sha256
```

Seeded-fault ground-truth labels are exported separately and only after evaluation is frozen, so blind evaluation stays possible (PRD §22.4).

## 7. Logs and metrics

**Recommended:**

- **Structured logs:** JSON lines with `campaignId`, `episodeId`, `leaseId`, and `phase` on every line, written by each process to a rotating local file.
- **Metrics:** exposed by the control plane at `GET /metrics` (Prometheus text format) and summarized in the Console.

| Metric | Why |
|---|---|
| episodes by outcome and role | Budget use and invalid-experiment rate (kill criterion in HLD 10) |
| candidate rejections by reason | Planner or contract design errors (HLD 03 §7.1) |
| planner call latency | GP-BO and TPE cost (HLD 06) |
| lease expiries and reconciliations | Bench reliability |
| spool depth and upload failures | Evidence at risk |
| safety trips by type | Lockout causes |

Errors must reach the Console, not only the logs (HLD 03 §22).

## 8. Retention and export

- Keep everything for the life of the project; raw traces are the largest item and are bounded by the number of episodes.
- Export bundles for every evaluation campaign at the evidence freeze (HLD 10).
- Never rewrite a stored episode; annotations are separate rows.

## 9. Research queries the schema must support

- Episodes to first confirmed failure per campaign, discovery budget only (HLD 06 primary metric).
- Discovery rate at budgets 30 and 50.
- Invalid and inconclusive rates per campaign and per fixture.
- Requested versus measured deviation per rail.
- Counterexample reproduction rates with confidence intervals.

## 10. Decisions

**ActiveQual decision (2026-11-06):**

| Decision | Outcome |
|---|---|
| Database | SQLite (WAL) for the MVP behind a repository interface; one writer, matching the single control-plane process (HLD 10 §5.3) |
| Trace format | Parquet for sampled series; raw capture plus JSON sidecar for scope data. This document owns the trace format; HLD 05 refers here |
| Metrics backend | Prometheus text endpoint, read by the Console; no external monitoring stack |

## 11. Acceptance checklist

- Every stored episode links to contract, fixture, firmware, calibration, planner, and software version.
- A campaign can be fully reconstructed from `events.jsonl`.
- Trace checksums verify on export and on re-import.
- Killing the control plane mid-campaign loses no accepted result; pending bench results upload after restart.

## 12. Change log

| Date | Change |
|---|---|
| 2026-11-05 | Initial draft |
| 2026-11-06 | §10 decisions recorded; trace format owned here |
