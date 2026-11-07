"""How the Controller talks to the control plane.

``BackendClient`` is the whole surface the bench needs (HLD 05 §7). ``InProcessClient`` calls a
``Backend`` directly, which is how the simulated end-to-end tests and Gate A run; an HTTP client
with the same methods replaces it when the bench runs as its own process.
"""

from __future__ import annotations

from typing import Any, Protocol

from activequal.service.backend import Backend


class BackendClient(Protocol):
    def report_health(self, health: dict[str, Any]) -> None: ...
    def claim(self, controller_instance_id: str) -> dict[str, Any] | None: ...
    def heartbeat(self, lease_id: str, phase: str | None = None) -> dict[str, Any]: ...
    def acknowledge_abort(self, lease_id: str) -> dict[str, Any]: ...
    def submit_result(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class InProcessClient:
    def __init__(self, backend: Backend, fixture_id: str) -> None:
        self.backend = backend
        self.fixture_id = fixture_id

    def report_health(self, health: dict[str, Any]) -> None:
        self.backend.record_bench_health(self.fixture_id, health)

    def claim(self, controller_instance_id: str) -> dict[str, Any] | None:
        return self.backend.claim_episode(self.fixture_id, controller_instance_id)

    def heartbeat(self, lease_id: str, phase: str | None = None) -> dict[str, Any]:
        return self.backend.heartbeat(lease_id, self.fixture_id, phase)

    def acknowledge_abort(self, lease_id: str) -> dict[str, Any]:
        return self.backend.acknowledge_abort(lease_id, self.fixture_id)

    def submit_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.backend.submit_result(payload, self.fixture_id)
