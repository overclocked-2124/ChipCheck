# ChipCheck Console screenshots

Viewport-size captures (1440x900 at 2x, not full page; mobile 390x844 at 3x) of the ChipCheck Research Console
running against the simulated OLED bench with dummy data: four finished campaigns (TPE seeds 42 and 11, random
seeds 7 and 12) on one approved contract and fixture `bench-A`. The ESP32 timing dashboard (`/ahft`, PRD Part II)
is not part of these shots.

## desktop/
| File | What it shows |
|---|---|
| 01-campaigns-list | Campaign list at the start of the session |
| 02-new-campaign-form, 03-new-campaign-form-budget | New campaign: contract, version, fixture, planner, budgets |
| 04-campaign-draft | Campaign in DRAFT, before validation |
| 05-campaign-ready-arming-checklist, 06-campaign-ready-lower | READY state with the arming checklist (pending items block arming) |
| 07-campaign-armed | ARMED, waiting for start |
| 08-campaign-running-live, 09-campaign-running-timeline | RUNNING: actions, budget progress, bench health, live outcome timeline |
| 10-campaign-completed-top, 11-campaign-completed-timeline, 12-campaign-event-log | COMPLETED campaign, outcome timeline, event log |
| 13-results-top .. 16-results-verification-steps | Results: counterexample (seeded), original vs minimised conditions, failure interval, verification steps |
| 17-episode-failing-top, 18-episode-failing-evidence | Failing episode: requested conditions, planner and safety decision, measured values, requirements, bench quality, lease |
| 19-episode-passing-top, 20-episode-passing-evidence, 20b-episode-invalid-top | Passing and invalid episodes |
| 21-manual-candidate | "Pick a test yourself": manual conditions checked by the safety rules |
| 22-contracts-list, 23-25 contract-detail-* | Approved contract: header, rules and evidence, canonical JSON |
| 26-fixtures-list, 27-28 fixture-bench-a-* | Fixture health, calibration |
| 29-campaigns-list-four | Campaign list with four campaigns |
| 30-compare-selected .. 32-compare-statistics | Planner comparison: episodes to first confirmed failure, curves, log-rank statistics |

## mobile/
Campaigns list, finished campaign, new campaign form, contracts list, compare.
