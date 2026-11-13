# Raspberry Pi interaction simulation

This is an independent software-only demonstration on the backup branch. It models three logical 0–255 controls and a buzzer using two artificial failure regions. These regions and observations are synthetic; no Raspberry Pi, GPIO, electrical measurement, real fault, or safety approval is implied.

From the repository root, install the existing project dependencies and run:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e . scikit-learn
.venv/bin/python -m interaction_demo.app
```

Open http://127.0.0.1:8765. Create a campaign; propose and run batches. TPE receives only completed valid PASS/FAIL results and keeps 25% of each batch for random exploration. Confirm repeats failures and probe changes one coordinate at a time. All consume budget. Export JSON includes requested controls, applied controls and synthetic measurements. Campaigns are stored in `~/.local/share/chipcheck/interaction-demo.sqlite3`; set `CHIPCHECK_DEMO_DB` to change this path.

The execution boundary is `Campaign.run_pending(..., executor=...)`: an executor receives the specification's command JSON and returns a result with matching IDs, applied values, measurements, outcome and quality. The provided UI always uses the simulator. A real adapter, independent reviewed safety checks, approved physical contract, transport, timeouts, reset and physical measurement remain to be designed and validated with the hardware team. Do not connect real hardware to this demo.

Current limits: the logical contract is fixed in code, the results report is a JSON export, boundary probing is manual and conditional, and there is no automatic region clustering, benchmark, hardware interface or claim that adaptive selection outperforms random. The simulated sound numbers are illustrative and not calibrated. Proposals are only generated after the preceding batch has completed. INVALID/ABORTED observations do not train TPE.
