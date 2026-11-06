# ActiveQual HLD 09: Console and Researcher Experience

**Project:** ActiveQual: AI-Driven Adaptive Physical Testing for Embedded Systems  
**Document type:** High-Level Design  
**Status:** Initial draft for team review  
**Depends on:** HLD 03 §22 (what the Console must show), HLD 04 (contract), HLD 05 (APIs), HLD 08 (records)

## 1. Purpose and scope

This document defines the Console's pages and flows: contract review, arming, live execution, failures and verification, evidence, comparison, and the faculty demonstration. It covers what each page shows and which actions it allows, not visual design.

## 2. Current state

The Console today is a five-step setup wizard (`activequal/console/ui/src/components/setup-wizard.tsx`) that previews unapproved candidates through `/api/proposals`. It cannot arm a campaign, stream episodes, show failures, or produce a report. It still sends the legacy setup shape, not contract v2.

## 3. Principles

1. **The Console never decides safety.** It shows what Backend and the bench report and sends researcher requests (HLD 01 §6.3).
2. **Errors are never only in logs.** Every stop, rejection, invalid experiment, and lockout has a visible reason (HLD 03 §22).
3. **Honest language.** Results use the PRD §19.2 vocabulary; "no counterexample found within this budget", never "safe".
4. **Requested and measured values appear side by side.**
5. **Seeded faults are labelled as seeded** wherever a counterexample is shown.

## 4. Navigation

```text
Contracts ── Contract detail (versions, review, approve)
Fixtures  ── Fixture health and calibration
Campaigns ── New campaign ── Arm checklist ── Live campaign ── Counterexample ── Report
Compare   ── Planner comparison across campaigns
```

## 5. Pages

| Page | Shows | Actions |
|---|---|---|
| Contracts | Versions, hash, approval state, reviewer | Create version, request review |
| Contract detail | Controls, forbidden rules, observations, requirements, safety limits, plan; canonical JSON view; diff from the previous version | Approve (reviewer only) |
| Fixture health | E-stop, interlock, watchdog, adapter capabilities, firmware hashes, calibration age | Start a calibration run |
| New campaign | Contract version, fixture, planner method and seed, budgets | Create (`DRAFT`), validate |
| Arm checklist | Each arming condition from HLD 03 §6.2 with pass/fail, wiring confirmation checkbox, expected maximum runtime | Arm (enabled only when all pass) |
| Live campaign | State and allowed actions, current episode and phase, lease owner and heartbeat, requested vs measured values, outcome timeline, robustness history, budget used per pool, rejection and invalid reasons, safety status | Start, pause, resume, abort, disarm; a prominent "Stop and de-energize" that maps to abort plus the physical E-stop instruction |
| Failure region | Scatter of the continuous control against robustness, one series per discrete combination; observed pass, fail, invalid, inconclusive | Filter by discrete state |
| Verification | Confirm replays, each minimization step and its result, bracket probes and the reported interval with its resolution | None; read-only progress |
| Counterexample | Original and minimized conditions, interval, violated requirement and margin, reproduction rate with interval, traces, seeded/natural label | Replay as a new linked episode (re-runs all safety checks) |
| Lockout | Cause, preserved measurements, physical checklist | Clear lockout (reviewer, workstation only; HLD 07 §7) |
| Report | Campaign summary in PRD §19.2 language, counts by outcome, budget use, counterexamples, limitations | Export evidence bundle (HLD 08 §6) |
| Compare | Kaplan–Meier curves of episodes to first failure per planner, discovery at 30 and 50, log-rank result (HLD 06) | Select campaigns |

## 6. States every page must handle

| State | Behavior |
|---|---|
| Empty | Explain what to create first |
| Loading | Skeletons, no stale numbers presented as current |
| Disconnected from control plane | Banner; physical state is unknown to the Console, so say so; do not imply the bench stopped |
| Bench unhealthy | Arm disabled with the failing condition named |
| Stale version | Refresh and show what changed (HLD 03 §20) |
| Locked out | Every page shows the lockout banner and links to the Lockout page |

## 7. Live updates

**Recommended:** the Console subscribes to `GET /v1/campaigns/{id}/events` (server-sent events) through its own server route. It re-reads the campaign on reconnect, so a missed event never leaves the display wrong.

## 8. Faculty demonstration flow

Adapted from PRD §18.1, using the evidence from HLD 06:

1. Show the contract and limits, and state that the planner cannot change them.
2. Explain the interaction space and why one voltage sweep is not the point.
3. Run the disclosed seeded benchmark. **Recommended:** the wide-island demo configuration at a 50-episode budget, where TPE found the failure within 50 episodes in about 99% of simulated campaigns; on the narrow island at a 30-episode budget, TPE missed in about 60% of runs and GP-BO in about 40%.
4. Show verification: replays, minimization, the bracketed interval.
5. Show the comparison against random and the honest limits, including that adaptive search does not beat random on a fault with no measurable precursor.

The demo shows the real seed and run log; a recorded run is a labelled fallback only.

## 9. Open decisions

| Decision | Recommended direction |
|---|---|
| Contract editing | Form for common fields plus a validated JSON editor; approval always on the canonical JSON |
| Charting | Server-computed series rendered client-side; no client-side statistics |
| Access from other machines | Not in the MVP (HLD 07) |

## 10. Acceptance checklist

- Every HLD 03 §22 item is visible on the Live campaign page.
- A researcher can find why any campaign stopped without opening a log.
- The Arm button cannot be enabled while any arming condition fails.
- Disconnecting the control plane never shows the bench as stopped or safe.

## 11. Change log

| Date | Change |
|---|---|
| 2026-11-05 | Initial draft |
