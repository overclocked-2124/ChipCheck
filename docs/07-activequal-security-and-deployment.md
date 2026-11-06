# ActiveQual HLD 07: Security and Deployment

**Project:** ActiveQual: AI-Driven Adaptive Physical Testing for Embedded Systems  
**Document type:** High-Level Design  
**Status:** Initial draft for team review  
**Depends on:** HLD 01 (stack amendment), HLD 03 (state machine), HLD 05 (APIs)

## 1. Purpose and scope

This document defines who and what may act on ActiveQual, how the processes start and stop, and how credentials, configuration, and versions are bound together for the 12-week MVP.

The MVP runs on one supervised laboratory workstation. Remote, multi-bench, or Internet-facing deployment is out of scope (HLD 01 §3.4) and is covered only as future considerations in §9.

## 2. Threat model for the MVP

The main risks are accidental, not adversarial:

| Risk | Example | Control |
|---|---|---|
| Wrong command reaches hardware | Stale or replayed request re-runs an episode | Lease IDs, idempotency keys, contract and fixture hash binding (§5) |
| Wrong configuration | Firmware or wiring changed without re-approval | Version binding at arm time (§6) |
| Unsupervised operation | Campaign armed or lockout cleared remotely | Loopback-only services, physical-presence rules (§7) |
| Credential leak | Bench token committed to the repository | Secrets outside the repository (§8) |
| Data loss | Evidence lost on crash | Local spool and checksums (HLD 08) |

Deliberate attack by a local user with workstation access is not defended against in the MVP; the workstation is a supervised lab machine.

## 3. Deployment shape

**ActiveQual decision (HLD 01 §2.1):** one workstation, three processes.

| Process | Contents | Listens on |
|---|---|---|
| Web | Next.js Console and its server routes | `127.0.0.1:3000` |
| Control plane | Backend, Agent, Decision, Oracle; campaign database | `127.0.0.1:8001` (recommended) |
| Bench | Controller, bench-side validator, Adapter; USB serial to the test-controller MCU | No listener; outbound to the control plane only |

Firmware runs on the test-controller MCU and the ESP32 DUT.

**Recommended:** run the three processes under a process supervisor (for example systemd user units or a Procfile runner) so restarts are logged and ordered.

## 4. Startup, readiness, and shutdown

### 4.1 Startup order

1. **Control plane:** apply database migrations, load contracts, mark any lease that was active at the last shutdown as needing reconciliation (HLD 03 §9.2), then report ready on `GET /healthz`.
2. **Bench process:** command every output to shutdown before anything else, exchange `HELLO` with the MCU (firmware hash, fixture ID), report fixture health, then begin polling `claim`.
3. **Web:** serves the Console; it holds no physical authority, so its order is not safety-relevant.

A bench process that cannot reach the MCU or cannot confirm shutdown state reports itself unhealthy and claims no work.

### 4.2 Shutdown

1. Stop issuing claims.
2. Finish or abort the current episode at a safe boundary (HLD 03 §14).
3. Confirm outputs are in shutdown state.
4. Flush the local evidence spool.
5. Exit.

A crash at any step leaves the MCU's host-loss timeout and the hardware interlock to remove power (HLD 05 §9.3).

## 5. Machine identity and replay protection

**Recommended:**

- The bench process authenticates to the control plane with a per-fixture bearer token. The token is bound server-side to one project and one `fixtureId`, can be revoked, and may carry an expiry for demonstrations.
- Allowed RPCs for the token are only the bench endpoints in HLD 05 §7.
- Replay protection comes from the protocol, not the transport: a claim returns a fresh lease ID, results carry `episodeId + attempt + manifestHash`, and every bench message carries `contractHash` and `fixtureId`. A replayed or cross-fixture message is rejected.
- On a single workstation over loopback, TLS adds little. If the bench ever runs on a separate machine, use mutual TLS with a per-fixture certificate instead of the bearer token.

Never reuse a human session or user credential in the bench process (HLD 01 §10).

## 6. Version binding

A campaign can be armed only when these match the approved tuple (HLD 03 §6.2):

| Item | Source of truth |
|---|---|
| Contract version and canonical hash | Control-plane database |
| Fixture ID and revision | Fixture registration |
| Test-controller firmware hash | MCU `HELLO` reply |
| DUT firmware hash | DUT identification reply |
| Calibration record | Latest valid calibration for the fixture |
| Software versions | Git commit of the control plane and bench process, recorded with the campaign |

Any change invalidates the arm state and is recorded in the audit log.

## 7. Researcher authorization and supervised-lab rules

**Recommended for the MVP:** a single local operator session with two roles.

| Role | May |
|---|---|
| Researcher | Create campaigns, arm, start, pause, abort, disarm, read evidence |
| Reviewer (hardware/safety owner) | Approve contract versions and fixture tuples, clear lockouts |

Rules from the PRD (§26) that remain in force:

- No remote arming: arming and lockout clearing are accepted only from the workstation console.
- Clearing a lockout requires confirming that the fixture was physically inspected; the confirmation and the reviewer are recorded.
- Approving a contract requires a second person for any change to safety limits (PRD §28.1).

**ActiveQual decision (2026-11-06):** a shared operator account with a recorded name per action; named accounts wait for remote deployment (§9).

Loopback binding alone does not stop another local process from calling the control plane, so human actions carry two credentials as well:

- The Console's server routes hold an **operator token** (a file with mode 0600, like the bench token, §8) and send it on every researcher request. The control plane rejects researcher endpoints without it. The browser never sees the token.
- Reviewer actions (approving a contract or fixture tuple, clearing a lockout) also need a **reviewer passphrase**, typed in the Console for each action and checked against a hash in the workstation configuration. It guards against a researcher approving their own change by accident, which is the threat the MVP defends against (§2); it is not a defence against a determined local user.

## 8. Secrets and configuration

- Configuration lives in environment variables and a per-workstation config file outside the repository (for example `CHIPCHECK_DECISION_URL`, the control-plane listen address, the database path).
- The bench token is stored in a file readable only by the bench process user (mode 0600) or in the OS keyring, never in the repository or logs.
- Logs and exported evidence bundles must not contain tokens; exports are scanned before release (PRD §26).
- Firmware binaries, schematics, and traces are treated as potentially confidential and kept local by default.

## 9. Future remote deployment (not MVP)

If the control plane later moves off the bench workstation:

- keep the pull model, so no inbound connection reaches the lab network;
- switch bench authentication to mutual TLS;
- add named accounts with project-scoped authorization;
- keep arming and lockout clearing physically local.

## 10. Decisions

**ActiveQual decision (2026-11-06):**

| Decision | Outcome |
|---|---|
| User accounts in the MVP | Shared operator account with a recorded name per action; operator token and reviewer passphrase (§7) |
| Bench authentication | Per-fixture bearer token as in §5; mutual TLS only if the bench moves to another machine |
| Process supervisor | systemd user units on Linux; a Procfile runner on other platforms |
| Control-plane port | `127.0.0.1:8001` |
| Token rotation | Bench and operator tokens rotated per evaluation block and on any suspected exposure |

## 11. Acceptance checklist

- Control plane and Console listen only on loopback; the bench process opens no listening socket.
- A bench token for fixture A cannot claim or submit for fixture B.
- A researcher request without the operator token, and a reviewer action without the passphrase, are rejected and logged.
- A replayed result with a changed manifest hash is rejected with `INTEGRITY_ERROR`.
- Changing any item in §6 invalidates arming.
- Killing each process during an episode leaves the bench in shutdown state.

## 12. Change log

| Date | Change |
|---|---|
| 2026-11-05 | Initial draft |
| 2026-11-06 | §10 decisions recorded; operator token and reviewer passphrase added, since loopback binding alone does not authenticate human actions |
