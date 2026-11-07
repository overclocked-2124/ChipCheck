"""A complete simulated ActiveQual stack in one process: Backend, Agent, Decision, Controller, simulated bench.

Used by the parity check (WP8), the demo script and the end-to-end gate. It runs the same code paths the real
deployment does, with an in-memory database and the simulator adapter in place of hardware. Nothing here
shortcuts a safety or approval step: contracts are approved by two reviewers, the campaign is validated, armed
and started through the normal transitions.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from activequal.adapter.service.simulator import FaultInjection, SimulatedBenchAdapter
from activequal.agent.service.agent import Agent, StepResult
from activequal.controller.service.client import InProcessClient
from activequal.controller.service.controller import Controller
from activequal.controller.service.spool import Spool
from activequal.decision.service.decision import propose
from activequal.model.examples import oled_example_contract
from activequal.service.backend import Backend, researcher, reviewer
from activequal.service.ids import FixedClock
from activequal.storage.database import Database

CAPABILITIES = ["supply.ch2", "supply.ch3", "dut", "mcu"]
DUT_FIRMWARE = "0" * 64
MCU_FIRMWARE = "m" * 64
START = datetime(2026, 11, 16, 9, 0, 0, tzinfo=timezone.utc)
SAM, DANA, ALEX = researcher("sam"), reviewer("dana"), reviewer("alex")


class SimulatedStack:
    def __init__(self, profile: str = "B1w", *, planner: str = "tpe", seed: int = 42, noise_seed: int = 0,
                 discovery: int = 50, verification: int = 24, contract: dict[str, Any] | None = None,
                 plan: Any = None, planner_config: dict[str, Any] | None = None, sigma_ms: float = 2.5,
                 fault: FaultInjection | None = None) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.clock = FixedClock(START)
        self.db = Database()
        self.backend = Backend(self.db, Path(self._folder.name) / "traces", clock=self.clock, software_version="sim")
        contract = contract or oled_example_contract()
        if plan is not None:
            contract["campaign"] = {**contract["campaign"], "plan": plan}
        b = self.backend
        created = b.create_contract(contract, SAM)
        self.contract_key = created["contractId"]
        b.approve_contract(self.contract_key, 1, DANA)
        b.approve_contract(self.contract_key, 1, ALEX)
        self.token = b.register_fixture("bench-A", "A", CAPABILITIES, DANA, approved_mcu_firmware_sha256=MCU_FIRMWARE)["token"]
        b.record_calibration("bench-A", {"supply.ch2": {"gain": 1.0, "offset": 0.0, "uncertainty": 0.005}},
                             "simulated meter", "sim", START + timedelta(days=365), SAM)
        self.adapter = SimulatedBenchAdapter(profile, noise_seed=noise_seed, latency_sigma_ms=sigma_ms, fault=fault,
                                             dut_firmware_sha256=DUT_FIRMWARE, mcu_firmware_sha256=MCU_FIRMWARE)
        self.controller = Controller(InProcessClient(b, "bench-A"), self.adapter, Spool(Path(self._folder.name) / "spool"),
                                     "bench-A", heartbeat_interval_s=0.05)
        self.controller.report_health()
        campaign = b.create_campaign(self.contract_key, 1, "bench-A", planner, seed, discovery, verification, SAM, planner_config)
        self.campaign_id = campaign["id"]
        view = b.validate_campaign(self.campaign_id, campaign["version"], SAM)
        if view["state"] != "READY":
            raise RuntimeError(f"campaign did not validate: {view['reasons']}")
        view = b.arm_campaign(self.campaign_id, view["version"], SAM)
        b.start_campaign(self.campaign_id, view["version"], SAM)
        self.agent = Agent(b, self.campaign_id, propose)
        self.steps: list[StepResult] = []

    def run(self, max_steps: int = 1000) -> list[StepResult]:
        """Alternate Agent steps and bench runs until the campaign leaves RUNNING."""
        for _ in range(max_steps):
            result = self.agent.step()
            self.steps.append(result)
            if result.kind in ("completed", "idle"):
                return self.steps
            self.controller.run_once()
        raise RuntimeError("campaign did not finish within the step limit")

    def episodes_to_first_failure(self) -> int | None:
        """1-based index of the first discovery episode with a DUT_FAILURE, or None (HLD 06 primary metric)."""
        discovery = [h for h in self.backend.episode_history(self.campaign_id) if h["role"] == "discovery"]
        for index, episode in enumerate(discovery, start=1):
            if episode["outcome"] == "DUT_FAILURE":
                return index
        return None

    def close(self) -> None:
        self.db.close()
        self._folder.cleanup()

    def __enter__(self) -> "SimulatedStack":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
