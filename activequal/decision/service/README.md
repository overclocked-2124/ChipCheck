# ChipCheck Decision Service

The Decision Service proposes test conditions using Optuna TPE or GP-BO. Random and Grid are baseline methods. It receives an approved domain and prior measured outcomes from its caller. Only `PASS` and `DUT_FAILURE` results with robustness values train the sampler; invalid experiments and safety aborts are excluded. Proposals are **not approved episodes** and cannot operate hardware.

Run with Python 3.12 or newer, from the repository root:

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"          # add ".[gp]" and --extra-index-url https://download.pytorch.org/whl/cpu for the gp planner
.venv/bin/python -m unittest discover -t . -s activequal -v
.venv/bin/python -m activequal.decision.service.decision
```

## Request shapes and planners

A request carries either a test `contract` (`contractVersion: 2`, preferred) or the console's legacy `setup` payload, never both. Both become one search domain built from the declared controls (`continuous`, `integer`, `duration`, `boolean`, `categorical`). A control may declare `activeWhen`, and while it is inactive it is pinned to its `nominal` value. `forbidden` rules (`{"all": [...]}` predicates) are used only to avoid wasted proposals; Backend and Controller remain the authoritative checks.

Planners live in `planners/` behind `PLANNER_REGISTRY`: `tpe` and `gp` are the adaptive methods, `random` and `grid` are baselines. TPE is multivariate and grouped. `gp` is Gaussian-process Bayesian optimization and needs the optional dependencies (`pip install -r requirements-gp.txt`, which installs the CPU build of torch); without them a `gp` request returns a clear error and the other methods are unaffected. A GP proposal takes roughly 0.1 s to a few seconds with a few dozen points of history. The sampler seed advances with the amount of history, and every executed, invalid or aborted point is remembered so it is never proposed again. To add an algorithm, add a file in `planners/` and register it.

## Endpoint

The local HTTP endpoint is `POST http://127.0.0.1:8001/v1/proposals`. The console's Next.js route sends setup controls and optionally previous measured results. `CHIPCHECK_DECISION_HOST` and `CHIPCHECK_DECISION_PORT` change the listener. Keep it on loopback for the current local deployment.

The current console asks for startup proposals. Adaptive TPE proposals require previous measured `PASS` or `DUT_FAILURE` results and a numeric robustness score from the Backend/Oracle path. This service does not invent those measurements.
