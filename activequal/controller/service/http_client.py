"""HTTP implementation of ``BackendClient`` for the bench process (HLD 05 §7).

The bench always initiates (HLD 01 §8.1). Errors come back as the same ``BackendError`` the
in-process client raises, so the Controller behaves identically over either. A control plane that
cannot be reached becomes ``UNAVAILABLE``: the Controller keeps the evidence in its spool.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from activequal.service.errors import HTTP_STATUS, BackendError

TIMEOUT_S = 10.0       # HLD 05 §11 control-plane request timeout


class HttpBackendClient:
    def __init__(self, base_url: str, token: str, timeout_s: float = TIMEOUT_S) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_s = timeout_s

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any] | None]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base_url + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read()
                return response.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as exc:
            try:
                error = json.loads(exc.read())["error"]
                code = error["code"] if error["code"] in HTTP_STATUS else "UNAVAILABLE"
                raise BackendError(code, error["message"], error.get("details")) from None
            except (ValueError, KeyError, TypeError):
                raise BackendError("UNAVAILABLE", f"control plane answered HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise BackendError("UNAVAILABLE", f"control plane unreachable: {exc}") from None

    def report_health(self, health: dict[str, Any]) -> None:
        self._call("POST", "/v1/bench/health", health)

    def claim(self, controller_instance_id: str) -> dict[str, Any] | None:
        status, body = self._call("POST", "/v1/bench/claim", {"controllerInstanceId": controller_instance_id})
        return None if status == 204 else body

    def heartbeat(self, lease_id: str, phase: str | None = None) -> dict[str, Any]:
        _, body = self._call("POST", f"/v1/bench/leases/{lease_id}:heartbeat", {"phase": phase} if phase else {})
        return body or {}

    def acknowledge_abort(self, lease_id: str) -> dict[str, Any]:
        _, body = self._call("POST", f"/v1/bench/leases/{lease_id}:abort-ack", {})
        return body or {}

    def submit_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        _, body = self._call("POST", f"/v1/bench/episodes/{payload['episodeId']}/results", payload)
        return body or {}
