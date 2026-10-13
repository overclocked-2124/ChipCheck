# ChipCheck Decision Service

The Decision Service proposes test conditions using Optuna TPE. Random and Grid are baseline methods. It receives an approved domain and prior measured outcomes from its caller. Only `PASS` and `DUT_FAILURE` results with robustness values train the sampler; invalid experiments and safety aborts are excluded. Proposals are **not approved episodes** and cannot operate hardware.

Run with Python 3.12 or newer:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python decision.py
```

The local HTTP endpoint is `POST http://127.0.0.1:8001/v1/proposals`. The BFF sends setup controls and optionally previous measured results. `CHIPCHECK_DECISION_HOST` and `CHIPCHECK_DECISION_PORT` change the listener. Keep it on loopback for the current local deployment.

The current console asks for startup proposals. Adaptive TPE proposals require previous measured `PASS` or `DUT_FAILURE` results and a numeric robustness score from the Backend/Oracle path. This service does not invent those measurements.
