# ActiveQual HLD 05: APIs and Instrumentation Protocols

**Project:** ActiveQual: AI-Driven Adaptive Physical Testing for Embedded Systems  
**Document type:** High-Level Design  
**Status:** Initial draft for team review  
**Depends on:** HLD 01 (system context and stack amendment), HLD 02 (hardware), HLD 03 (state machine), HLD 04 (contract)

## 1. Purpose

This document defines the messages that connect ActiveQual's processes and devices:

- Console server routes to the control plane;
- the Agent to the Decision Service;
- the bench process (Controller and Adapter) to the control plane;
- the bench process to the test-controller MCU;
- the test-controller MCU and host to the ESP32 DUT.

It also fixes request identity, idempotency, versioning, error reporting, and timeouts at the protocol level. Lifecycle meaning lives in HLD 03 and field meaning in HLD 04; this document does not repeat them.

## 2. Decision labels

- **ActiveQual decision:** confirmed by the team.
- **Recommended:** preferred option awaiting review.
- **Open decision:** needs evidence or team agreement.

## 3. Process map

**ActiveQual decision (HLD 01 §2.1):** Python control-plane process (Backend, Agent, Decision, Oracle), Python bench process (Controller, bench-side validator, Adapter), Next.js Console whose server routes act as the backend-for-frontend.

**Recommended:** HTTP/JSON between processes, with request and response bodies defined as typed models (for example pydantic) and published as JSON Schema. gRPC is not required: every process is local, there is no streaming RPC that HTTP plus server-sent events cannot carry, and one language on both sides removes the main benefit of generated stubs.

```text
Browser ──HTTP──> Next.js server routes ──HTTP/JSON──> control plane (Backend + Agent + Decision + Oracle)
                                                          ^
bench process (Controller + Adapter) ──HTTP/JSON pull─────┘   (bench always initiates; HLD 01 §8.1)
bench process ──USB serial, framed──> test-controller MCU ──GPIO/UART──> ESP32 DUT
```

The control plane listens on loopback only for the MVP. The bench process never accepts inbound connections.

## 4. Common conventions

| Topic | Convention |
|---|---|
| Versioning | Path prefix `/v1`. A breaking change adds `/v2`; both run until clients move. |
| Identity | Every durable entity has a server-generated ID (UUIDv7 recommended, sortable by creation time). |
| Concurrency | State-changing campaign requests carry `campaignVersion`. A stale version returns `409 STALE_VERSION` (HLD 03 §20). |
| Idempotency | The keys of §8 come from the request body (`campaignId + plannerSequence` for candidates, `episodeId + attempt + manifestHash` for results), not from a header. A repeat with the same key and body returns the original response; the same key with a different body returns `409 IDEMPOTENCY_MISMATCH`. |
| Contract binding | Every bench message carries `contractHash` and `fixtureId`. A mismatch is rejected (HLD 03 §11.2). |
| Time | RFC 3339 UTC timestamps from the sender. Bench messages also carry a monotonic `controllerTimeMs` for trace alignment. |
| Units | Values travel in the units declared by the contract control or observation; no implicit conversion. |

### 4.1 Error model

```json
{"error": {"code": "STALE_VERSION", "message": "campaign changed since version 7", "details": {"currentVersion": 8}}}
```

| HTTP | `code` | Meaning |
|---|---|---|
| 400 | `INVALID_ARGUMENT` | Malformed or out-of-contract request (schema, range, forbidden combination) |
| 404 | `NOT_FOUND` | Unknown entity or not visible to the caller |
| 409 | `STALE_VERSION`, `IDEMPOTENCY_MISMATCH`, `INTEGRITY_ERROR` | Concurrency or integrity conflict; `INTEGRITY_ERROR` covers a result whose evidence hash differs from an accepted one (HLD 03 §16) |
| 412 | `FAILED_PRECONDITION` | Wrong state for the action (for example arming while `LOCKED_OUT`) |
| 503 | `UNAVAILABLE` | Dependency down; safe to retry non-physical requests |

Physical operations are never retried automatically (HLD 03 §17).

## 5. Console-facing API (control plane)

| Method and path | Purpose | Notes |
|---|---|---|
| `POST /v1/contracts` | Create a contract version from canonical JSON | Server validates against HLD 04 §12 and returns `contractId`, `version`, `contractHash` |
| `GET /v1/contracts` | Every contract version, newest first, with hash and approval state | Summaries only; read one version for its JSON |
| `POST /v1/contracts/{id}/versions/{v}:approve` | Record reviewer approval | Requires the reviewer role (HLD 07) |
| `GET /v1/contracts/{id}/versions/{v}` | Read a version | Immutable once approved |
| `POST /v1/fixtures` | Register a fixture: ID, revision, adapter capabilities | Reviewer only; issues the bench token (HLD 07 §5) |
| `GET /v1/fixtures` | Every fixture with health and current calibration | |
| `GET /v1/fixtures/{id}` | Fixture health and current calibration | |
| `POST /v1/fixtures/{id}:rotate-token` | Issue a new bench token; the old one stops working | Reviewer only; the token is shown once |
| `POST /v1/fixtures/{id}/calibrations` | Record a calibration: per-channel gain, offset, uncertainty, meter identity, operator | Arming requires a current calibration (HLD 03 §6.2) |
| `POST /v1/campaigns` | Create a campaign in `DRAFT` | Body: contract version, fixture, planner, seed, plan |
| `POST /v1/campaigns/{id}:validate` | `DRAFT` → `VALIDATING` → `READY` or back | Returns structured reasons on failure |
| `POST /v1/campaigns/{id}:arm` / `:start` / `:pause` / `:resume` / `:abort` / `:disarm` | Researcher actions | Each carries `campaignVersion`; transitions per HLD 03 §6 |
| `POST /v1/campaigns/{id}:clear-lockout` | Record lockout review | Requires physical-presence confirmation (HLD 07 §7) |
| `GET /v1/campaigns/{id}` | Campaign state, budget, counts | |
| `GET /v1/campaigns` | Campaign list, newest first | |
| `POST /v1/campaigns/{id}/manual-candidates` | Operator-chosen candidate (PRD §18.1 demo) | Same safety validation as planner candidates; reason code `MANUAL`; the sequence number is taken inside the insert, so it cannot collide with the Agent's; counts against the discovery budget |
| `GET /v1/campaigns/{id}/episodes` | Finalized episodes in planner-history shape, plus refused candidates | What the planners read |
| `GET /v1/campaigns/{id}/records` | Every episode with requested and measured values, verdict, planner reason, quality flags; refused candidates with violations | Console tables and charts (HLD 08 §5 record shape) |
| `GET /v1/campaigns/{id}/counterexamples` | Stored counterexamples | |
| `GET /v1/campaigns/{id}/report` | The campaign report as JSON (PRD §19.2 language, reproduction intervals, stop reason, metrics) | Same content as the exported report |
| `GET /v1/campaigns/{id}/contract` | The campaign's contract, approvals, arming tuple and expected maximum runtime | Arming checklist (HLD 09 §5) |
| `GET /v1/campaigns/{id}/lease` | The live lease: owner, last heartbeat, expiry, or `NEEDS_RECONCILIATION` | `null` when no episode is leased |
| `GET /v1/compare?campaigns=a,b` | Episodes to the first confirmed failure per campaign and the HLD 06 §8 comparison (Kaplan–Meier, discovery rates, log-rank), grouped by contract hash | Statistics are computed here, never in the browser (HLD 09 §9) |
| `GET /v1/campaigns/{id}/export` | Evidence bundle (HLD 08 §6) and generated report | |
| `GET /v1/campaigns/{id}/events` | Server-sent events stream | State transitions, episode phases, outcomes |
| `GET /v1/episodes/{id}` | Episode record with planner reason, bench quality flags and events, traces and leases | Requested and measured values kept separate |
| `POST /v1/leases/{id}:reconcile` | A reviewer decides what an expired lease means (`not_executed` or `evidence_lost`) with a note | Reviewer only; the campaign then locks out for inspection |
| `GET /healthz`, `GET /metrics` | Liveness; Prometheus text (HLD 08 §7) | No operator token; loopback only |
| `POST /v1/proposals` | Unapproved candidate preview (the Decision HTTP form, §6) | Preview only; never creates episodes |

## 6. Agent and Decision Service

**ActiveQual decision (HLD 01):** Decision runs as a module inside the control-plane process for the MVP.

- **In-process call:** `planner.propose(domain, history, count, seed, config) -> list[CandidateProposal]` (implemented in `activequal/decision/service/planners/base.py`).
- **HTTP form:** `POST /v1/proposals` with body `{contract | setup, method, seed, count, warmupTrials, history}` and response `{source, method, setupName, historyUsed, tests: [{id, conditions, reason}]}`. Each proposal will also carry a machine-readable `reasonCode` (`STARTUP`, `MODEL`, `FALLBACK`, `BASELINE`, `MANUAL`; NFR-08, HLD 10 WP16). Kept for the console preview and for out-of-process testing.
- **Determinism:** the same request returns the same response. Per-call sampler seeds are derived by hashing the campaign seed with the history length, so campaigns with nearby seeds stay independent.
- **Inputs never include** the seeded fault trigger, the private ground-truth marker, or any field outside the contract's public observations.

Agent submits a returned candidate with the Backend candidate submission (an in-process call inside the control plane; no HTTP route), idempotency key `campaignId + plannerSequence` (HLD 03 §16). The Agent and manual candidates let Backend take the next free sequence inside the insert transaction, so two submitters never pick the same number; an explicit sequence still gets the idempotent replay behavior.

## 7. Bench-facing API (pull model)

| Method and path | Purpose | Idempotency |
|---|---|---|
| `POST /v1/bench/claim` | `ClaimNextEpisode` in HLD 03 §10. Claim the next `AVAILABLE` episode for `fixtureId`; returns lease, candidate, `contractHash`, deadlines, or `204` if none | Server-side atomic claim; lease ID is the key |
| `POST /v1/bench/leases/{leaseId}:heartbeat` | Extend the lease, report phase; response carries pending `abort` or `pause` requests | Safe to repeat |
| `POST /v1/bench/leases/{leaseId}:abort-ack` | Confirm the bench reached shutdown after an abort | Safe to repeat |
| `POST /v1/bench/episodes/{episodeId}/results` | `SubmitEpisodeResult` in HLD 03 §10. Submit observations, events, trace manifest | `episodeId + attempt + manifestHash` |
| `PUT /v1/bench/traces/{sha256}` | Upload a raw trace by content hash | Content hash |
| `POST /v1/bench/health` | Fixture health (E-stop, interlock, watchdog, adapter capabilities) | Safe to repeat |

The bench submits **evidence, not outcomes**. The Oracle in Backend classifies the result (HLD 01 decision 13, HLD 04 §13).

### 7.1 Result payload (summary)

```json
{
  "episodeId": "…", "attempt": 1, "leaseId": "…", "contractHash": "…", "fixtureId": "bench-A",
  "requested": {"oledRailV": 3.24, "redLed": true, "greenLed": false, "workload": "oled_refresh"},
  "measured": {"measuredOledRailV": {"value": 3.238, "uncertainty": 0.01}, "oledLatencyMs": {"value": 151, "uncertainty": 5}},
  "quality": {"complete": true, "railSettled": true, "instrumentFault": false, "timeouts": []},
  "events": [{"type": "OUTPUT_ENABLE", "controllerTimeMs": 1203}],
  "traces": [{"sha256": "…", "mediaType": "application/vnd.apache.parquet", "bytes": 48213}],
  "manifestHash": "…"
}
```

## 8. Idempotency keys

From HLD 03 §16, mapped to this API:

| Operation | Key |
|---|---|
| Candidate submission | `campaignId + plannerSequence` |
| Episode creation | approved candidate ID |
| Lease claim | server-generated lease ID |
| Result submission | `episodeId + attempt + manifestHash` |
| Trace upload | SHA-256 of content |

## 9. Test-controller serial protocol

**Recommended.** HLD 02 §8.3 requires versioned framing, checksums, explicit rejection, duplicate detection, and an emergency shutdown command. The line-oriented text protocol in `SIMPLIFIED-PLAN.md` has none of these and is superseded.

### 9.1 Framing

- USB CDC serial. Frames are COBS-encoded with a `0x00` delimiter, so a lost byte costs one frame, not the stream.
- Frame layout before encoding:

| Field | Size | Notes |
|---|---|---|
| `version` | 1 | Protocol version, starts at 1 |
| `type` | 1 | Message type (§9.2) |
| `seq` | 2 | Sender sequence number; receiver drops duplicates and reports gaps |
| `episodeTag` | 4 | Low 32 bits of the episode ID; 0 outside an episode |
| `length` | 2 | Payload length |
| `payload` | n | Little-endian fixed-layout fields per type |
| `crc` | 2 | CRC-16/CCITT-FALSE over all preceding fields |

### 9.2 Message types

| Direction | Type | Purpose |
|---|---|---|
| host → MCU | `HELLO` | Version and capability exchange; MCU returns firmware hash and fixture ID |
| host → MCU | `HEARTBEAT` | Host liveness (§9.3) |
| host → MCU | `SET_LIMITS` | Program per-channel voltage and current limits; MCU echoes read-back |
| host → MCU | `LOAD_PLAN` | Bounded event template for one episode (HLD 02 §8.1) |
| host → MCU | `SET_RAIL`, `ENABLE_RAIL`, `DISABLE_RAIL`, `READ_ALL` | Rail control and read-back |
| host → MCU | `EXECUTE`, `ABORT`, `SHUTDOWN` | Episode control; `SHUTDOWN` is honored in any state |
| MCU → host | `ACK`, `NACK{reason}` | Every command is acknowledged or explicitly rejected |
| MCU → host | `MEASUREMENT`, `EVENT`, `STATUS`, `ALERT` | Read-back, timestamped events, trips (overcurrent, watchdog, E-stop) |

### 9.3 Liveness

- Host sends `HEARTBEAT` every 250 ms (**Recommended**).
- MCU moves outputs to shutdown if no valid frame arrives for 1 s (**Recommended**).
- The RP2040 hardware watchdog (maximum about 8.3 s) is a backstop for MCU firmware lockup, set well below the episode maximum; the independent hardware interlock (HLD 02 §13) remains the final layer.

## 10. DUT protocol

- **ActiveQual decision (2026-11-06, §13):** workload commands could reach the ESP32 through the test-controller MCU (deterministic timing, HLD 02 §8) or directly from the host over UART (simpler, as in `SIMPLIFIED-PLAN.md`). Route timing-critical commands (workload start, LED states inside an event template) through the MCU; DUT telemetry may stream to the host over UART for the MVP.
- Message set from HLD 02 §12: `SET_RED_LED`, `SET_GREEN_LED`, `OLED_REFRESH`, `SENSOR_READ`, `AUXILIARY_OPERATION`, `GET_HEARTBEAT`, `GET_RESET_REASON`, `RESET_TO_KNOWN_STATE`. Every reply carries episode tag, sequence number, status, timestamps, and error code.
- **Recommended:** use the same COBS + CRC framing as §9 so both links share one parser and one test suite.
- The DUT never emits a seeded-fault marker on the evaluation link; ground-truth markers go to a separate, physically disconnected log during evaluation campaigns.

## 11. Timeouts at the protocol level

Values are starting points to be replaced by bench measurements (HLD 03 §21 owns the episode-level table).

| Timeout | Starting value | Basis |
|---|---|---|
| Lease heartbeat interval / expiry | 1 s / 5 s | Detect a lost Controller well inside one episode |
| Control-plane HTTP request | 10 s | Covers the slowest planner call measured (GP-BO under 1 s at p95 after the starvation fix) |
| MCU command acknowledgement | 100 ms | USB round trip is a few ms; leaves margin for flash writes |
| Host heartbeat / host-loss shutdown | 250 ms / 1 s | §9.3 |

## 12. End-to-end example

```text
Agent   -> Decision      propose(...)                       -> candidate c17 (TPE, reason)
Agent   -> Backend       submit_candidate (in-process) key=campaign+17 -> APPROVED, episode e42 AVAILABLE
Bench   -> Backend       POST /bench/claim                  -> lease L9, candidate, contractHash
Bench   -> MCU           HELLO / SET_LIMITS / LOAD_PLAN      <- ACK, ACK (limits read back), ACK
Bench   -> MCU           SET_RAIL oled 3.24 / ENABLE_RAIL    <- MEASUREMENT 3.238 V (settled)
Bench   -> MCU           EXECUTE                             <- EVENT stream, MEASUREMENT, STATUS done
Bench   -> MCU           DISABLE_RAIL / SHUTDOWN             <- ACK (shutdown confirmed)
Bench   -> Backend       POST /bench/episodes/e42/results   key=e42+1+manifestHash
Backend -> Oracle        classify(evidence, contract)       -> DUT_FAILURE, margins, reason
```

## 13. Decisions

**ActiveQual decision (2026-11-06):**

| Decision | Outcome |
|---|---|
| DUT command path (§10) | Timing-critical commands go through the MCU, so their timestamps share the MCU clock with the event markers and the optical capture |
| Trace format | Owned by HLD 08 §10; this document only carries trace references and checksums |
| Schema publication | Planned: JSON Schema generated from the typed models and checked in, with a CI diff check. Not built yet; the Python parsers are the reference today |

## 14. Acceptance checklist

- Every request in §5 and §7 has a schema, an error mapping, and a test for its failure modes.
- Replaying any idempotent request returns the original result; a changed body returns `IDEMPOTENCY_MISMATCH`.
- A dropped, duplicated, or corrupted serial frame is detected and never executed.
- Host loss moves outputs to shutdown within the host-loss timeout, measured on hardware.

## 15. Change log

| Date | Change |
|---|---|
| 2026-11-05 | Initial draft |
| 2026-11-06 | §13 decisions recorded; trace format deferred to HLD 08 |
