# Raspberry Pi interaction simulation

This is a software-only demonstration using the existing Decision planner with a separate demo campaign backend. It models three logical 0–255 controls and a buzzer using two artificial failure regions. These regions and observations are synthetic; no Raspberry Pi, GPIO, electrical measurement, real fault, or safety approval is implied.

From the repository root, install the existing project dependencies and run:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e . scikit-learn
.venv/bin/python -m interaction_demo.app
```

Open http://127.0.0.1:8767. Create a campaign; propose and run batches. Random and TPE proposals use the existing ActiveQual Decision service in-process. TPE receives only completed valid PASS/FAIL observations, mapped to binary robustness scores. The random-forest planner remains specific to this demo. Confirm repeats failures and probe changes one coordinate at a time. All consume budget. Export JSON includes requested controls, applied controls and synthetic measurements. Campaigns are stored in `~/.local/share/chipcheck/interaction-demo.sqlite3`; set `CHIPCHECK_DEMO_DB` to change this path.

The execution boundary is `Campaign.run_pending(..., executor=...)`: an executor receives the specification's command JSON and returns a result with matching IDs, applied values, measurements, outcome and quality. The provided UI always uses the simulator. A real adapter, independent reviewed safety checks, approved physical contract, transport, timeouts, reset and physical measurement remain to be designed and validated with the hardware team. Do not connect real hardware to this demo.

The existing ActiveQual campaign Backend, Agent, Controller and Oracle are not wired into this demo; the demo server owns campaign state and simulated verdicts. The Decision contract is a logical simulation contract, not an approved hardware contract.

Current limits: the logical contract is fixed in code, the results report is a JSON export, boundary probing is manual and conditional, and there is no automatic region clustering, benchmark, hardware interface or claim that adaptive selection outperforms random. The simulated sound numbers are illustrative and not calibrated. Proposals are only generated after the preceding batch has completed. INVALID/ABORTED observations do not train TPE.

## Real Raspberry Pi over a hotspot

The laptop runs the planner and this server; the Pi runs `pi_agent.py` and applies each command.

1. Laptop hotspot (Linux): `nmcli device wifi hotspot ifname wlp2s0 ssid chipcheck password 'choose-a-password'` (use your Wi-Fi interface name from `nmcli device`). The laptop is then `10.42.0.1`.
2. Join the Pi to that Wi-Fi, copy `interaction_demo/pi_agent.py` to it, and run `python3 pi_agent.py` (add `--fake` to test the link without GPIO). Defaults: LEDs on BCM 18, 13, 19; sound sensor output on BCM via --sensor N (none by default: LEDs are real, the buzzer verdict is simulated until a sensor is wired); port 8800.
3. On the laptop: `CHIPCHECK_PI_URL=http://<pi-ip>:8800 CHIPCHECK_PI_TOKEN=demo CHIPCHECK_DEMO_HOST=0.0.0.0 .venv/bin/python -m interaction_demo.app`. The startup line says which executor is in use. Campaign runs and the bench rig probes both go to the Pi.

The Pi forces all duties to 0 on start, on error and on exit. If the Pi is unreachable the experiment is recorded ABORTED and does not train the planner. This is not a reviewed safety design; do not connect anything beyond LEDs with series resistors and a sound sensor.
