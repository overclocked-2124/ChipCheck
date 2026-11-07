"""Background loop that drives every RUNNING campaign's Agent and sweeps expired leases.

One thread, one Agent step per campaign per tick. An Agent that raises is logged and skipped for
that tick; it never takes the control plane down. The server has one worker, so there is exactly one
Agent loop per campaign (HLD 10 §5.3).
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from activequal.agent.service.agent import Agent
from activequal.service.backend import Backend
from activequal.service.queries import running_campaign_ids

log = logging.getLogger("activequal.runner")


class AgentRunner:
    def __init__(self, backend: Backend, propose: Callable[[dict[str, Any]], dict[str, Any]],
                 interval_s: float = 0.5) -> None:
        self.backend, self.propose, self.interval_s = backend, propose, interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._agents: dict[str, Agent] = {}
        self.errors: dict[str, str] = {}      # campaign id -> last Agent error, shown in the Console

    def tick(self) -> int:
        """One pass over the running campaigns. Returns how many Agent steps submitted work."""
        submitted = 0
        try:
            self.backend.expire_leases()
        except Exception:
            log.exception("lease sweep failed")
        for campaign_id in running_campaign_ids(self.backend):
            agent = self._agents.setdefault(campaign_id, Agent(self.backend, campaign_id, self.propose))
            try:
                result = agent.step()
                self.errors.pop(campaign_id, None)
                submitted += result.kind == "submitted"
            except Exception as exc:
                self.errors[campaign_id] = f"{type(exc).__name__}: {exc}"
                log.exception("agent step failed for campaign %s", campaign_id)
        return submitted

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="agent-runner", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            self.tick()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
