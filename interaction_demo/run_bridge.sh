#!/usr/bin/env bash
# Laptop side. Usage: interaction_demo/run_bridge.sh <PI_IP> [TOKEN] [PI_PORT]   (token defaults to "demo")
# Starts the demo website on all interfaces and sends campaign runs and rig probes to the Pi agent.
set -euo pipefail
PI_IP="${1:?usage: run_bridge.sh <PI_IP> [TOKEN] [PI_PORT]}"; TOKEN="${2:-demo}"; PI_PORT="${3:-8800}"
cd "$(dirname "$0")/.."
echo "Checking Pi agent at http://$PI_IP:$PI_PORT ..."
curl -fsS --max-time 4 -H "Authorization: Bearer $TOKEN" "http://$PI_IP:$PI_PORT/health" && echo || { echo "Pi agent not reachable (same Wi-Fi? agent running? token matches?)"; exit 1; }
echo "Open on this laptop:  http://127.0.0.1:8767"
for ip in $(ip -4 -o addr show scope global | grep -Ev " (docker|br-|tailscale)" | awk "{print \$4}" | cut -d/ -f1); do echo "Open from your phone: http://$ip:8767"; done
CHIPCHECK_PI_URL="http://$PI_IP:$PI_PORT" CHIPCHECK_PI_TOKEN="$TOKEN" CHIPCHECK_DEMO_HOST=0.0.0.0 exec .venv/bin/python -m interaction_demo.app
