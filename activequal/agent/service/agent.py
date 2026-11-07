"""The Agent Service: runs one campaign's planning loop (HLD 03 §4, HLD 04 §14).

Each ``step()`` looks at the campaign in Backend and does at most one thing: wait for the running
episode, submit the next verification candidate, ask Decision for the next discovery candidate, or
end the campaign. It keeps no state of its own. Where it left off is rebuilt from Backend's
records, so a restart changes nothing. It never approves a candidate, never talks to the bench and
never sees the seeded fault: it hands Decision the contract and measured history only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from activequal.agent.service.plan import PlanConfig, plan_config
from activequal.agent.service.session import (FAIL, PASS, REJECTED, Request, SessionSummary,
                                              verification_session)
from activequal.decision.service.planners.coverage_planner import pairwise_array
from activequal.model.contract import ContractModel, parse_contract
from activequal.model.errors import InvalidRequest
from activequal.service.backend import Backend

log = logging.getLogger("activequal.agent")

Propose = Callable[[dict[str, Any]], dict[str, Any]]

REASON_VERIFICATION = "VERIFICATION"


class AgentError(RuntimeError):
    """The Agent cannot continue and a person has to look (planner misconfiguration, diverged log)."""


@dataclass(frozen=True)
class StepResult:
    kind: str                       # idle | waiting | submitted | completed
    detail: str = ""
    candidate: dict[str, Any] | None = None


class Agent:
    def __init__(self, backend: Backend, campaign_id: str, propose: Propose) -> None:
        self.backend = backend
        self.campaign_id = campaign_id
        self.propose = propose
        self.summaries: list[SessionSummary] = []     # verification sessions seen on the latest step

    # --------------------------------------------------------------------- loop

    def step(self) -> StepResult:
        backend, cid = self.backend, self.campaign_id
        view = backend.get_campaign(cid)
        if view["state"] != "RUNNING":
            return StepResult("idle", f"campaign is {view['state']}")
        if backend.in_flight_count(cid):
            return StepResult("waiting", "an episode is still running")

        loaded = backend.campaign_contract(cid)
        contract = loaded["contract"]
        model = parse_contract(contract, require_oracle=True)
        plan = plan_config(view["plan"], view["budget"]["discovery"], view["budget"]["verification"])
        history = backend.episode_history(cid)

        # Verification sessions come first: each discovery failure is confirmed, minimized and bracketed.
        excluded: list[dict[str, Any]] = []
        self.summaries = []
        used_before = 0
        for trigger in [h for h in history if h["role"] == "discovery" and h["outcome"] == FAIL]:
            session = verification_session(model, trigger["conditions"], plan, max(0, plan.verification_budget - used_before))
            request, summary = self._replay(session, backend.session_log(cid, trigger["episodeId"]), trigger["episodeId"])
            if request is not None:
                return self._submit_verification(request, trigger["episodeId"])
            used_before += summary.episodes_used
            self.summaries.append(summary)
            if summary.confirmed:
                self._record(trigger["episodeId"], summary)
                rule = self._region_rule(model, summary)
                if rule is not None:
                    excluded.append(rule)
        confirmed = [s for s in self.summaries if s.confirmed]
        failure_found = bool(self.summaries)
        if plan.on_confirmed == "stop" and (confirmed or (failure_found and plan.verification_budget == 0)):
            return self._complete("first failure confirmed and minimized" if confirmed
                                  else "failure found; verification budget is 0")

        # Discovery.
        discovery_used = view["budget"]["discoveryUsed"]
        if discovery_used >= plan.discovery_budget:
            return self._complete(f"discovery budget of {plan.discovery_budget} episodes used; "
                                  f"{len(confirmed)} confirmed counterexample(s)")
        recent = [h for h in history if h["role"] == "discovery"][-plan.consecutive_invalid:]
        if len(recent) == plan.consecutive_invalid and all(h["outcome"] == "INVALID_EXPERIMENT" for h in recent):
            return self._complete(f"the last {plan.consecutive_invalid} discovery episodes were invalid: "
                                  "required measurements are repeatedly unavailable")
        if backend.consecutive_rejections(cid) >= plan.max_consecutive_rejections:
            return self._complete(f"planner failure: {plan.max_consecutive_rejections} candidates in a row were rejected")
        return self._propose(view, contract, model, plan, history, excluded)

    # ---------------------------------------------------------------- discovery

    def _propose(self, view: dict[str, Any], contract: dict[str, Any], model: ContractModel, plan: PlanConfig,
                 history: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> StepResult:
        discrete = [len(c.values) for c in model.controls.values() if c.kind in ("boolean", "categorical")]
        coverage_rows = len(pairwise_array(discrete))
        in_init = view["budget"]["discoveryUsed"] < plan.init_episodes(coverage_rows)
        method = "coverage" if in_init else view["planner"]["method"]
        request: dict[str, Any] = {
            "contract": {**contract, "forbidden": [*contract.get("forbidden", []), *excluded]},
            "method": method, "seed": view["seed"], "count": 1,
            "history": self._decision_history(contract, history)}
        for key in ("warmupTrials", "candidates"):
            if key in view["planner"]["config"]:
                request[key] = view["planner"]["config"][key]
        try:
            response = self.propose(request)
        except InvalidRequest as exc:
            raise AgentError(f"Decision refused the request: {exc}") from exc
        tests = response.get("tests", [])
        if not tests:
            return self._complete("no feasible candidate remains for the planner")
        test = tests[0]
        sequence = self.backend.next_planner_sequence(self.campaign_id)
        result = self.backend.submit_candidate(
            self.campaign_id, sequence, test["conditions"], planner_reason=test["reason"],
            reason_code=test.get("reasonCode", "MODEL"))
        return StepResult("submitted", f"{method}: {test['reason']}", result)

    def _decision_history(self, contract: dict[str, Any], history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Measured discovery results train the planner. Everything else is only remembered, so a point is never repeated."""
        from activequal.decision.service.domain import domain_from_contract, parse_history
        entries = [{"outcome": h["outcome"], "conditions": h["conditions"], "robustness": h["robustness"]}
                   if h["role"] == "discovery" else
                   {"outcome": "INVALID_EXPERIMENT", "conditions": h["conditions"]}   # verification replays: remember only
                   for h in history]
        domain = domain_from_contract(contract)
        for rejected in self.backend.rejected_conditions(self.campaign_id):
            try:
                parse_history(domain, [{"outcome": "INVALID_EXPERIMENT", "conditions": rejected["conditions"]}])
            except InvalidRequest:
                continue            # malformed or out-of-domain conditions cannot be proposed anyway
            entries.append({"outcome": "INVALID_EXPERIMENT", "conditions": rejected["conditions"]})
        return entries

    # ------------------------------------------------------------- verification

    @staticmethod
    def _replay(session, log_entries: list[dict[str, Any]], trigger_id: str
                ) -> tuple[Request | None, SessionSummary | None]:
        """Feed the recorded results back into a fresh session. Returns the next request or the finished summary."""
        try:
            request = next(session)
            for entry in log_entries:
                if entry["conditions"] != request.conditions or entry["role"] != request.role:
                    raise AgentError(f"verification log for episode {trigger_id} diverged from the plan at "
                                     f"sequence {entry['sequence']}")
                outcome = entry["outcome"]
                if outcome is None:
                    raise AgentError("a verification episode is unfinished but nothing is in flight")
                request = session.send(outcome if outcome in (PASS, FAIL, REJECTED) else "UNUSABLE")
        except StopIteration as done:
            return None, done.value
        return request, None

    def _submit_verification(self, request: Request, trigger_id: str) -> StepResult:
        sequence = self.backend.next_planner_sequence(self.campaign_id)
        result = self.backend.submit_candidate(
            self.campaign_id, sequence, request.conditions, planner_reason=request.reason,
            reason_code=REASON_VERIFICATION, role=request.role, linked_episode_id=trigger_id,
            repeat_reason=request.reason)
        return StepResult("submitted", request.reason, result)

    def _record(self, trigger_id: str, summary: SessionSummary) -> None:
        self.backend.record_counterexample(
            self.campaign_id, trigger_id,
            {"conditions": summary.minimized, "removed": summary.removed, "kept": summary.kept,
             "necessity": summary.necessity},
            {"intervals": summary.intervals, "budgetExhausted": summary.budget_exhausted},
            summary.reproductions, summary.replays)

    @staticmethod
    def _region_rule(model: ContractModel, summary: SessionSummary) -> dict[str, Any] | None:
        """A rule covering a confirmed failure region, so Decision looks for a distinct one.

        A control constrains the region only where the failure needs it: a bracketed numeric control
        by its interval, a kept control by its value, and a discrete control at nominal that a probe
        showed to be necessary by that nominal value. Controls that minimization removed or that a
        probe found irrelevant leave the region unconstrained.
        """
        atoms: list[dict[str, Any]] = []
        for name, control in model.controls.items():
            if name in summary.intervals:
                atoms.append({"control": name, "gte": summary.intervals[name]["low"]})
                atoms.append({"control": name, "lte": summary.intervals[name]["high"]})
            elif name in summary.kept or summary.necessity.get(name) == "necessary":
                atoms.append({"control": name, "eq": summary.minimized[name]})
        return {"all": atoms} if atoms else None

    # ------------------------------------------------------------------- finish

    def _complete(self, reason: str) -> StepResult:
        self.backend.complete_campaign(self.campaign_id, reason)
        log.info("campaign %s completed: %s", self.campaign_id, reason)
        return StepResult("completed", reason)
