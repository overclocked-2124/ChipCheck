"""A full simulated stack: Backend + Agent + Decision + Controller + simulated bench."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from activequal.adapter.service.simulator import FaultInjection, SimulatedBenchAdapter
from activequal.agent.service.agent import Agent, StepResult
from activequal.controller.service.client import InProcessClient
from activequal.controller.service.controller import Controller
from activequal.controller.service.spool import Spool
from activequal.decision.service.decision import propose
from activequal.model.examples import oled_example_contract
from activequal.service.tests.support import World


class Rig:
    def __init__(self, profile: str = "B1w", *, discovery: int = 50, verification: int = 24, planner: str = "tpe",
                 contract: dict[str, Any] | None = None, fault: FaultInjection | None = None, noise_seed: int = 3,
                 sigma_ms: float = 2.5, planner_config: dict[str, Any] | None = None, plan: Any = None) -> None:
        if plan is not None:
            contract = dict(contract or oled_example_contract())
            contract["campaign"] = {**contract["campaign"], "plan": plan}
        self.world = World(contract=contract, discovery=discovery, verification=verification, planner=planner)
        if planner_config is not None:
            with self.world.db.transaction() as conn:
                conn.execute("UPDATE campaigns SET planner_config_json = ? WHERE id = ?",
                             (json.dumps(planner_config), self.world.campaign_id))
        self.folder = tempfile.TemporaryDirectory()
        self.adapter = SimulatedBenchAdapter(profile, noise_seed=noise_seed, latency_sigma_ms=sigma_ms, fault=fault)
        self.controller = Controller(InProcessClient(self.world.backend, "bench-A"), self.adapter,
                                     Spool(Path(self.folder.name) / "spool"), "bench-A", heartbeat_interval_s=0.05)
        self.agent = Agent(self.world.backend, self.world.campaign_id, propose)
        self.steps: list[StepResult] = []

    @property
    def backend(self):
        return self.world.backend

    def run(self, max_steps: int = 400) -> list[StepResult]:
        for _ in range(max_steps):
            result = self.agent.step()
            self.steps.append(result)
            if result.kind in ("completed", "idle"):
                return self.steps
            report = self.controller.run_once()
            assert report is not None or result.kind != "submitted" or result.candidate["state"] == "REJECTED", result
        raise AssertionError("campaign did not finish")

    def close(self) -> None:
        self.world.close()
        self.folder.cleanup()
