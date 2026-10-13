"""Candidate selection only. No safety approval, scoring, or instrument access."""

from __future__ import annotations

import json
import logging
import math
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import optuna

optuna.logging.set_verbosity(optuna.logging.WARNING)


class InvalidRequest(ValueError):
    pass


def _number(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequest(f"{name} must be a number") from exc
    if not math.isfinite(result):
        raise InvalidRequest(f"{name} must be finite")
    return result


def _options(value: Any, name: str, allowed: set[str] | None = None) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > 20:
        raise InvalidRequest(f"{name} must have 1–20 options")
    result = [str(item).strip().lower() for item in value]
    if any(not item or len(item) > 60 for item in result) or len(set(result)) != len(result):
        raise InvalidRequest(f"{name} contains empty or duplicate options")
    if allowed and any(item not in allowed for item in result):
        raise InvalidRequest(f"{name} has an unsupported option")
    return result


def _domain(setup: dict[str, Any]) -> tuple[dict[str, optuna.distributions.BaseDistribution], dict[str, Any]]:
    if not isinstance(setup, dict) or not str(setup.get("name", "")).strip():
        raise InvalidRequest("setup.name is required")
    if str(setup.get("forbiddenCombinations", "")).strip():
        raise InvalidRequest("free-text forbidden combinations cannot be enforced by Decision; use a reviewed structured contract")
    safety = setup.get("safety")
    if not isinstance(safety, dict):
        raise InvalidRequest("setup.safety is required")
    ceiling = _number(safety.get("maximumVolts"), "safety.maximumVolts")
    additional = setup.get("additionalRails", [])
    if not isinstance(additional, list) or len(additional) > 1:
        raise InvalidRequest("at most one additional sensor rail is supported")
    rails = [("railVolts", setup.get("rail"))] + [("sensorRailVolts", item) for item in additional]
    rail_specs = {}
    for parameter, rail in rails:
        if not isinstance(rail, dict) or not str(rail.get("name", "")).strip():
            raise InvalidRequest(f"{parameter} requires a rail name")
        low = _number(rail.get("minimumVolts"), f"{parameter}.minimumVolts")
        high = _number(rail.get("maximumVolts"), f"{parameter}.maximumVolts")
        step = _number(rail.get("stepVolts"), f"{parameter}.stepVolts")
        if low < 0 or high <= low or step <= 0 or step > high - low:
            raise InvalidRequest(f"{parameter} range or step is invalid")
        if high > ceiling:
            raise InvalidRequest("rail maximum exceeds the declared voltage ceiling")
        rail_specs[parameter] = {"name": rail["name"], "low": low, "high": high, "step": step}
    red = _options(setup.get("redLedOptions"), "redLedOptions", {"on", "off"})
    green = _options(setup.get("greenLedOptions"), "greenLedOptions", {"on", "off"})
    workloads = _options(setup.get("workloadOptions"), "workloadOptions")
    budget = setup.get("experimentBudget")
    if not isinstance(budget, int) or budget < 1:
        raise InvalidRequest("experimentBudget must be a positive integer")
    distributions: dict[str, optuna.distributions.BaseDistribution] = {
        **{name: optuna.distributions.FloatDistribution(spec["low"], spec["high"], step=spec["step"])
           for name, spec in rail_specs.items()},
        "redLed": optuna.distributions.CategoricalDistribution(red),
        "greenLed": optuna.distributions.CategoricalDistribution(green),
        "workload": optuna.distributions.CategoricalDistribution(workloads),
    }
    return distributions, {"rails": rail_specs, "budget": budget,
                           "red": red, "green": green, "workloads": workloads}


def _key(params: dict[str, Any]) -> tuple[Any, ...]:
    return tuple((name, round(float(value), 9) if name.endswith("Volts") else value)
                 for name, value in sorted(params.items()))


def propose(request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise InvalidRequest("request must be an object")
    setup = request.get("setup")
    distributions, domain = _domain(setup)
    method = str(request.get("method", "tpe")).lower()
    if method not in {"tpe", "random", "grid"}:
        raise InvalidRequest("method must be tpe, random, or grid")
    seed = request.get("seed", 42)
    count = request.get("count", 3)
    warmup = request.get("warmupTrials", 8)
    if not isinstance(seed, int) or not isinstance(count, int) or not isinstance(warmup, int):
        raise InvalidRequest("seed, count, and warmupTrials must be integers")
    if count < 1 or count > 10 or warmup < 1:
        raise InvalidRequest("count must be 1–10 and warmupTrials must be positive")
    count = min(count, domain["budget"])
    history = request.get("history", [])
    if not isinstance(history, list) or len(history) > 10000:
        raise InvalidRequest("history must be a list of at most 10000 results")

    if method == "tpe":
        sampler = optuna.samplers.TPESampler(seed=seed, n_startup_trials=warmup)
    elif method == "random":
        sampler = optuna.samplers.RandomSampler(seed=seed)
    else:
        # Grid is a baseline for small domains only. Do not expand huge spaces.
        grid_space = {}
        total = len(domain["red"]) * len(domain["green"]) * len(domain["workloads"])
        for name, spec in domain["rails"].items():
            values = []
            current = Decimal(str(spec["low"]))
            maximum = Decimal(str(spec["high"]))
            increment = Decimal(str(spec["step"]))
            while current <= maximum and len(values) <= 10000:
                values.append(float(current))
                current += increment
            total *= len(values)
            grid_space[name] = values
        if total > 10000:
            raise InvalidRequest("grid baseline exceeds 10000 combinations")
        sampler = optuna.samplers.GridSampler({**grid_space, "redLed": domain["red"],
                                               "greenLed": domain["green"], "workload": domain["workloads"]}, seed=seed)

    study = optuna.create_study(direction="minimize", sampler=sampler)
    seen = set()
    usable = 0
    for item in history:
        if not isinstance(item, dict):
            raise InvalidRequest("history entries must be objects")
        if item.get("outcome") not in {"PASS", "DUT_FAILURE", "INVALID_EXPERIMENT", "SAFETY_ABORT"}:
            raise InvalidRequest("history outcome is unsupported")
        if item["outcome"] in {"INVALID_EXPERIMENT", "SAFETY_ABORT"}:
            continue
        params = item.get("conditions")
        if not isinstance(params, dict) or set(params) != set(distributions):
            raise InvalidRequest("valid history needs complete conditions")
        try:
            trial = optuna.trial.create_trial(params=params, distributions=distributions,
                                               value=_number(item.get("robustness"), "history.robustness"))
            study.add_trial(trial)
        except ValueError as exc:
            raise InvalidRequest("history conditions do not match this setup") from exc
        seen.add(_key(params))
        usable += 1

    proposals = []
    attempts = 0
    while len(proposals) < count and attempts < max(50, count * 50):
        attempts += 1
        try:
            trial = study.ask(fixed_distributions=distributions)
        except RuntimeError:  # GridSampler exhausted its finite search space.
            break
        params = trial.params
        if _key(params) in seen:
            continue
        seen.add(_key(params))
        reason = ("TPE selected this from prior measured robustness" if method == "tpe" and usable >= warmup
                  else "Startup coverage before adaptive feedback" if method == "tpe"
                  else "Uniform random baseline" if method == "random" else "Grid baseline")
        proposals.append({"id": f"candidate-{len(proposals) + 1}", "conditions": params, "reason": reason})

    return {"source": "decision", "method": method, "setupName": setup["name"],
            "historyUsed": usable, "tests": proposals}


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
