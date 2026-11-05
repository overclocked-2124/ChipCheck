# ActiveQual HLD 06: Adaptive Search and Research Evaluation

**Project:** ActiveQual: AI-Driven Adaptive Physical Testing for Embedded Systems  
**Document type:** High-Level Design  
**Status:** Initial draft for team review  
**Depends on:** HLD 01, HLD 03, HLD 04 (contract, robustness, phase plan), HLD 05

## 1. Purpose

This document defines how ActiveQual selects experiments and how planners are compared fairly. It records the simulation evidence gathered so far and turns it into recommendations for the planner set, the campaign plan, benchmark sizing, the primary metric, and sample sizes.

**All evidence here is from simulated benchmarks, not hardware.** It shows how the pipeline and the planners behave on failure shapes we designed; it does not show how real devices fail.

## 2. Planner interface and current planners

The common interface is `propose(domain, history, count, seed, config) -> candidates with reasons` (`activequal/decision/service/planners/base.py`). Planners are stateless: the Agent supplies the full history on every call, and per-call sampler seeds are a hash of the campaign seed and the history length.

| Planner | Role | Status |
|---|---|---|
| `random` | Baseline included in every comparison | Built |
| `grid` | Baseline for small spaces (at most 10,000 points) | Built |
| `tpe` | Multivariate, grouped Optuna TPE | Built; adaptive method, no heavy dependencies |
| `gp` | Optuna GP-BO with bounded asks and a random fallback | Built; adaptive method, needs the optional torch dependency |
| coverage | Pairwise covering array plus space-filling voltages | Evaluated as an Agent-level phase; not a planner yet |

**ActiveQual decision (HLD 01, decision 12):** multivariate TPE and GP-BO are the adaptive methods, random the baseline. The evidence in §3 supports keeping both: neither dominates the other.

Inputs never include the seeded fault trigger. Only `PASS` and `DUT_FAILURE` train a planner; invalid and aborted points are remembered so they are never proposed again (HLD 03 §5).

## 3. Planner comparison

Campaigns were driven through the real `propose()` API exactly as the Agent will call it: one candidate per call, history fed back, guard-banded verdicts, Option A robustness. Discovery is the first guard-banded failure.

Benchmarks (one OLED rail at 0.01 V steps, red and green LED, five workloads; 1,220 points):

| ID | Failure | Failing points |
|---|---|---|
| B1a | Gradient island around 3.25 V with a latency precursor that is partly visible in wrong LED states | about 5 voltages in the target state |
| B1b | Same island, precursor visible only in the target LED state | about 5 |
| B1w | Wider island | about 11 |
| B2 | Cliff: reset with no precursor, at 3.15–3.18 V, red on, sensor read | 8 points |

Discovery within 30 and 50 episodes (500 campaigns per cell for random and TPE; 120 for GP-BO for GP-BO):

| Benchmark | Random | TPE | GP-BO |
|---|---|---|---|
| B1a | 11% / 18% | 39% / 72% | **62% / 86%** |
| B1b | 11% / 18% | 35% / 65% | 28% / 41% |
| B1w | 25% / 39% | 83% / 99% | **91% / 98%** |
| B2 | 17% / 29% | 14% / 20% | 15% / 22% |

Findings:

1. **TPE beats random by a wide margin when a measurable precursor exists** (all three B1 variants, log-rank p < 0.0001).
2. **On the cliff fault, TPE is significantly worse than random** (log-rank p = 0.004). With no gradient, TPE concentrates on regions that look good and stops exploring. Adaptive search is not a general improvement; the research claim must be limited to failures with a measurable precursor.
3. **GP-BO and TPE each win somewhere.** GP-BO was significantly better than TPE on B1a and B1w (log-rank p < 0.001), where a partial precursor gives the model a gradient across states. It was significantly worse on B1b (p = 0.0001), where the precursor appears only in the target state. On the cliff it was no different from TPE (p = 0.64) or random (p = 0.19). GP-BO also costs a large optional dependency and 0.1 to a few seconds per proposal; TPE costs milliseconds.
4. Random's measured discovery matches the exact calculation for every benchmark (for example B2: 17% measured, 18.2% expected), which validates the simulator and the seed handling.

## 4. Campaign plan evidence

The plan ratified in HLD 04 §14 included a coverage phase and forced exploration. Both were tested (500 campaigns per cell; p is log-rank against plain TPE):

| Benchmark | TPE | TPE + forced exploration every 5th | Coverage then TPE |
|---|---|---|---|
| B1a | 39% | 35% (p = 0.09) | 46% (p = 0.20) |
| B1b | 35% | 36% (p = 0.99) | **25% (p = 0.004)** |
| B1w | 83% | **79% (p = 0.046)** | 90% (p = 0.17) |
| B2 | 14% | 15% (p = 0.19) | 11% (p = 0.72) |

Discovery within 30 episodes.

**Recommended:**

- Remove forced exploration: it never helped and hurt once.
- Make the coverage phase an optional setting, off by default: small non-significant gains on two benchmarks, a significant loss on one. Its fixed voltages (nominal, corners, spread points) bias the early model away from narrow windows.
- Keep any coverage or exploration setting identical across the planners being compared, and pre-register it.

## 5. Benchmark sizing

How wide must a seeded island be? TPE and random across island widths and measurement noise (300 campaigns per cell, discovery within 30 / 50 episodes):

| Failing voltages | TPE, σ = 2.5 ms | TPE, σ = 10 ms | Random |
|---:|---|---|---|
| 5 | 39% / 71% | 40% / 70% | 10–12% / 16–19% |
| 7 | 59% / 87% | 57% / 86% | 16–17% / 24–26% |
| 9 | 72% / 96% | 70% / 96% | 20–22% / 31–34% |
| 11 | 83% / 99% | 82% / 98% | 25–27% / 38–39% |
| 15 | 96% / 100% | 92% / 99% | 33–34% / 48–49% |

- The PRD's demo gate (at least 95% discovery within 30 episodes, PRD §17.6) needs about 15 failing voltages. At a 50-episode budget about 9 are enough.
- Noise had little effect on discovery here, but the guard band was held at U = 5 ms while noise varied, so the σ = 10 ms rows are optimistic: in practice U must scale with σ (§6), which widens the inconclusive band.

**Recommended:** a wide disclosed island at a 50-episode budget for the demonstration; narrow islands and the cliff for research comparisons.

## 6. Guard band trade-off

For a `<=` requirement with limit L and Gaussian measurement noise σ (exact calculation):

| σ | U | False failure, true value 115 ms | Inconclusive at 115 ms | Expected false failures per 50 passing episodes near the limit |
|---:|---:|---:|---:|---:|
| 2.5 | 0 | 2.3% | 0% | 1.02 |
| 2.5 | 5 | 0.0% | 50% | 0.01 |
| 5 | 0 | 15.9% | 0% | 2.67 |
| 5 | 10 | 0.1% | 84% | 0.04 |
| 10 | 0 | 30.9% | 0% | 6.06 |
| 10 | 20 | 0.6% | 93% | 0.11 |

Without a guard band, noise near the limit produces false `DUT_FAILURE`s in most campaigns. **Recommended:** U = 2σ from calibration. If measured σ is large (around 10 ms against a 120 ms limit), the inconclusive band covers 100–140 ms, and the requirement or the observation method must be reconsidered (kill criterion K4, HLD 10).

## 7. Verification phase evidence

The HLD 04 §14 verification phase was simulated on discovered failures (2,000 per row; truth is the set of voltages with at least 50% failure probability):

| Setting | Confirmed | Red LED found necessary | Green LED (at nominal) found necessary | Interval exact | Episodes median / p90 |
|---|---:|---:|---:|---:|---|
| Single-episode steps, budget 16, narrow island | 98% | 100% | 0% | 88% | 12 / 13 |
| Plus necessity probes | 99% | 100% | **100%** | 88% | 13 / 14 |
| Majority of 3 per step, budget 40 | 98% | 100% | 0% | 98% | 22 / 24 |
| Single, σ = 10 ms | 91% | 100% | 0% | 29% | 12 / 14 |
| Wide island, budget 16 | 99% | 100% | 0% | 92% (72% ran out of budget) | 16 / 16 |
| Wide island, budget 20 | — | — | — | 91% (0% ran out) | 17 / 18 |

- Minimizing toward nominal never shows that a condition already at its nominal value is necessary. One **necessity probe** per such discrete control fixes this for about one extra episode.
- Single-episode decisions are enough: their 90th-percentile edge error is one step (10 mV) at every noise level tested, and majority voting roughly doubles the cost without reducing that error under noise.
- The verification budget must cover wider windows. **Recommended:** 24 episodes.

## 8. Primary metric and sample size

**Recommended:** the primary metric is episodes to the first confirmed failure within the discovery budget, compared with a log-rank test on Kaplan–Meier curves censored at the budget. Discovery rate at 30 and 50 episodes is secondary (it is the same curve read at the budget).

Statistical power, TPE vs random, at α = 0.05 (bootstrap from the simulated campaigns):

| Benchmark | Budget | n = 10 | n = 20 | n = 30 | n = 50 |
|---|---:|---|---|---|---|
| B1a | 30 | 12% / 28% | 41% / 53% | 64% / 74% | 86% / 89% |
| B1a | 50 | 48% / 65% | 94% / 95% | 99% / 99% | 100% / 100% |
| B1b | 50 | 38% / 57% | 79% / 85% | 96% / 98% | 100% / 100% |
| B1w | 30 | 61% / 78% | 94% / 97% | 100% / 99% | 100% / 100% |
| B2 | 50 | 1% / 5% | 4% / 7% | 9% / 14% | 13% / 17% |

Each cell is discovery-rate test / log-rank. Log-rank was more powerful in every cell. The budget matters as much as the sample size.

**Recommended:** budget 50 for the discovery pool and 20 campaigns per planner per benchmark on hardware. That gives about 95% power on the narrow island and costs roughly 3–5 hours of bench time per comparison at 6–10 s per episode, including verification.

## 9. Pre-registration checklist

Before any final campaign, freeze and record:

- benchmark definitions and seeded fault constants (held by someone outside the algorithm work);
- planners, their settings, and any coverage setting;
- discovery and verification budgets;
- primary and secondary metrics and the analysis code;
- number of campaigns per cell and the seed list;
- exclusion rules for invalid campaigns.

No planner tuning on held-out benchmarks after results are seen (PRD §21.7).

## 10. Threats to validity

- **Simulation is not hardware.** The benchmarks are our own designs. The precursor shapes, the noise model, and the latency physics are assumptions to be checked against the thin hardware slice (HLD 10, WP5).
- **The precursor assumption decides the result.** Adaptive search wins only when a measurable precursor exists; on hardware the real failure may be a cliff.
- **The simulated B2** adds a red-LED condition that the handoff's B2 description does not include.
- **The guard band in §5** was fixed at 5 ms while noise varied.
- **GP-BO results were sensitive to the harness and to seed handling.** An earlier analysis concluded GP-BO never beat TPE; after the seed fix the result reversed on two benchmarks. Treat planner rankings as provisional until repeated on hardware.
- **Earlier numbers are superseded:** results reported before 2026-11-05 used a harness that hid GP starvation, or campaigns whose random streams overlapped between nearby seeds. Only the numbers in this document should be used.

## 11. Open decisions

| Decision | Recommended direction |
|---|---|
| Default adaptive method for the demo and for hardware campaigns | Run both TPE and GP-BO in comparisons; neither dominates (§3). Pick the demo planner after the thin hardware slice shows which failure shape is realistic |
| Coverage phase and forced exploration | Coverage optional and off by default; remove forced exploration (§4) |
| Primary metric | Log-rank on episodes to first confirmed failure (§8) |
| Demo benchmark | Wide disclosed island at a 50-episode budget (§5) |
| Verification budget and necessity probes | 24 episodes with probes (§7) |
| Benchmark harness | Move the evaluation harness into the repository as the simulator adapter and benchmark CLI (HLD 10, WP3) |

## 12. Change log

| Date | Change |
|---|---|
| 2026-11-05 | Initial draft with simulation evidence |
