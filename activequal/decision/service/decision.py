"""Candidate selection only. No safety approval, scoring, or instrument access.

Requests carry either a test ``contract`` (v2, preferred) or the console's legacy
``setup`` payload. Both become the same search domain, and the named planner plugin
proposes candidates from it.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from domain import InvalidRequest, domain_from_contract, domain_from_setup, parse_history
from planners import PLANNER_REGISTRY

__all__ = ["InvalidRequest", "propose"]


def propose(request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise InvalidRequest("request must be an object")
    if "contract" in request and "setup" in request:
        raise InvalidRequest("send either contract or setup, not both")
    domain = domain_from_contract(request["contract"]) if "contract" in request \
        else domain_from_setup(request.get("setup"))
    method = str(request.get("method", "tpe")).lower()
    planner = PLANNER_REGISTRY.get(method)
    if planner is None:
        raise InvalidRequest(f"method must be one of: {', '.join(sorted(PLANNER_REGISTRY))}")
    seed = request.get("seed", 42)
    count = request.get("count", 3)
    warmup = request.get("warmupTrials", 8)
    for value in (seed, count, warmup):
        if not isinstance(value, int) or isinstance(value, bool):
            raise InvalidRequest("seed, count, and warmupTrials must be integers")
    if count < 1 or count > 10 or warmup < 1:
        raise InvalidRequest("count must be 1–10 and warmupTrials must be positive")
    history = parse_history(domain, request.get("history", []))
    usable = sum(1 for item in history if item.outcome in {"PASS", "DUT_FAILURE"})
    proposals = planner.propose(domain, history, min(count, domain.budget), seed, {"warmupTrials": warmup})
    return {"source": "decision", "method": method, "setupName": domain.name, "historyUsed": usable,
            "tests": [{"id": item.id, "conditions": item.conditions, "reason": item.reason} for item in proposals]}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/v1/proposals":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 2_000_000:
                raise InvalidRequest("request size must be 1–2000000 bytes")
            request = json.loads(self.rfile.read(size))
            result = propose(request)
            status = 200
        except ValueError as exc:
            result, status = {"error": str(exc)}, 400
        raw = json.dumps(result).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO)
    host = os.environ.get("CHIPCHECK_DECISION_HOST", "127.0.0.1")
    port = int(os.environ.get("CHIPCHECK_DECISION_PORT", "8001"))
    with ThreadingHTTPServer((host, port), Handler) as server:
        logging.info("Decision Service listening on %s:%s", host, port)
        server.serve_forever()
