"""The HLD 04 §12 OLED example contract, for tests, demos and the simulator fixture.

The limits are the document's illustrative values, not approved bench limits (HLD 04 §12.1,
HLD 02 §19.2). Call ``oled_example_contract()`` to get a fresh copy that can be edited.
"""

from __future__ import annotations

import copy
from typing import Any

_OLED_EXAMPLE: dict[str, Any] = {
    "contractVersion": 2,
    "setup": {"dut": "esp32s3-oled-demo", "firmwareSha256": "0" * 64, "fixture": "bench-A", "fixtureRev": "A"},
    "controls": {
        "oledRailV": {"type": "continuous", "unit": "V", "min": 3.00, "max": 3.60, "step": 0.01, "nominal": 3.30,
                      "shutdown": 0.0, "slewPerSMax": 0.5, "bind": {"target": "supply.ch2", "action": "setVoltage"}},
        "sensorRailV": {"type": "continuous", "unit": "V", "min": 3.00, "max": 3.60, "step": 0.01, "nominal": 3.30,
                        "shutdown": 0.0, "slewPerSMax": 0.5, "bind": {"target": "supply.ch3", "action": "setVoltage"}},
        "redLed": {"type": "boolean", "nominal": False, "bind": {"target": "dut", "action": "LED RED"}},
        "greenLed": {"type": "boolean", "nominal": False, "bind": {"target": "dut", "action": "LED GREEN"}},
        "workload": {"type": "categorical", "values": ["idle", "oled_refresh", "sensor_read", "flash_write"],
                     "nominal": "idle", "bind": {"target": "dut", "action": "WORKLOAD"}},
        "flashOffsetMs": {"type": "integer", "unit": "ms", "min": 0, "max": 20, "step": 1, "nominal": 0,
                          "activeWhen": {"control": "workload", "eq": "flash_write"},
                          "bind": {"target": "mcu", "action": "flashOffset"}},
        "dwellMs": {"type": "duration", "unit": "ms", "min": 200, "max": 2000, "step": 100, "nominal": 500},
    },
    "forbidden": [{"all": [{"control": "workload", "eq": "flash_write"},
                           {"control": "sensorRailV", "gte": 3.55}]}],
    "observations": {
        "oledLatencyMs": {"unit": "ms", "source": "firmware", "reduction": "max",
                          "requiredWhen": {"control": "workload", "eq": "oled_refresh"}, "uncertainty": 5},
        "maxHeartbeatGapMs": {"unit": "ms", "source": "firmware", "reduction": "max_gap", "required": True,
                              "uncertainty": 10},
        "resetCount": {"unit": "count", "source": "mcu", "reduction": "count", "required": True},
        "measuredOledRailV": {"unit": "V", "source": "instrument", "reduction": "mean", "required": True,
                              "uncertainty": 0.01},
        "measuredDut3v3MinV": {"unit": "V", "source": "instrument", "reduction": "min", "required": True,
                               "uncertainty": 0.01},
    },
    "requirements": [
        {"id": "latency", "metric": "oledLatencyMs", "op": "<=", "limit": 120, "nominal": 31},
        {"id": "heartbeat", "metric": "maxHeartbeatGapMs", "op": "<=", "limit": 500, "nominal": 200},
        {"id": "reset", "metric": "resetCount", "op": "exact", "limit": 0},
        {"id": "dut_3v3_band", "metric": "measuredDut3v3MinV", "op": "band", "lo": 3.135, "hi": 3.465,
         "nominal": 3.30},
    ],
    "validity": [{"metric": "measuredOledRailV", "tracks": "oledRailV", "tolerance": 0.03}],
    "scoring": {"planner": "normalized_min", "verdict": "guard_banded"},
    "safety": {"channels": {"supply.ch2": {"maxA": 0.2, "maxV": 3.6}, "supply.ch3": {"maxA": 0.2, "maxV": 3.6}},
               "maxTempC": 60, "maxEpisodeS": 10},
    "templates": [],
    "campaign": {"budget": 30, "seed": 42, "plan": "default_v1"},
}


def oled_example_contract() -> dict[str, Any]:
    return copy.deepcopy(_OLED_EXAMPLE)
