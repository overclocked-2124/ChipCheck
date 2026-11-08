"""The Controller: runs one leased episode against a ``BenchAdapter`` and submits evidence.

It owns the local episode lifecycle (HLD 03 §8): re-validates the claim with the shared safety
rules before power is applied, keeps the lease alive while the adapter works, reports phases to
Backend, and submits *evidence, never an outcome*. Evidence is written to the local spool before
any upload, so a control-plane outage cannot lose a measurement (HLD 03 §8 ``EVIDENCE_PENDING``).
Any doubt about the physical state ends in emergency shutdown and a reported trip, never in a retry
(HLD 03 §17.2). It knows nothing about the simulator or the serial driver: only ``BenchAdapter``.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import Any, Callable

from activequal.adapter.service.base import BenchAdapter
from activequal.adapter.service.types import ApprovedEpisode, BenchHealth, Phase, RawBenchCapture
from activequal.controller.service.client import BackendClient
from activequal.controller.service.spool import Spool
from activequal.model.canonical import contract_hash as compute_contract_hash
from activequal.model.contract import ContractModel, parse_contract
from activequal.model.errors import InvalidRequest
from activequal.model.evidence import manifest_hash
from activequal.model.safety import capture_trips, check_candidate
from activequal.service.errors import BackendError

log = logging.getLogger("activequal.controller")

DEFAULT_DWELL_MS = 500

SUBMITTED = "SUBMITTED"
EVIDENCE_PENDING = "EVIDENCE_PENDING"
PREFLIGHT_FAILED = "PREFLIGHT_FAILED"
CUTOFF = "CUTOFF"
LEASE_LOST = "LEASE_LOST"
BENCH_UNHEALTHY = "BENCH_UNHEALTHY"
REJECTED = "REJECTED"


@dataclass(frozen=True)
class RunReport:
    status: str
    episode_id: str | None = None
    verdict: dict[str, Any] | None = None
    detail: tuple[str, ...] = ()


def health_report(health: BenchHealth) -> dict[str, Any]:
    """The bench health message of HLD 05 §7. A latched lockout counts as an active trip."""
    return {"estopReleased": health.estop_released, "interlockHealthy": not health.locked_out,
            "watchdogHealthy": health.watchdog_ok, "outputsInShutdown": not health.locked_out or health.estop_released,
            "adaptersCompatible": health.dut_connected and health.instruments_connected,
            "tripActive": health.locked_out, "dutFirmwareSha256": health.dut_firmware_sha256,
            "mcuFirmwareSha256": health.mcu_firmware_sha256}


def build_payload(claim: dict[str, Any], model: ContractModel | None, capture: RawBenchCapture | None, *,
                  trip: str | None = None, problems: tuple[str, ...] = ()) -> dict[str, Any]:
    """Turn a capture into the result payload of HLD 05 §7.1. ``capture`` is None when nothing was measured.

    ``model`` may be None only when the claimed contract could not be parsed (nothing is measured then)."""
    measured: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    settled = instrument_fault = False
    shutdown = True
    timeouts = list(problems)
    if capture is not None:
        measured.update({name: {"value": float(value)} for name, value in capture.observations.items()})
        for name in capture.missing_observations:
            measured.setdefault(name, {"value": None})
        for rule in (model.validity if model is not None else None) or []:
            rail = capture.measured_rail_v.get(rule.tracks)
            measured[rule.metric] = {"value": None if rail is None else float(rail)}
        events = [{"type": e.phase, "controllerTimeMs": e.t_ms, "note": e.note} for e in capture.events]
        settled, shutdown = capture.rail_settled, capture.shutdown_confirmed
        instrument_fault = bool(capture.instrument_errors)
        if capture.heartbeat_lost:
            events.append({"type": "DUT_HEARTBEAT_LOST", "controllerTimeMs": 0, "note": "DUT heartbeat lost"})
        for error in capture.instrument_errors:
            events.append({"type": "INSTRUMENT_ERROR", "controllerTimeMs": 0, "note": error})
        trip = capture.trip or ("hardware cutoff engaged" if capture.cutoff_engaged else trip)
    payload = {
        "episodeId": claim["episodeId"], "attempt": claim["attempt"], "leaseId": claim["leaseId"],
        "contractHash": claim["contractHash"], "fixtureId": claim["fixtureId"], "requested": claim["requested"],
        "measured": measured,
        "quality": {"railSettled": settled, "instrumentFault": instrument_fault, "shutdownConfirmed": shutdown and trip is None,
                    "timeouts": timeouts},
        "events": events, "traces": [], "safetyTrip": trip}
    payload["manifestHash"] = manifest_hash(payload)
    return payload


class Controller:
    def __init__(self, client: BackendClient, adapter: BenchAdapter, spool: Spool, fixture_id: str, *,
                 instance_id: str = "controller-1", heartbeat_interval_s: float = 1.0,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.client, self.adapter, self.spool = client, adapter, spool
        self.fixture_id, self.instance_id = fixture_id, instance_id
        self.heartbeat_interval_s = heartbeat_interval_s
        self._sleep = sleep

    # -------------------------------------------------------------------- health

    def report_health(self) -> BenchHealth:
        health = self.adapter.health_check()
        self.client.report_health(health_report(health))
        return health

    def flush_spool(self) -> list[str]:
        """Upload evidence left over from earlier outages. Returns the episode ids still pending."""
        still_pending: list[str] = []
        for payload in list(self.spool.pending()):
            try:
                self.client.submit_result(payload)
            except BackendError as exc:
                log.warning("spooled result %s not accepted: %s", payload.get("episodeId"), exc.code)
                still_pending.append(payload["episodeId"])
            except Exception as exc:                      # control plane unreachable: keep the file
                log.warning("spooled result %s not uploaded: %r", payload.get("episodeId"), exc)
                still_pending.append(payload["episodeId"])
            else:
                self.spool.remove(payload)
        return still_pending

    # ------------------------------------------------------------------ preflight

    def _preflight(self, claim: dict[str, Any]) -> tuple[ContractModel | None, list[str]]:
        problems: list[str] = []
        contract = claim.get("contract")
        try:
            digest = compute_contract_hash(contract)
            if digest != claim["contractHash"]:
                problems.append("the contract sent with the claim does not match its hash")
            model = parse_contract(contract, require_oracle=True)
        except Exception as exc:
            return None, [f"the claimed contract cannot be used: {exc}"]
        if claim["fixtureId"] != self.fixture_id:
            problems.append(f"the claim is for fixture {claim['fixtureId']}, this bench is {self.fixture_id}")
        decision = check_candidate(model, claim["requested"], fixture_capabilities=frozenset(claim["fixtureCapabilities"]),
                                   contract_hash=claim["contractHash"], expected_hash=digest)
        problems.extend(f"{v.code}: {v.message}" for v in decision.violations)
        health = self.adapter.health_check()
        if not health.ok:
            problems.append("bench health: " + ("; ".join(health.detail) or "not ok"))
        expected_dut = model.setup.get("firmwareSha256")
        if expected_dut and health.dut_firmware_sha256 != expected_dut:
            problems.append("the DUT firmware does not match the contract")
        return model, problems

    # ------------------------------------------------------------------- one run

    def run_once(self) -> RunReport | None:
        self.flush_spool()
        health = self.report_health()
        if not health.ok:
            return RunReport(BENCH_UNHEALTHY, detail=health.detail or ("bench reported not ok",))
        claim = self.client.claim(self.instance_id)
        if claim is None:
            return None
        episode_id = claim["episodeId"]
        lease_id = claim["leaseId"]
        model, problems = self._preflight(claim)
        self.client.heartbeat(lease_id, Phase.PREFLIGHT.value)
        if model is None:
            return self._fail_preflight(claim, None, problems)
        if problems:
            return self._fail_preflight(claim, model, problems)

        episode = ApprovedEpisode(
            episode_id=episode_id, attempt=claim["attempt"], contract_hash=claim["contractHash"],
            fixture_id=self.fixture_id, conditions=dict(claim["requested"]),
            duration_ms=int(claim["requested"].get("dwellMs", DEFAULT_DWELL_MS)),
            seed=int(claim["episodeSeed"]))
        capture, error, abort, lease_lost = self._execute(lease_id, episode)

        trip = None
        if error is not None:
            trip = f"controller error: {error!r}"
        elif capture is not None and not capture.trip and not capture.cutoff_engaged:
            exceeded = capture_trips(model, capture.measured_rail_v, capture.measured_current_a) if model else ()
            if exceeded:
                self.adapter.emergency_shutdown()
                capture = replace(capture, trip="; ".join(exceeded), cutoff_engaged=True,
                                  phases_reached=capture.phases_reached + (Phase.EMERGENCY_CUTOFF.value,))
        phases = [] if capture is None else [p for p in capture.phases_reached if p != Phase.PREFLIGHT.value]
        if capture is None:
            phases = [Phase.EMERGENCY_CUTOFF.value]
        if phases and phases[-1] == Phase.EMERGENCY_CUTOFF.value:
            phases.append("LOCKOUT")
        payload = build_payload(claim, model, capture, trip=trip)
        self.spool.save(payload)                # durable before anything else can fail
        report_error = self._report_phases(lease_id, phases)
        if lease_lost or report_error:
            return RunReport(LEASE_LOST, episode_id, detail=(report_error or "lease lost during the episode",))
        if abort:
            try:
                self.client.acknowledge_abort(lease_id)
            except BackendError as exc:
                log.warning("abort acknowledgement refused: %s", exc.message)
        return self._submit(payload, CUTOFF if payload["safetyTrip"] else SUBMITTED)

    def _fail_preflight(self, claim: dict[str, Any], model: ContractModel | None, problems: list[str]) -> RunReport:
        """Nothing was energized: report shutdown and let Backend classify the (empty) evidence as invalid."""
        reasons = tuple(f"preflight: {p}" for p in problems)
        try:
            self.client.heartbeat(claim["leaseId"], Phase.SHUTTING_DOWN.value)
            payload = build_payload(claim, model, None, problems=reasons)
            payload["quality"]["railSettled"] = False
            payload["manifestHash"] = manifest_hash(payload)
            self.spool.save(payload)
            report = self._submit(payload, PREFLIGHT_FAILED)
        except (BackendError, InvalidRequest) as exc:
            return RunReport(PREFLIGHT_FAILED, claim["episodeId"], detail=reasons + (str(exc),))
        return RunReport(PREFLIGHT_FAILED, claim["episodeId"], report.verdict, reasons)

    def _execute(self, lease_id: str, episode: ApprovedEpisode
                 ) -> tuple[RawBenchCapture | None, BaseException | None, bool, bool]:
        """Run the adapter in a worker while the lease is kept alive. Returns (capture, error, abort, lease_lost)."""
        abort = lease_lost = False
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.adapter.apply_and_measure, episode)
            while True:
                try:
                    future.result(timeout=self.heartbeat_interval_s)
                    break
                except TimeoutError:
                    pass
                except BaseException:
                    break
                try:
                    abort = abort or self.client.heartbeat(lease_id).get("abort", False)
                except BackendError:
                    if not lease_lost:                  # losing the lease never means "keep going"
                        lease_lost = True
                        self.adapter.emergency_shutdown()
        try:
            return future.result(), None, abort, lease_lost
        except BaseException as exc:                    # uncertain physical state: cut power, report a trip
            log.error("adapter failed during %s: %r", episode.episode_id, exc)
            self.adapter.emergency_shutdown()
            return None, exc, abort, lease_lost

    def _report_phases(self, lease_id: str, phases: list[str]) -> str | None:
        for phase in phases:
            try:
                self.client.heartbeat(lease_id, phase)
            except BackendError as exc:
                return f"could not report {phase}: {exc.message}"
        return None

    def _submit(self, payload: dict[str, Any], status: str) -> RunReport:
        try:
            verdict = self.client.submit_result(payload)
        except BackendError as exc:
            if exc.code == "UNAVAILABLE":
                return RunReport(EVIDENCE_PENDING, payload["episodeId"], detail=(exc.message,))
            return RunReport(REJECTED, payload["episodeId"], detail=(f"{exc.code}: {exc.message}",))
        except Exception as exc:                        # control plane unreachable; the spool keeps the evidence
            return RunReport(EVIDENCE_PENDING, payload["episodeId"], detail=(repr(exc),))
        self.spool.remove(payload)
        return RunReport(status, payload["episodeId"], verdict)
