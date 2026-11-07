"""Shared fixtures for Backend tests: a fully armed campaign on the OLED example contract."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any

from activequal.model.evidence import manifest_hash
from activequal.model.examples import oled_example_contract
from activequal.service.backend import Backend, researcher, reviewer
from activequal.service.ids import FixedClock
from activequal.storage.database import Database

START = datetime(2026, 11, 16, 9, 0, 0, tzinfo=timezone.utc)
CAPABILITIES = ["supply.ch2", "supply.ch3", "dut", "mcu"]
GOOD_HEALTH = {"estopReleased": True, "interlockHealthy": True, "watchdogHealthy": True, "outputsInShutdown": True,
               "adaptersCompatible": True, "tripActive": False, "dutFirmwareSha256": "0" * 64,
               "mcuFirmwareSha256": "m" * 64}
SAM, DANA, ALEX = researcher("sam"), reviewer("dana"), reviewer("alex")

CANDIDATE = {"oledRailV": 3.25, "sensorRailV": 3.30, "redLed": True, "greenLed": False,
             "workload": "oled_refresh", "flashOffsetMs": 0, "dwellMs": 500}


class World:
    def __init__(self, *, contract: dict[str, Any] | None = None, discovery: int = 3, verification: int = 2,
                 arm: bool = True, start: bool = True, planner: str = "tpe") -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.clock = FixedClock(START)
        self.db = Database()
        self.backend = Backend(self.db, self.folder.name, clock=self.clock, software_version="git:test")
        b = self.backend
        created = b.create_contract(contract or oled_example_contract(), SAM)
        self.contract_key, self.contract_version, self.contract_hash = (created["contractId"], created["version"],
                                                                        created["contractHash"])
        b.approve_contract(self.contract_key, 1, DANA)
        b.approve_contract(self.contract_key, 1, ALEX)
        reg = b.register_fixture("bench-A", "A", CAPABILITIES, DANA, approved_mcu_firmware_sha256="m" * 64)
        self.token = reg["token"]
        b.record_calibration("bench-A", {"supply.ch2": {"gain": 1.0, "offset": 0.0, "uncertainty": 0.005}},
                             "Fluke 87V #123", "sam", START + timedelta(days=30), SAM)
        b.record_bench_health("bench-A", dict(GOOD_HEALTH))
        campaign = b.create_campaign(self.contract_key, 1, "bench-A", planner, 42, discovery, verification, SAM)
        self.campaign_id = campaign["id"]
        self.version = campaign["version"]
        if arm:
            self.validate_and_arm()
        if arm and start:
            self.start()

    def validate_and_arm(self) -> None:
        b = self.backend
        view = b.validate_campaign(self.campaign_id, self.version, SAM)
        assert view["state"] == "READY", view
        view = b.arm_campaign(self.campaign_id, view["version"], SAM)
        self.version = view["version"]

    def start(self) -> None:
        self.version = self.backend.start_campaign(self.campaign_id, self.version, SAM)["version"]

    def view(self) -> dict[str, Any]:
        return self.backend.get_campaign(self.campaign_id)

    def submit(self, sequence: int = 0, conditions: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
        return self.backend.submit_candidate(self.campaign_id, sequence, conditions or dict(CANDIDATE),
                                             planner_reason=kw.pop("planner_reason", "test"),
                                             reason_code=kw.pop("reason_code", "BASELINE"), **kw)

    def claim(self) -> dict[str, Any] | None:
        return self.backend.claim_episode("bench-A", "controller-1")

    def walk(self, claim: dict[str, Any], *phases: str) -> None:
        for phase in phases:
            self.backend.heartbeat(claim["leaseId"], "bench-A", phase)

    def payload(self, claim: dict[str, Any], *, measured: dict[str, Any] | None = None, trip: str | None = None,
                settled: bool = True, instrument_fault: bool = False, shutdown: bool = True,
                timeouts: list[str] | None = None, traces: list[dict] | None = None) -> dict[str, Any]:
        requested = claim["requested"]
        values = {"oledLatencyMs": 31.0, "maxHeartbeatGapMs": 200.0, "resetCount": 0.0,
                  "measuredOledRailV": requested["oledRailV"] - 0.002, "measuredDut3v3MinV": 3.30}
        values.update(measured or {})
        body = {"episodeId": claim["episodeId"], "attempt": claim["attempt"], "leaseId": claim["leaseId"],
                "contractHash": claim["contractHash"], "fixtureId": "bench-A", "requested": requested,
                "measured": {k: {"value": v} for k, v in values.items()},
                "quality": {"railSettled": settled, "instrumentFault": instrument_fault, "shutdownConfirmed": shutdown,
                            "timeouts": timeouts or []},
                "events": [{"type": "OUTPUT_ENABLE", "controllerTimeMs": 1203}], "traces": traces or [],
                "safetyTrip": trip}
        body["manifestHash"] = manifest_hash(body)
        return body

    def run_episode(self, sequence: int = 0, conditions: dict[str, Any] | None = None, **payload_kw: Any
                    ) -> dict[str, Any]:
        """Candidate -> claim -> normal phases -> result. Returns the verdict."""
        self.submit(sequence, conditions)
        claim = self.claim()
        assert claim is not None
        self.walk(claim, "PREFLIGHT", "CONFIGURING", "SETTLING", "EXECUTING", "OBSERVING", "SHUTTING_DOWN")
        return self.backend.submit_result(self.payload(claim, **payload_kw), "bench-A")

    def close(self) -> None:
        self.db.close()
        self.folder.cleanup()
