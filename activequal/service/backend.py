"""The Backend Service: authoritative state for contracts, fixtures, campaigns, episodes and results.

Everything here is a plain method call. The HTTP layer (HLD 05) only authenticates, parses and
forwards; it holds no rules. Every state change runs in one IMMEDIATE SQLite transaction, goes
through the transition tables in ``states.py`` and appends an audit event (HLD 03 §3 principles 1
and 10, §19). A candidate becomes an executable episode only after the shared safety-rule library
approves it (HLD 03 §7, §11.1); the bench submits evidence and Backend runs the Oracle (HLD 01
decision 13).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from activequal.model.canonical import CanonicalError, canonical_json, contract_hash as compute_contract_hash
from activequal.model.contract import ContractModel, parse_contract
from activequal.model.errors import InvalidRequest
from activequal.model.evidence import EpisodeResult, manifest_hash, parse_result
from activequal.model.safety import SHUTDOWN_ALLOWANCE_S, check_candidate
from activequal.service import oracle
from activequal.service.errors import BackendError, invalid, not_found, precondition
from activequal.service.ids import Clock, SystemClock, isoformat, new_id, parse_time
from activequal.service.states import (CAMPAIGN_TRANSITIONS, CANDIDATE_TRANSITIONS, EPISODE_TRANSITIONS,
                                       CampaignState as C, CandidateState as K, EpisodeState as E,
                                       IllegalTransition, transition)
from activequal.storage.database import Database

PROJECT_ID = "default"
RESEARCHER, REVIEWER, SYSTEM = "researcher", "reviewer", "system"

ROLE_DISCOVERY = "discovery"
VERIFICATION_ROLES = frozenset({"confirm", "minimize", "bracket", "necessity_probe"})
EPISODE_ROLES = VERIFICATION_ROLES | {ROLE_DISCOVERY}

LEASE_TTL_S = 5.0                   # HLD 03 §21.1: heartbeat 1 s, expiry 5 s
HEALTH_MAX_AGE_S = 10.0
MAX_TRACE_BYTES = 256 * 1024 * 1024
ACTIVE_CAMPAIGN_STATES = (C.ARMED, C.RUNNING, C.PAUSING, C.PAUSED, C.ABORTING, C.LOCKED_OUT)
DEFAULT_PLANNERS = frozenset({"tpe", "gp", "random", "grid", "fixed_corner", "coverage", "manual"})

# Phases a bench may report on heartbeat, mapped to episode states (HLD 03 §8).
PHASE_STATES = {s.value: s for s in (E.PREFLIGHT, E.CONFIGURING, E.SETTLING, E.EXECUTING, E.OBSERVING,
                                     E.SHUTTING_DOWN, E.EMERGENCY_CUTOFF, E.LOCKOUT)}


@dataclass(frozen=True)
class Actor:
    name: str
    roles: frozenset[str]

    def has(self, role: str) -> bool:
        return role in self.roles


def researcher(name: str) -> Actor:
    return Actor(name, frozenset({RESEARCHER}))


def reviewer(name: str) -> Actor:
    return Actor(name, frozenset({REVIEWER}))


SYSTEM_ACTOR = Actor("backend", frozenset({SYSTEM}))


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(text: str | bytes) -> str:
    return hashlib.sha256(text.encode() if isinstance(text, str) else text).hexdigest()


def _limits_signature(model: ContractModel) -> str:
    """What a reviewer must re-approve: safety limits and every control's range, slew and binding."""
    controls = {name: (c.kind, c.minimum, c.maximum, c.step, c.shutdown, c.slew_per_s_max, c.bind, c.unit)
                for name, c in model.controls.items()}
    return _json({"controls": controls, "forbidden": model.forbidden, "safety": repr(model.safety)})


class Backend:
    def __init__(self, db: Database, trace_dir: str | Path, *, clock: Clock | None = None,
                 software_version: str = "dev", known_planners: Iterable[str] = DEFAULT_PLANNERS,
                 lease_ttl_s: float = LEASE_TTL_S) -> None:
        self.db = db
        self.trace_dir = Path(trace_dir)
        self.clock = clock or SystemClock()
        self.software_version = software_version
        self.known_planners = frozenset(known_planners)
        self.lease_ttl_s = lease_ttl_s
        self._models: dict[str, ContractModel] = {}
        with self.db.transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO projects (id, name) VALUES (?, ?)", (PROJECT_ID, "default"))

    # ------------------------------------------------------------------ helpers

    def _now(self) -> datetime:
        return self.clock.now()

    def _ts(self) -> str:
        return isoformat(self._now())

    @staticmethod
    def _require(actor: Actor, *roles: str) -> None:
        if not any(actor.has(role) for role in roles):
            raise BackendError("PERMISSION_DENIED", f"{actor.name} needs the {' or '.join(roles)} role")

    def _event(self, conn: sqlite3.Connection, entity: str, new_state: str, *, previous: str | None = None,
               campaign_id: str | None = None, episode_id: str | None = None, attempt: int | None = None,
               actor: Actor, reason_code: str, reason: str, contract_hash: str | None = None,
               fixture_id: str | None = None, controller_ts: str | None = None,
               detail: dict[str, Any] | None = None) -> None:
        conn.execute(
            "INSERT INTO events (entity, campaign_id, episode_id, attempt, previous_state, new_state, actor_type,"
            " actor_id, reason_code, reason, backend_ts, controller_ts, contract_hash, fixture_id, detail_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (entity, campaign_id, episode_id, attempt, previous, new_state, ",".join(sorted(actor.roles)),
             actor.name, reason_code, reason, self._ts(), controller_ts, contract_hash, fixture_id,
             _json(detail) if detail is not None else None))

    def _model(self, conn: sqlite3.Connection, contract_version_id: str) -> ContractModel:
        model = self._models.get(contract_version_id)
        if model is None:
            row = conn.execute("SELECT canonical_json FROM contract_versions WHERE id = ?",
                               (contract_version_id,)).fetchone()
            if row is None:
                raise not_found("contract version")
            model = parse_contract(json.loads(row["canonical_json"]), require_oracle=True)
            self._models[contract_version_id] = model
        return model

    # ---------------------------------------------------------------- contracts

    def create_contract(self, contract: Any, actor: Actor, contract_key: str | None = None) -> dict[str, Any]:
        self._require(actor, RESEARCHER, REVIEWER)
        try:
            model = parse_contract(contract, require_oracle=True)
            digest = compute_contract_hash(contract)
            canonical = canonical_json(contract).decode()
        except (InvalidRequest, CanonicalError) as exc:
            raise invalid(str(exc)) from exc
        with self.db.transaction() as conn:
            last = None
            if contract_key is not None:
                last = conn.execute("SELECT * FROM contract_versions WHERE contract_key = ? ORDER BY version DESC",
                                    (contract_key,)).fetchone()
                if last is None:
                    raise not_found("contract")
            existing = conn.execute("SELECT * FROM contract_versions WHERE project_id = ? AND contract_hash = ?",
                                    (PROJECT_ID, digest)).fetchone()
            if existing:
                return self._contract_summary(conn, existing)
            if last is None:
                contract_key, version, previous = new_id(), 1, None
            else:
                version, previous = last["version"] + 1, last
            # Two people must approve a first version or any change to limits (PRD §28.1, HLD 07 §7).
            required = 2
            if previous is not None and _limits_signature(self._model(conn, previous["id"])) == _limits_signature(model):
                required = 1
            row_id = new_id()
            conn.execute(
                "INSERT INTO contract_versions (id, project_id, contract_key, version, canonical_json, contract_hash,"
                " created_by, created_at, approvals_required) VALUES (?,?,?,?,?,?,?,?,?)",
                (row_id, PROJECT_ID, contract_key, version, canonical, digest, actor.name, self._ts(), required))
            self._event(conn, "contract", "CREATED", actor=actor, reason_code="CONTRACT_CREATED",
                        reason=f"contract version {version} created", contract_hash=digest,
                        detail={"contractKey": contract_key, "version": version, "approvalsRequired": required})
            return self._contract_summary(conn, conn.execute("SELECT * FROM contract_versions WHERE id = ?",
                                                             (row_id,)).fetchone())

    def _contract_summary(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        approvers = [r["reviewer"] for r in conn.execute(
            "SELECT reviewer FROM contract_approvals WHERE contract_version_id = ? ORDER BY approved_at, reviewer",
            (row["id"],))]
        return {"id": row["id"], "contractId": row["contract_key"], "version": row["version"],
                "contractHash": row["contract_hash"], "approvalsRequired": row["approvals_required"],
                "approvedBy": approvers, "approved": len(approvers) >= row["approvals_required"]}

    def _contract_row(self, conn: sqlite3.Connection, contract_key: str, version: int) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM contract_versions WHERE contract_key = ? AND version = ?",
                           (contract_key, version)).fetchone()
        if row is None:
            raise not_found("contract version")
        return row

    def approve_contract(self, contract_key: str, version: int, actor: Actor) -> dict[str, Any]:
        self._require(actor, REVIEWER)
        with self.db.transaction() as conn:
            row = self._contract_row(conn, contract_key, version)
            if conn.execute("SELECT 1 FROM contract_approvals WHERE contract_version_id = ? AND reviewer = ?",
                            (row["id"], actor.name)).fetchone() is None:
                conn.execute("INSERT INTO contract_approvals VALUES (?,?,?)", (row["id"], actor.name, self._ts()))
                self._event(conn, "contract", "APPROVED", actor=actor, reason_code="CONTRACT_APPROVED",
                            reason=f"{actor.name} approved version {version}", contract_hash=row["contract_hash"])
            return self._contract_summary(conn, row)

    def get_contract(self, contract_key: str, version: int) -> dict[str, Any]:
        with self.db.transaction() as conn:
            row = self._contract_row(conn, contract_key, version)
            return {**self._contract_summary(conn, row), "contract": json.loads(row["canonical_json"])}

    # ----------------------------------------------------------------- fixtures

    def register_fixture(self, fixture_id: str, revision: str, capabilities: list[str], actor: Actor,
                         approved_mcu_firmware_sha256: str | None = None) -> dict[str, Any]:
        """Register a fixture and issue its bench token. The token is returned once and stored only as a hash."""
        self._require(actor, REVIEWER)
        if not fixture_id.strip() or not revision.strip():
            raise invalid("fixture id and revision are required")
        if (not isinstance(capabilities, list) or not capabilities
                or not all(isinstance(c, str) and c for c in capabilities)):
            raise invalid("capabilities must be a non-empty list of target names")
        token = "aqb_" + secrets.token_urlsafe(32)
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    "INSERT INTO fixtures (id, project_id, revision, capabilities_json, token_sha256,"
                    " approved_mcu_firmware_sha256, created_at) VALUES (?,?,?,?,?,?,?)",
                    (fixture_id, PROJECT_ID, revision, _json(sorted(set(capabilities))), _sha256(token),
                     approved_mcu_firmware_sha256, self._ts()))
                self._event(conn, "fixture", "REGISTERED", fixture_id=fixture_id, actor=actor,
                            reason_code="FIXTURE_REGISTERED", reason=f"fixture {fixture_id} revision {revision}")
        except sqlite3.IntegrityError as exc:
            raise precondition(f"fixture {fixture_id} already exists") from exc
        return {"fixtureId": fixture_id, "token": token}

    def rotate_bench_token(self, fixture_id: str, actor: Actor) -> dict[str, Any]:
        self._require(actor, REVIEWER)
        token = "aqb_" + secrets.token_urlsafe(32)
        with self.db.transaction() as conn:
            if conn.execute("UPDATE fixtures SET token_sha256 = ? WHERE id = ?", (_sha256(token), fixture_id)).rowcount == 0:
                raise not_found("fixture")
            self._event(conn, "fixture", "TOKEN_ROTATED", fixture_id=fixture_id, actor=actor,
                        reason_code="TOKEN_ROTATED", reason="bench token rotated")
        return {"fixtureId": fixture_id, "token": token}

    def authenticate_bench(self, token: str) -> str:
        """Return the fixture a bench token belongs to. A token never works for another fixture."""
        if not isinstance(token, str) or not token:
            raise BackendError("UNAUTHENTICATED", "bench token required")
        row = self.db.one("SELECT id FROM fixtures WHERE token_sha256 = ?", (_sha256(token),))
        if row is None:
            raise BackendError("UNAUTHENTICATED", "unknown bench token")
        return row["id"]

    def _fixture(self, conn: sqlite3.Connection, fixture_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM fixtures WHERE id = ?", (fixture_id,)).fetchone()
        if row is None:
            raise not_found("fixture")
        return row

    def record_calibration(self, fixture_id: str, channels: dict[str, dict[str, float]], meter_identity: str,
                           operator: str, valid_until: datetime, actor: Actor) -> dict[str, Any]:
        self._require(actor, RESEARCHER, REVIEWER)
        if not isinstance(channels, dict) or not channels:
            raise invalid("calibration needs at least one channel")
        for name, values in channels.items():
            if not isinstance(values, dict) or not all(
                    isinstance(values.get(k), (int, float)) and not isinstance(values.get(k), bool)
                    for k in ("gain", "offset", "uncertainty")):
                raise invalid(f"channel {name} needs numeric gain, offset and uncertainty")
        if not meter_identity.strip() or not operator.strip():
            raise invalid("meter identity and operator are required")
        if valid_until.tzinfo is None or valid_until <= self._now():
            raise invalid("valid_until must be a timezone-aware time in the future")
        cal_id = new_id()
        with self.db.transaction() as conn:
            self._fixture(conn, fixture_id)
            conn.execute("INSERT INTO calibrations VALUES (?,?,?,?,?,?,?)",
                         (cal_id, fixture_id, _json(channels), meter_identity.strip(), operator.strip(), self._ts(),
                          isoformat(valid_until)))
            conn.execute("UPDATE fixtures SET current_calibration_id = ? WHERE id = ?", (cal_id, fixture_id))
            self._event(conn, "fixture", "CALIBRATED", fixture_id=fixture_id, actor=actor,
                        reason_code="CALIBRATION_RECORDED", reason=f"calibration {cal_id} by {operator}",
                        detail={"calibrationId": cal_id, "validUntil": isoformat(valid_until)})
        return {"calibrationId": cal_id}

    def record_bench_health(self, fixture_id: str, health: dict[str, Any]) -> dict[str, Any]:
        """Store the bench's latest health report. A trip or pressed E-stop locks out an active campaign."""
        flags = ("estopReleased", "interlockHealthy", "watchdogHealthy", "outputsInShutdown", "adaptersCompatible",
                 "tripActive")
        if not isinstance(health, dict) or not all(isinstance(health.get(f), bool) for f in flags):
            raise invalid("health needs boolean " + ", ".join(flags))
        for key in ("dutFirmwareSha256", "mcuFirmwareSha256"):
            if health.get(key) is not None and not isinstance(health.get(key), str):
                raise invalid(f"{key} must be a string or null")
        with self.db.transaction() as conn:
            self._fixture(conn, fixture_id)
            conn.execute("UPDATE fixtures SET health_json = ?, health_at = ? WHERE id = ?",
                         (_json(health), self._ts(), fixture_id))
            if health["tripActive"] or not health["estopReleased"]:
                campaign = conn.execute(
                    "SELECT * FROM campaigns WHERE fixture_id = ? AND state IN (?,?,?,?)",
                    (fixture_id, C.ARMED, C.RUNNING, C.PAUSING, C.ABORTING)).fetchone()
                if campaign is not None:
                    reason = "trip reported by the bench" if health["tripActive"] else "E-stop pressed"
                    self._lockout(conn, campaign, reason_code="BENCH_REPORTED_TRIP", reason=reason, actor=SYSTEM_ACTOR)
        return {"recorded": True}

    def _bench_reasons(self, conn: sqlite3.Connection, fixture: sqlite3.Row, model: ContractModel,
                       tuple_: dict[str, Any] | None) -> list[dict[str, str]]:
        """Reasons the bench is not ready to arm, start or resume (HLD 03 §6.2). Empty means ready."""
        reasons: list[dict[str, str]] = []

        def add(code: str, message: str) -> None:
            reasons.append({"code": code, "message": message})

        cal = None
        if fixture["current_calibration_id"]:
            cal = conn.execute("SELECT * FROM calibrations WHERE id = ?", (fixture["current_calibration_id"],)).fetchone()
        if cal is None:
            add("CALIBRATION_MISSING", "the fixture has no calibration")
        elif parse_time(cal["valid_until"]) <= self._now():
            add("CALIBRATION_EXPIRED", "the fixture's calibration has expired")
        elif tuple_ is not None and tuple_.get("calibrationId") != cal["id"]:
            add("CALIBRATION_CHANGED", "the calibration changed since arming")
        if not fixture["health_json"] or not fixture["health_at"]:
            add("BENCH_HEALTH_UNKNOWN", "the bench has not reported its health")
            return reasons
        health = json.loads(fixture["health_json"])
        if (self._now() - parse_time(fixture["health_at"])).total_seconds() > HEALTH_MAX_AGE_S:
            add("BENCH_HEALTH_STALE", f"the bench health report is older than {HEALTH_MAX_AGE_S:g} s")
        for key, code, message in (("estopReleased", "ESTOP_PRESSED", "the E-stop is pressed"),
                                   ("interlockHealthy", "INTERLOCK_UNHEALTHY", "the hardware interlock is not healthy"),
                                   ("watchdogHealthy", "WATCHDOG_UNHEALTHY", "the watchdog is not healthy"),
                                   ("outputsInShutdown", "OUTPUTS_ENERGIZED", "programmable outputs are not in shutdown"),
                                   ("adaptersCompatible", "ADAPTER_INCOMPATIBLE", "adapter capabilities are incompatible")):
            if not health[key]:
                add(code, message)
        if health["tripActive"]:
            add("TRIP_ACTIVE", "an unresolved trip is active")
        expected_dut = model.setup.get("firmwareSha256")
        if expected_dut and health.get("dutFirmwareSha256") != expected_dut:
            add("DUT_FIRMWARE_MISMATCH", "the DUT firmware does not match the contract")
        approved_mcu = fixture["approved_mcu_firmware_sha256"]
        if approved_mcu and health.get("mcuFirmwareSha256") != approved_mcu:
            add("MCU_FIRMWARE_MISMATCH", "the test-controller firmware is not the approved one")
        if tuple_ is not None:
            for key, code in (("dutFirmwareSha256", "DUT_FIRMWARE_CHANGED"), ("mcuFirmwareSha256", "MCU_FIRMWARE_CHANGED")):
                if health.get(key) != tuple_.get(key):
                    add(code, "firmware identity changed since arming")
        return reasons

    # ---------------------------------------------------------------- campaigns

    def create_campaign(self, contract_key: str, contract_version: int, fixture_id: str, planner_method: str,
                        seed: int, discovery_budget: int, verification_budget: int, actor: Actor,
                        planner_config: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require(actor, RESEARCHER)
        for name, value in (("seed", seed), ("discovery_budget", discovery_budget),
                            ("verification_budget", verification_budget)):
            if not isinstance(value, int) or isinstance(value, bool):
                raise invalid(f"{name} must be an integer")
        if discovery_budget < 1 or verification_budget < 0:
            raise invalid("discovery_budget must be at least 1 and verification_budget at least 0")
        try:
            config_json = _json(planner_config or {})
        except (TypeError, ValueError) as exc:
            raise invalid("planner_config must be JSON") from exc
        campaign_id = new_id()
        with self.db.transaction() as conn:
            contract = self._contract_row(conn, contract_key, contract_version)
            self._fixture(conn, fixture_id)
            model = self._model(conn, contract["id"])
            plan = model.plan if model.plan is not None else "default_v1"
            conn.execute(
                "INSERT INTO campaigns (id, project_id, state, version, contract_version_id, fixture_id, planner_method,"
                " planner_config_json, seed, plan_json, discovery_budget, verification_budget, software_version,"
                " created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (campaign_id, PROJECT_ID, C.DRAFT.value, 1, contract["id"], fixture_id, planner_method, config_json,
                 seed, _json(plan), discovery_budget, verification_budget, self.software_version, actor.name,
                 self._ts(), self._ts()))
            self._event(conn, "campaign", C.DRAFT.value, campaign_id=campaign_id, actor=actor,
                        reason_code="CAMPAIGN_CREATED", reason="campaign created",
                        contract_hash=contract["contract_hash"], fixture_id=fixture_id)
            return self._campaign_view(conn, self._campaign(conn, campaign_id))

    def _campaign(self, conn: sqlite3.Connection, campaign_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if row is None:
            raise not_found("campaign")
        return row

    def _move_campaign(self, conn: sqlite3.Connection, campaign: sqlite3.Row, new: C, *, actor: Actor,
                       reason_code: str, reason: str, expected_version: int | None = None,
                       extra: dict[str, Any] | None = None) -> sqlite3.Row:
        """One audited, version-checked campaign transition."""
        if expected_version is not None and campaign["version"] != expected_version:
            raise BackendError("STALE_VERSION", f"campaign changed since version {expected_version}",
                               {"currentVersion": campaign["version"]})
        current = C(campaign["state"])
        try:
            transition(CAMPAIGN_TRANSITIONS, current, new, actor_type=",".join(sorted(actor.roles)),
                       actor_id=actor.name, reason_code=reason_code, reason=reason, now=self._now())
        except IllegalTransition as exc:
            raise precondition(str(exc), state=current.value) from exc
        sets, params = ["state = ?", "version = version + 1", "updated_at = ?"], [new.value, self._ts()]
        for column, value in (extra or {}).items():
            sets.append(f"{column} = ?")
            params.append(value)
        try:
            cursor = conn.execute(f"UPDATE campaigns SET {', '.join(sets)} WHERE id = ? AND version = ?",
                                  (*params, campaign["id"], campaign["version"]))
        except sqlite3.IntegrityError as exc:
            raise precondition("the fixture already has an active campaign") from exc
        if cursor.rowcount != 1:
            raise BackendError("STALE_VERSION", "campaign changed concurrently")
        row = self._campaign(conn, campaign["id"])
        self._event(conn, "campaign", new.value, previous=current.value, campaign_id=campaign["id"], actor=actor,
                    reason_code=reason_code, reason=reason,
                    contract_hash=self._contract_hash(conn, campaign), fixture_id=campaign["fixture_id"])
        return row

    def _contract_hash(self, conn: sqlite3.Connection, campaign: sqlite3.Row) -> str:
        return conn.execute("SELECT contract_hash FROM contract_versions WHERE id = ?",
                            (campaign["contract_version_id"],)).fetchone()["contract_hash"]

    def _active_lease(self, conn: sqlite3.Connection, fixture_id: str) -> sqlite3.Row | None:
        return conn.execute("SELECT * FROM leases WHERE fixture_id = ? AND state IN ('ACTIVE','NEEDS_RECONCILIATION')",
                            (fixture_id,)).fetchone()

    def _settle(self, conn: sqlite3.Connection, campaign: sqlite3.Row) -> sqlite3.Row:
        """PAUSING -> PAUSED and ABORTING -> ABORTED once the bench no longer owns an episode."""
        campaign = self._campaign(conn, campaign["id"])
        if self._active_lease(conn, campaign["fixture_id"]) is not None:
            return campaign
        state = C(campaign["state"])
        if state is C.PAUSING:
            return self._move_campaign(conn, campaign, C.PAUSED, actor=SYSTEM_ACTOR, reason_code="PAUSED",
                                       reason="the active episode reached shutdown")
        if state is C.ABORTING:
            return self._move_campaign(conn, campaign, C.ABORTED, actor=SYSTEM_ACTOR, reason_code="ABORTED",
                                       reason="the bench confirmed shutdown")
        return campaign

    def _lockout(self, conn: sqlite3.Connection, campaign: sqlite3.Row, *, reason_code: str, reason: str,
                 actor: Actor) -> sqlite3.Row:
        campaign = self._campaign(conn, campaign["id"])
        if C(campaign["state"]) is C.LOCKED_OUT:
            return campaign
        return self._move_campaign(conn, campaign, C.LOCKED_OUT, actor=actor, reason_code=reason_code, reason=reason)

    def validate_campaign(self, campaign_id: str, campaign_version: int, actor: Actor) -> dict[str, Any]:
        self._require(actor, RESEARCHER)
        with self.db.transaction() as conn:
            campaign = self._campaign(conn, campaign_id)
            campaign = self._move_campaign(conn, campaign, C.VALIDATING, actor=actor, reason_code="VALIDATION_STARTED",
                                           reason="validation requested", expected_version=campaign_version)
            reasons = self._validation_reasons(conn, campaign)
            if reasons:
                campaign = self._move_campaign(conn, campaign, C.DRAFT, actor=SYSTEM_ACTOR,
                                               reason_code="VALIDATION_FAILED",
                                               reason="; ".join(r["message"] for r in reasons))
            else:
                campaign = self._move_campaign(conn, campaign, C.READY, actor=SYSTEM_ACTOR,
                                               reason_code="VALIDATION_PASSED", reason="configuration is valid")
            return {**self._campaign_view(conn, campaign), "reasons": reasons}

    def _validation_reasons(self, conn: sqlite3.Connection, campaign: sqlite3.Row) -> list[dict[str, str]]:
        reasons: list[dict[str, str]] = []

        def add(code: str, message: str) -> None:
            reasons.append({"code": code, "message": message})

        contract = conn.execute("SELECT * FROM contract_versions WHERE id = ?", (campaign["contract_version_id"],)).fetchone()
        fixture = self._fixture(conn, campaign["fixture_id"])
        model = self._model(conn, contract["id"])
        raw_setup = model.setup
        summary = self._contract_summary(conn, contract)
        if not summary["approved"]:
            add("CONTRACT_NOT_APPROVED", f"contract has {len(summary['approvedBy'])} of "
                                         f"{summary['approvalsRequired']} required approvals")
        if raw_setup.get("fixture") not in (None, fixture["id"]):
            add("FIXTURE_ID_MISMATCH", f"the contract is for fixture {raw_setup.get('fixture')}, not {fixture['id']}")
        if raw_setup.get("fixtureRev") not in (None, fixture["revision"]):
            add("FIXTURE_REVISION_MISMATCH", f"the contract expects revision {raw_setup.get('fixtureRev')}, "
                                             f"the fixture is {fixture['revision']}")
        capabilities = set(json.loads(fixture["capabilities_json"]))
        missing = sorted({c.bind[0] for c in model.controls.values() if c.bind} - capabilities)
        if missing:
            add("CAPABILITY_MISSING", "the fixture lacks: " + ", ".join(missing))
        if campaign["discovery_budget"] + campaign["verification_budget"] > model.budget:
            add("BUDGET_EXCEEDS_CONTRACT", f"the pools total "
                                           f"{campaign['discovery_budget'] + campaign['verification_budget']} but the "
                                           f"contract allows {model.budget}")
        if campaign["planner_method"] not in self.known_planners:
            add("PLANNER_UNKNOWN", f"planner {campaign['planner_method']!r} is not available")
        return reasons

    def _arming_tuple(self, fixture: sqlite3.Row, contract_hash: str) -> dict[str, Any]:
        health = json.loads(fixture["health_json"])
        return {"contractHash": contract_hash, "fixtureRevision": fixture["revision"],
                "calibrationId": fixture["current_calibration_id"], "dutFirmwareSha256": health.get("dutFirmwareSha256"),
                "mcuFirmwareSha256": health.get("mcuFirmwareSha256"), "softwareVersion": self.software_version}

    def arm_campaign(self, campaign_id: str, campaign_version: int, actor: Actor) -> dict[str, Any]:
        self._require(actor, RESEARCHER)
        with self.db.transaction() as conn:
            campaign = self._campaign(conn, campaign_id)
            if C(campaign["state"]) is not C.READY:
                raise precondition(f"only a READY campaign can be armed (it is {campaign['state']})")
            fixture = self._fixture(conn, campaign["fixture_id"])
            model = self._model(conn, campaign["contract_version_id"])
            reasons = self._validation_reasons(conn, campaign) + self._bench_reasons(conn, fixture, model, None)
            if reasons:
                raise precondition("the campaign cannot be armed", reasons=reasons)
            tuple_ = self._arming_tuple(fixture, self._contract_hash(conn, campaign))
            campaign = self._move_campaign(conn, campaign, C.ARMED, actor=actor, reason_code="ARMED",
                                           reason="researcher armed the campaign", expected_version=campaign_version,
                                           extra={"armed_tuple_json": _json(tuple_)})
            return self._campaign_view(conn, campaign)

    def start_campaign(self, campaign_id: str, campaign_version: int, actor: Actor) -> dict[str, Any]:
        self._require(actor, RESEARCHER)
        with self.db.transaction() as conn:
            campaign = self._campaign(conn, campaign_id)
            self._check_armed_tuple(conn, campaign)
            campaign = self._move_campaign(conn, campaign, C.RUNNING, actor=actor, reason_code="STARTED",
                                           reason="researcher started the campaign", expected_version=campaign_version)
            return self._campaign_view(conn, campaign)

    def _check_armed_tuple(self, conn: sqlite3.Connection, campaign: sqlite3.Row) -> None:
        if campaign["armed_tuple_json"] is None:
            raise precondition("the campaign was never armed")
        fixture = self._fixture(conn, campaign["fixture_id"])
        model = self._model(conn, campaign["contract_version_id"])
        reasons = self._bench_reasons(conn, fixture, model, json.loads(campaign["armed_tuple_json"]))
        if reasons:
            raise precondition("the bench is not ready", reasons=reasons)

    def pause_campaign(self, campaign_id: str, campaign_version: int, actor: Actor) -> dict[str, Any]:
        self._require(actor, RESEARCHER)
        with self.db.transaction() as conn:
            campaign = self._campaign(conn, campaign_id)
            campaign = self._move_campaign(conn, campaign, C.PAUSING, actor=actor, reason_code="PAUSE_REQUESTED",
                                           reason="researcher paused the campaign", expected_version=campaign_version)
            return self._campaign_view(conn, self._settle(conn, campaign))

    def resume_campaign(self, campaign_id: str, campaign_version: int, actor: Actor) -> dict[str, Any]:
        self._require(actor, RESEARCHER)
        with self.db.transaction() as conn:
            campaign = self._campaign(conn, campaign_id)
            if C(campaign["state"]) is not C.PAUSED:
                raise precondition(f"only a PAUSED campaign can resume (it is {campaign['state']})")
            self._check_armed_tuple(conn, campaign)
            campaign = self._move_campaign(conn, campaign, C.RUNNING, actor=actor, reason_code="RESUMED",
                                           reason="researcher resumed the campaign", expected_version=campaign_version)
            return self._campaign_view(conn, campaign)

    def abort_campaign(self, campaign_id: str, campaign_version: int, actor: Actor, *, disarm: bool = False
                       ) -> dict[str, Any]:
        self._require(actor, RESEARCHER)
        with self.db.transaction() as conn:
            campaign = self._campaign(conn, campaign_id)
            if disarm and C(campaign["state"]) is not C.ARMED:
                raise precondition("only an ARMED campaign can be disarmed")
            campaign = self._move_campaign(
                conn, campaign, C.ABORTING, actor=actor, reason_code="DISARMED" if disarm else "ABORT_REQUESTED",
                reason="researcher disarmed the campaign" if disarm else "researcher aborted the campaign",
                expected_version=campaign_version)
            return self._campaign_view(conn, self._settle(conn, campaign))

    def complete_campaign(self, campaign_id: str, reason: str) -> dict[str, Any]:
        """Stopping rule reached (HLD 04 §9). Called by the Agent when nothing is in flight."""
        with self.db.transaction() as conn:
            campaign = self._campaign(conn, campaign_id)
            busy = conn.execute("SELECT 1 FROM episodes WHERE campaign_id = ? AND state != ?",
                                (campaign_id, E.FINALIZED.value)).fetchone()
            if busy:
                raise precondition("an episode is still in flight")
            campaign = self._move_campaign(conn, campaign, C.COMPLETED, actor=SYSTEM_ACTOR, reason_code="COMPLETED",
                                           reason=reason)
            return self._campaign_view(conn, campaign)

    def clear_lockout(self, campaign_id: str, campaign_version: int, actor: Actor, *, physical_inspection: bool,
                      note: str) -> dict[str, Any]:
        self._require(actor, REVIEWER)
        if physical_inspection is not True or not note.strip():
            raise invalid("clearing a lockout requires confirming a physical inspection and a note")
        with self.db.transaction() as conn:
            campaign = self._campaign(conn, campaign_id)
            campaign = self._move_campaign(conn, campaign, C.DRAFT, actor=actor, reason_code="LOCKOUT_CLEARED",
                                           reason=f"fixture inspected: {note.strip()}", expected_version=campaign_version)
            return self._campaign_view(conn, campaign)

    def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            return self._campaign_view(conn, self._campaign(conn, campaign_id))

    def _pool_usage(self, conn: sqlite3.Connection, campaign_id: str) -> dict[str, int]:
        rows = conn.execute("SELECT role, COUNT(*) AS n FROM episodes WHERE campaign_id = ? GROUP BY role",
                            (campaign_id,)).fetchall()
        usage = {"discovery": 0, "verification": 0}
        for row in rows:
            usage["discovery" if row["role"] == ROLE_DISCOVERY else "verification"] += row["n"]
        return usage

    def _campaign_view(self, conn: sqlite3.Connection, campaign: sqlite3.Row) -> dict[str, Any]:
        outcomes = {r["outcome"] or "IN_FLIGHT": r["n"] for r in conn.execute(
            "SELECT outcome, COUNT(*) AS n FROM episodes WHERE campaign_id = ? GROUP BY outcome", (campaign["id"],))}
        rejected = conn.execute("SELECT COUNT(*) AS n FROM candidates WHERE campaign_id = ? AND state = ?",
                                (campaign["id"], K.REJECTED.value)).fetchone()["n"]
        usage = self._pool_usage(conn, campaign["id"])
        return {
            "id": campaign["id"], "state": campaign["state"], "version": campaign["version"],
            "contractVersionId": campaign["contract_version_id"], "contractHash": self._contract_hash(conn, campaign),
            "fixtureId": campaign["fixture_id"], "planner": {"method": campaign["planner_method"],
                                                            "config": json.loads(campaign["planner_config_json"])},
            "seed": campaign["seed"], "plan": json.loads(campaign["plan_json"]),
            "budget": {"discovery": campaign["discovery_budget"], "verification": campaign["verification_budget"],
                       "discoveryUsed": usage["discovery"], "verificationUsed": usage["verification"]},
            "episodesByOutcome": outcomes, "candidatesRejected": rejected,
            "softwareVersion": campaign["software_version"]}

    # --------------------------------------------------------------- candidates

    def submit_candidate(self, campaign_id: str, planner_sequence: int, conditions: Any, *, planner_reason: str,
                         reason_code: str, role: str = ROLE_DISCOVERY, linked_episode_id: str | None = None,
                         repeat_reason: str | None = None, actor: Actor = SYSTEM_ACTOR) -> dict[str, Any]:
        """Validate a candidate and, if the safety rules approve it, create an AVAILABLE episode.

        Idempotent on (campaign, planner_sequence): a repeat with the same body returns the first
        answer, a repeat with a different body is an ``IDEMPOTENCY_MISMATCH`` (HLD 03 §16).
        """
        if not isinstance(planner_sequence, int) or isinstance(planner_sequence, bool) or planner_sequence < 0:
            raise invalid("planner_sequence must be a non-negative integer")
        if role not in EPISODE_ROLES:
            raise invalid(f"role must be one of {', '.join(sorted(EPISODE_ROLES))}")
        if not isinstance(planner_reason, str) or not planner_reason.strip() or not isinstance(reason_code, str):
            raise invalid("a candidate needs a planner reason and reason code")
        try:
            body = {"conditions": conditions, "plannerReason": planner_reason, "reasonCode": reason_code, "role": role,
                    "linkedEpisodeId": linked_episode_id, "repeatReason": repeat_reason}
            body_hash = _sha256(canonical_json(body))
            conditions_json = _json(conditions)
        except (CanonicalError, TypeError, ValueError) as exc:
            raise invalid(f"candidate is not valid JSON: {exc}") from exc
        with self.db.transaction() as conn:
            campaign = self._campaign(conn, campaign_id)
            existing = conn.execute("SELECT * FROM candidates WHERE campaign_id = ? AND planner_sequence = ?",
                                    (campaign_id, planner_sequence)).fetchone()
            if existing is not None:
                if existing["body_sha256"] != body_hash:
                    raise BackendError("IDEMPOTENCY_MISMATCH", "this sequence number was used for a different candidate")
                return self._candidate_view(conn, existing)
            if C(campaign["state"]) is not C.RUNNING:
                raise precondition(f"candidates are accepted only while RUNNING (campaign is {campaign['state']})")
            if role == ROLE_DISCOVERY and linked_episode_id is not None:
                raise invalid("a discovery candidate cannot link to an earlier episode")
            if role != ROLE_DISCOVERY:
                if not linked_episode_id or not (repeat_reason or "").strip():
                    raise invalid("a verification candidate needs linked_episode_id and repeat_reason (HLD 03 §17.2)")
                if conn.execute("SELECT 1 FROM episodes WHERE id = ? AND campaign_id = ?",
                                (linked_episode_id, campaign_id)).fetchone() is None:
                    raise invalid("linked_episode_id is not an episode of this campaign")
            cand_id = new_id()
            conn.execute(
                "INSERT INTO candidates (id, campaign_id, planner_sequence, body_sha256, conditions_json,"
                " planner_reason, reason_code, role, linked_episode_id, repeat_reason, state, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (cand_id, campaign_id, planner_sequence, body_hash, conditions_json, planner_reason, reason_code, role,
                 linked_episode_id, repeat_reason, K.PROPOSED.value, self._ts()))
            self._candidate_event(conn, campaign, cand_id, K.PROPOSED, None, actor, "CANDIDATE_PROPOSED",
                                  f"{reason_code}: {planner_reason}")
            self._set_candidate(conn, campaign, cand_id, K.PROPOSED, K.VALIDATING, actor, "VALIDATION_STARTED", "checking")
            violations = self._candidate_violations(conn, campaign, conditions, role)
            if violations:
                rejection = _json([{"code": v["code"], "control": v.get("control"), "message": v["message"]}
                                   for v in violations])
                conn.execute("UPDATE candidates SET state = ?, rejection_json = ? WHERE id = ?",
                             (K.REJECTED.value, rejection, cand_id))
                self._candidate_event(conn, campaign, cand_id, K.REJECTED, K.VALIDATING, SYSTEM_ACTOR,
                                      "CANDIDATE_REJECTED", "; ".join(v["code"] for v in violations))
            else:
                self._set_candidate(conn, campaign, cand_id, K.VALIDATING, K.APPROVED, SYSTEM_ACTOR,
                                    "CANDIDATE_APPROVED", "all deterministic checks passed")
                self._materialize(conn, campaign, cand_id, conditions, role, linked_episode_id)
            return self._candidate_view(conn, conn.execute("SELECT * FROM candidates WHERE id = ?", (cand_id,)).fetchone())

    def _candidate_violations(self, conn: sqlite3.Connection, campaign: sqlite3.Row, conditions: Any, role: str
                              ) -> list[dict[str, Any]]:
        usage = self._pool_usage(conn, campaign["id"])
        pool = "discovery" if role == ROLE_DISCOVERY else "verification"
        budget = campaign["discovery_budget"] if pool == "discovery" else campaign["verification_budget"]
        violations: list[dict[str, Any]] = []
        if usage[pool] >= budget:
            violations.append({"code": "BUDGET_EXHAUSTED", "control": None,
                               "message": f"the {pool} pool of {budget} episodes is used up"})
        try:
            fixture = self._fixture(conn, campaign["fixture_id"])
            model = self._model(conn, campaign["contract_version_id"])
            digest = self._contract_hash(conn, campaign)
            decision = check_candidate(model, conditions, fixture_capabilities=frozenset(json.loads(fixture["capabilities_json"])),
                                       contract_hash=digest, expected_hash=digest)
            violations.extend({"code": v.code, "control": v.control, "message": v.message} for v in decision.violations)
        except Exception as exc:     # fail closed: a crash in a rule is a rejection, never an approval
            violations.append({"code": "UNEVALUABLE", "control": None, "message": f"safety check failed: {exc!r}"})
        return violations

    def _candidate_event(self, conn: sqlite3.Connection, campaign: sqlite3.Row, cand_id: str, new: K,
                         previous: K | None, actor: Actor, code: str, reason: str) -> None:
        self._event(conn, "candidate", new.value, previous=previous.value if previous else None,
                    campaign_id=campaign["id"], actor=actor, reason_code=code, reason=reason,
                    contract_hash=self._contract_hash(conn, campaign), fixture_id=campaign["fixture_id"],
                    detail={"candidateId": cand_id})

    def _set_candidate(self, conn: sqlite3.Connection, campaign: sqlite3.Row, cand_id: str, old: K, new: K,
                       actor: Actor, code: str, reason: str) -> None:
        transition(CANDIDATE_TRANSITIONS, old, new, actor_type=",".join(sorted(actor.roles)), actor_id=actor.name,
                   reason_code=code, reason=reason, now=self._now())
        conn.execute("UPDATE candidates SET state = ? WHERE id = ? AND state = ?", (new.value, cand_id, old.value))
        self._candidate_event(conn, campaign, cand_id, new, old, actor, code, reason)

    def _materialize(self, conn: sqlite3.Connection, campaign: sqlite3.Row, cand_id: str, conditions: dict[str, Any],
                     role: str, linked: str | None) -> None:
        episode_id = new_id()
        digest = self._contract_hash(conn, campaign)
        conn.execute(
            "INSERT INTO episodes (id, campaign_id, candidate_id, attempt, state, role, linked_episode_id, requested_json,"
            " contract_hash, fixture_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (episode_id, campaign["id"], cand_id, 1, E.AVAILABLE.value, role, linked, _json(conditions), digest,
             campaign["fixture_id"], self._ts()))
        self._set_candidate(conn, campaign, cand_id, K.APPROVED, K.MATERIALIZED, SYSTEM_ACTOR, "EPISODE_CREATED",
                            f"episode {episode_id} is AVAILABLE")
        self._event(conn, "episode", E.AVAILABLE.value, campaign_id=campaign["id"], episode_id=episode_id, attempt=1,
                    actor=SYSTEM_ACTOR, reason_code="EPISODE_AVAILABLE", reason="approved and durable",
                    contract_hash=digest, fixture_id=campaign["fixture_id"])

    def _candidate_view(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        episode = conn.execute("SELECT id FROM episodes WHERE candidate_id = ?", (row["id"],)).fetchone()
        return {"candidateId": row["id"], "state": row["state"], "plannerSequence": row["planner_sequence"],
                "episodeId": episode["id"] if episode else None,
                "violations": json.loads(row["rejection_json"]) if row["rejection_json"] else []}

    # -------------------------------------------------------------------- bench

    def _episode(self, conn: sqlite3.Connection, episode_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if row is None:
            raise not_found("episode")
        return row

    def _lease(self, conn: sqlite3.Connection, lease_id: str, fixture_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM leases WHERE id = ?", (lease_id,)).fetchone()
        if row is None or row["fixture_id"] != fixture_id:
            raise not_found("lease")      # a token for another fixture learns nothing about this lease
        return row

    def _move_episode(self, conn: sqlite3.Connection, episode: sqlite3.Row, new: E, *, actor: Actor, reason_code: str,
                      reason: str, controller_ts: str | None = None, extra: dict[str, Any] | None = None) -> None:
        current = E(episode["state"])
        try:
            transition(EPISODE_TRANSITIONS, current, new, actor_type=",".join(sorted(actor.roles)), actor_id=actor.name,
                       reason_code=reason_code, reason=reason, now=self._now())
        except IllegalTransition as exc:
            raise precondition(str(exc), state=current.value) from exc
        sets, params = ["state = ?"], [new.value]
        for column, value in (extra or {}).items():
            sets.append(f"{column} = ?")
            params.append(value)
        conn.execute(f"UPDATE episodes SET {', '.join(sets)} WHERE id = ? AND state = ?",
                     (*params, episode["id"], current.value))
        self._event(conn, "episode", new.value, previous=current.value, campaign_id=episode["campaign_id"],
                    episode_id=episode["id"], attempt=episode["attempt"], actor=actor, reason_code=reason_code,
                    reason=reason, contract_hash=episode["contract_hash"], fixture_id=episode["fixture_id"],
                    controller_ts=controller_ts)

    def expire_leases(self) -> list[str]:
        """Mark overdue leases for reconciliation (HLD 03 §9.2). Never makes the episode physically retryable."""
        expired: list[str] = []
        with self.db.transaction() as conn:
            for lease in conn.execute("SELECT * FROM leases WHERE state = 'ACTIVE' AND expires_at < ?",
                                      (self._ts(),)).fetchall():
                conn.execute("UPDATE leases SET state = 'NEEDS_RECONCILIATION' WHERE id = ?", (lease["id"],))
                episode = self._episode(conn, lease["episode_id"])
                self._event(conn, "lease", "NEEDS_RECONCILIATION", previous="ACTIVE", campaign_id=episode["campaign_id"],
                            episode_id=episode["id"], attempt=lease["attempt"], actor=SYSTEM_ACTOR,
                            reason_code="LEASE_EXPIRED", reason="no heartbeat before the lease expired",
                            contract_hash=lease["contract_hash"], fixture_id=lease["fixture_id"],
                            detail={"leaseId": lease["id"]})
                expired.append(lease["id"])
        return expired

    def claim_episode(self, fixture_id: str, controller_instance_id: str) -> dict[str, Any] | None:
        """Atomically lease the next AVAILABLE episode of the fixture's RUNNING campaign, or return None."""
        if not controller_instance_id.strip():
            raise invalid("controller_instance_id is required")
        self.expire_leases()
        with self.db.transaction() as conn:
            campaign = conn.execute("SELECT * FROM campaigns WHERE fixture_id = ? AND state = ?",
                                    (fixture_id, C.RUNNING.value)).fetchone()
            if campaign is None:
                return None
            if self._active_lease(conn, fixture_id) is not None:
                return None            # one physical owner per fixture; reconciliation blocks new work
            episode = conn.execute("SELECT * FROM episodes WHERE campaign_id = ? AND state = ? ORDER BY created_at, id",
                                   (campaign["id"], E.AVAILABLE.value)).fetchone()
            if episode is None:
                return None
            model = self._model(conn, campaign["contract_version_id"])
            lease_id, now = new_id(), self._now()
            conn.execute(
                "INSERT INTO leases (id, episode_id, controller_instance_id, fixture_id, attempt, contract_hash,"
                " issued_at, expires_at, last_heartbeat_at, state) VALUES (?,?,?,?,?,?,?,?,?,'ACTIVE')",
                (lease_id, episode["id"], controller_instance_id, fixture_id, episode["attempt"],
                 episode["contract_hash"], isoformat(now), isoformat(now + timedelta(seconds=self.lease_ttl_s)),
                 isoformat(now)))
            self._move_episode(conn, episode, E.LEASED, actor=SYSTEM_ACTOR, reason_code="LEASE_ISSUED",
                               reason=f"leased to {controller_instance_id}")
            contract_json = conn.execute("SELECT canonical_json FROM contract_versions WHERE id = ?",
                                         (campaign["contract_version_id"],)).fetchone()["canonical_json"]
            fixture = self._fixture(conn, fixture_id)
            sequence = conn.execute("SELECT planner_sequence FROM candidates WHERE id = ?",
                                    (episode["candidate_id"],)).fetchone()["planner_sequence"]
            # Deterministic from the campaign seed and the candidate's sequence, so simulated runs repeat exactly
            # (NFR-03). Real instruments ignore it.
            seed = int(_sha256(f"{campaign['seed']}:{sequence}:{episode['attempt']}")[:8], 16)
            return {"leaseId": lease_id, "episodeId": episode["id"], "attempt": episode["attempt"],
                    "episodeSeed": seed,
                    "contractHash": episode["contract_hash"], "fixtureId": fixture_id,
                    "contract": json.loads(contract_json),
                    "fixtureCapabilities": json.loads(fixture["capabilities_json"]),
                    "requested": json.loads(episode["requested_json"]),
                    "role": episode["role"], "leaseExpiresAt": isoformat(now + timedelta(seconds=self.lease_ttl_s)),
                    "maxEpisodeS": model.safety.max_episode_s,
                    "deadlines": {"leaseTtlS": self.lease_ttl_s, "shutdownAllowanceS": SHUTDOWN_ALLOWANCE_S}}

    def heartbeat(self, lease_id: str, fixture_id: str, phase: str | None = None) -> dict[str, Any]:
        """Extend a lease, record the reported phase, and tell the bench about pending abort or pause requests."""
        expired = False
        with self.db.transaction() as conn:
            lease = self._lease(conn, lease_id, fixture_id)
            if lease["state"] != "ACTIVE":
                raise precondition(f"lease is {lease['state']}", leaseState=lease["state"])
            now = self._now()
            if parse_time(lease["expires_at"]) < now:
                # Record the expiry (this must commit), then refuse outside the transaction.
                conn.execute("UPDATE leases SET state = 'NEEDS_RECONCILIATION' WHERE id = ?", (lease_id,))
                self._event(conn, "lease", "NEEDS_RECONCILIATION", previous="ACTIVE", episode_id=lease["episode_id"],
                            attempt=lease["attempt"], actor=SYSTEM_ACTOR, reason_code="LEASE_EXPIRED",
                            reason="heartbeat arrived after expiry", fixture_id=fixture_id,
                            contract_hash=lease["contract_hash"], detail={"leaseId": lease_id})
                expired = True
            else:
                episode = self._episode(conn, lease["episode_id"])
                campaign = self._campaign(conn, episode["campaign_id"])
                model = self._model(conn, campaign["contract_version_id"])
                # A lease can be extended only up to the episode's maximum duration plus the shutdown allowance.
                hard_stop = parse_time(lease["issued_at"]) + timedelta(
                    seconds=model.safety.max_episode_s + SHUTDOWN_ALLOWANCE_S)
                new_expiry = min(now + timedelta(seconds=self.lease_ttl_s), hard_stop)
                if phase is not None:
                    if phase not in PHASE_STATES:
                        raise invalid(f"unknown phase {phase!r}")
                    if E(episode["state"]) is not PHASE_STATES[phase]:
                        self._move_episode(conn, episode, PHASE_STATES[phase],
                                           actor=Actor(lease["controller_instance_id"], frozenset({"bench"})),
                                           reason_code="PHASE_REPORTED", reason=f"bench reported {phase}")
                conn.execute("UPDATE leases SET last_heartbeat_at = ?, expires_at = ? WHERE id = ?",
                             (isoformat(now), isoformat(new_expiry), lease_id))
                state = C(campaign["state"])
                return {"leaseExpiresAt": isoformat(new_expiry), "abort": state in (C.ABORTING, C.LOCKED_OUT),
                        "pause": state is C.PAUSING}
        assert expired
        raise precondition("lease expired; it needs reconciliation", leaseState="NEEDS_RECONCILIATION")

    def acknowledge_abort(self, lease_id: str, fixture_id: str) -> dict[str, Any]:
        """The bench confirms it reached shutdown after an abort; physical ownership ends here."""
        with self.db.transaction() as conn:
            lease = self._lease(conn, lease_id, fixture_id)
            episode = self._episode(conn, lease["episode_id"])
            if E(episode["state"]) not in (E.SHUTTING_DOWN, E.LOCKOUT, E.SUBMITTING, E.EVIDENCE_PENDING, E.FINALIZED):
                raise precondition("shutdown has not been reported for this episode", state=episode["state"])
            if lease["state"] in ("ACTIVE", "NEEDS_RECONCILIATION"):
                conn.execute("UPDATE leases SET state = 'RELEASED' WHERE id = ?", (lease_id,))
                self._event(conn, "lease", "RELEASED", previous=lease["state"], episode_id=episode["id"],
                            campaign_id=episode["campaign_id"], attempt=lease["attempt"], actor=SYSTEM_ACTOR,
                            reason_code="ABORT_ACKNOWLEDGED", reason="bench confirmed shutdown",
                            contract_hash=lease["contract_hash"], fixture_id=fixture_id, detail={"leaseId": lease_id})
            campaign = self._settle(conn, self._campaign(conn, episode["campaign_id"]))
            return {"campaignState": campaign["state"]}

    def reconcile_lease(self, lease_id: str, resolution: str, note: str, actor: Actor) -> dict[str, Any]:
        """A person decides what an expired lease means. No resolution re-queues the same physical run."""
        self._require(actor, REVIEWER)
        if resolution not in ("not_executed", "evidence_lost"):
            raise invalid("resolution must be not_executed or evidence_lost")
        if not note.strip():
            raise invalid("a reconciliation note is required")
        with self.db.transaction() as conn:
            lease = conn.execute("SELECT * FROM leases WHERE id = ?", (lease_id,)).fetchone()
            if lease is None:
                raise not_found("lease")
            if lease["state"] != "NEEDS_RECONCILIATION":
                raise precondition(f"lease is {lease['state']}, not awaiting reconciliation")
            episode = self._episode(conn, lease["episode_id"])
            conn.execute("UPDATE leases SET state = 'RELEASED' WHERE id = ?", (lease_id,))
            campaign = self._campaign(conn, episode["campaign_id"])
            # Route the episode to a finished state through its legal transitions, then record an INVALID verdict.
            self._finish_without_evidence(conn, episode, campaign, actor, f"{resolution}: {note.strip()}")
            if C(self._campaign(conn, campaign["id"])["state"]) in (C.RUNNING, C.PAUSING, C.ABORTING):
                self._lockout(conn, campaign, reason_code="LEASE_LOST",
                              reason="a lease expired; the fixture must be inspected", actor=SYSTEM_ACTOR)
            return {"episodeId": episode["id"], "outcome": oracle.INVALID_EXPERIMENT}

    def _finish_without_evidence(self, conn: sqlite3.Connection, episode: sqlite3.Row, campaign: sqlite3.Row,
                                 actor: Actor, reason: str) -> None:
        state = E(episode["state"])
        path = [E.EMERGENCY_CUTOFF, E.LOCKOUT, E.FINALIZED] if state in (
            E.PREFLIGHT, E.CONFIGURING, E.SETTLING, E.EXECUTING, E.OBSERVING, E.SHUTTING_DOWN) else \
            [E.PREFLIGHT, E.SHUTTING_DOWN, E.SUBMITTING, E.FINALIZED] if state is E.LEASED else []
        for step in path:
            episode = self._episode(conn, episode["id"])
            extra = {"outcome": oracle.INVALID_EXPERIMENT, "finalized_at": self._ts()} if step is E.FINALIZED else None
            self._move_episode(conn, episode, step, actor=actor, reason_code="RECONCILED", reason=reason, extra=extra)
        conn.execute("INSERT OR REPLACE INTO verdicts VALUES (?,?,?,?,?,?,?,?)",
                     (episode["id"], oracle.INVALID_EXPERIMENT, "LEASE_RECONCILED", reason, "{}", None, "{}", self._ts()))

    # ------------------------------------------------------------------ traces

    def put_trace(self, sha256: str, data: bytes, media_type: str, fixture_id: str) -> dict[str, Any]:
        """Store raw trace bytes under their SHA-256. A repeat upload of the same content is a no-op."""
        if not (isinstance(sha256, str) and len(sha256) == 64 and all(c in "0123456789abcdef" for c in sha256)):
            raise invalid("sha256 must be 64 lowercase hex characters")
        if len(data) > MAX_TRACE_BYTES:
            raise invalid("trace is too large")
        if _sha256(data) != sha256:
            raise BackendError("INTEGRITY_ERROR", "trace content does not match its hash")
        if not media_type.strip() or len(media_type) > 100:
            raise invalid("media_type is required")
        path = self.trace_dir / sha256[:2] / sha256[2:4] / sha256
        with self.db.transaction() as conn:
            self._fixture(conn, fixture_id)
            if conn.execute("SELECT 1 FROM traces WHERE sha256 = ?", (sha256,)).fetchone() is None:
                path.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=path.parent)
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(data)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(tmp, path)
                except BaseException:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
                    raise
                conn.execute("INSERT INTO traces (sha256, episode_id, media_type, bytes, capture_json, path)"
                             " VALUES (?,?,?,?,?,?)", (sha256, None, media_type.strip(), len(data), "{}", str(path)))
        return {"sha256": sha256, "bytes": len(data)}

    # ------------------------------------------------------------------ results

    def submit_result(self, payload: Any, fixture_id: str) -> dict[str, Any]:
        """Accept one episode's evidence, classify it with the Oracle and finalize the episode.

        Idempotent on episode + attempt + manifest hash (HLD 03 §16): the same payload returns the
        stored verdict, a different payload for an accepted attempt is an ``INTEGRITY_ERROR``.
        """
        try:
            result = parse_result(payload)
        except InvalidRequest as exc:
            raise invalid(str(exc)) from exc
        if result.fixture_id != fixture_id:
            raise BackendError("PERMISSION_DENIED", "this token cannot submit for another fixture")
        if manifest_hash(payload) != result.manifest_hash:
            raise BackendError("INTEGRITY_ERROR", "manifestHash does not match the payload")
        with self.db.transaction() as conn:
            episode = self._episode(conn, result.episode_id)
            if episode["fixture_id"] != fixture_id:
                raise not_found("episode")
            stored = conn.execute("SELECT * FROM results WHERE episode_id = ? AND attempt = ?",
                                  (result.episode_id, result.attempt)).fetchone()
            if stored is not None:
                if stored["manifest_hash"] != result.manifest_hash:
                    raise BackendError("INTEGRITY_ERROR", "a different result was already accepted for this attempt")
                return self._verdict_view(conn, episode)
            if result.attempt != episode["attempt"]:
                raise invalid("attempt does not match the episode")
            if result.contract_hash != episode["contract_hash"]:
                raise BackendError("INTEGRITY_ERROR", "contractHash does not match the approved episode")
            lease = self._lease(conn, result.lease_id, fixture_id)
            if lease["episode_id"] != episode["id"]:
                raise invalid("leaseId does not belong to this episode")
            if canonical_json(result.requested) != canonical_json(json.loads(episode["requested_json"])):
                raise BackendError("INTEGRITY_ERROR", "requested conditions differ from the approved episode")
            state = E(episode["state"])
            if result.safety_trip:
                if state not in (E.EMERGENCY_CUTOFF, E.LOCKOUT):
                    raise precondition("a safety trip is reported but the episode never reached cutoff", state=state.value)
            elif state is not E.SHUTTING_DOWN or not result.shutdown_confirmed:
                raise precondition("evidence is accepted only after confirmed shutdown", state=state.value)
            for trace in result.traces:
                if conn.execute("SELECT 1 FROM traces WHERE sha256 = ?", (trace["sha256"],)).fetchone() is None:
                    raise precondition(f"trace {trace['sha256']} has not been uploaded")

            campaign = self._campaign(conn, episode["campaign_id"])
            model = self._model(conn, campaign["contract_version_id"])
            verdict = self._classify(model, result)
            now = self._ts()
            conn.execute("INSERT INTO results VALUES (?,?,?,?,?)",
                         (episode["id"], result.attempt, result.manifest_hash, _json(payload), now))
            self._store_observations(conn, model, episode, result)
            statuses = {rid: ("FAIL" if rid in verdict.violated else "INCONCLUSIVE" if rid in verdict.inconclusive else "PASS")
                        for rid in verdict.margins}
            conn.execute("INSERT INTO verdicts VALUES (?,?,?,?,?,?,?,?)",
                         (episode["id"], verdict.outcome, verdict.reason_code, verdict.reason, _json(verdict.margins),
                          verdict.robustness, _json(statuses), now))
            for trace in result.traces:
                conn.execute("UPDATE traces SET episode_id = ? WHERE sha256 = ? AND episode_id IS NULL",
                             (episode["id"], trace["sha256"]))
            if state is E.SHUTTING_DOWN:
                self._move_episode(conn, episode, E.SUBMITTING, actor=SYSTEM_ACTOR, reason_code="EVIDENCE_RECEIVED",
                                   reason="result payload accepted")
                episode = self._episode(conn, episode["id"])
            self._move_episode(conn, episode, E.FINALIZED, actor=SYSTEM_ACTOR, reason_code=verdict.reason_code,
                               reason=f"{verdict.outcome}: {verdict.reason}",
                               extra={"outcome": verdict.outcome, "finalized_at": now})
            if lease["state"] in ("ACTIVE", "NEEDS_RECONCILIATION"):
                conn.execute("UPDATE leases SET state = 'RELEASED' WHERE id = ?", (lease["id"],))
            if (verdict.outcome == oracle.SAFETY_ABORT
                    and C(self._campaign(conn, campaign["id"])["state"]) in (C.ARMED, C.RUNNING, C.PAUSING, C.ABORTING)):
                self._lockout(conn, campaign, reason_code="SAFETY_TRIP", reason=verdict.reason, actor=SYSTEM_ACTOR)
            self._settle(conn, campaign)
            return self._verdict_view(conn, self._episode(conn, episode["id"]))

    def _classify(self, model: ContractModel, result: EpisodeResult) -> oracle.Verdict:
        errors: list[str] = []
        if result.instrument_fault:
            errors.append("instrument fault reported")
        if not result.rail_settled and not result.safety_trip:
            errors.append("rail did not settle")
        errors.extend(f"timeout: {t}" for t in result.timeouts)
        evidence = oracle.Evidence({name: m.value for name, m in result.measured.items()}, result.safety_trip,
                                   tuple(errors))
        try:
            return oracle.classify(model, result.requested, evidence)
        except InvalidRequest as exc:
            raise invalid(f"result cannot be classified: {exc}") from exc

    def _store_observations(self, conn: sqlite3.Connection, model: ContractModel, episode: sqlite3.Row,
                            result: EpisodeResult) -> None:
        tracked = {rule.metric: rule.tracks for rule in model.validity or []}
        for name, measured in result.measured.items():
            spec = model.observations.get(name) if model.observations else None
            uncertainty = measured.uncertainty if measured.uncertainty is not None else (spec.uncertainty if spec else None)
            requested = result.requested.get(tracked[name]) if name in tracked else None
            conn.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?)",
                         (episode["id"], result.attempt, name, requested if isinstance(requested, (int, float)) else None,
                          measured.value, uncertainty, _json({"reported": True, "known": spec is not None})))

    def _verdict_view(self, conn: sqlite3.Connection, episode: sqlite3.Row) -> dict[str, Any]:
        verdict = conn.execute("SELECT * FROM verdicts WHERE episode_id = ?", (episode["id"],)).fetchone()
        return {"episodeId": episode["id"], "state": episode["state"], "outcome": verdict["outcome"],
                "reasonCode": verdict["reason_code"], "reason": verdict["reason"],
                "margins": json.loads(verdict["margins_json"]), "robustness": verdict["robustness"],
                "requirements": json.loads(verdict["requirements_json"])}

    # ------------------------------------------------------------------ queries

    def get_episode(self, episode_id: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            episode = self._episode(conn, episode_id)
            view = {"id": episode["id"], "campaignId": episode["campaign_id"], "state": episode["state"],
                    "role": episode["role"], "attempt": episode["attempt"], "linkedEpisodeId": episode["linked_episode_id"],
                    "requested": json.loads(episode["requested_json"]), "contractHash": episode["contract_hash"],
                    "fixtureId": episode["fixture_id"], "outcome": episode["outcome"]}
            observations = conn.execute("SELECT * FROM observations WHERE episode_id = ? ORDER BY metric", (episode_id,)).fetchall()
            view["measured"] = {o["metric"]: {"value": o["measured"], "uncertainty": o["uncertainty"],
                                              "requested": o["requested"]} for o in observations}
            if episode["outcome"]:
                view["verdict"] = self._verdict_view(conn, episode)
            return view

    def episode_history(self, campaign_id: str) -> list[dict[str, Any]]:
        """Finalized episodes in the shape planners take as history (plus role and id)."""
        with self.db.transaction() as conn:
            self._campaign(conn, campaign_id)
            rows = conn.execute(
                "SELECT e.id, e.role, e.linked_episode_id, e.requested_json, e.outcome, v.robustness FROM episodes e"
                " LEFT JOIN verdicts v ON v.episode_id = e.id WHERE e.campaign_id = ? AND e.state = ?"
                " ORDER BY e.created_at, e.id", (campaign_id, E.FINALIZED.value)).fetchall()
            return [{"episodeId": r["id"], "role": r["role"], "outcome": r["outcome"],
                     "linkedEpisodeId": r["linked_episode_id"], "conditions": json.loads(r["requested_json"]),
                     "robustness": r["robustness"] if r["outcome"] in ("PASS", "DUT_FAILURE") else None} for r in rows]

    def campaign_contract(self, campaign_id: str) -> dict[str, Any]:
        """The campaign's contract as canonical JSON (what Decision and the Agent plan against)."""
        with self.db.transaction() as conn:
            campaign = self._campaign(conn, campaign_id)
            row = conn.execute("SELECT canonical_json, contract_hash FROM contract_versions WHERE id = ?",
                               (campaign["contract_version_id"],)).fetchone()
            return {"contract": json.loads(row["canonical_json"]), "contractHash": row["contract_hash"]}

    def next_planner_sequence(self, campaign_id: str) -> int:
        with self.db.transaction() as conn:
            self._campaign(conn, campaign_id)
            row = conn.execute("SELECT MAX(planner_sequence) AS m FROM candidates WHERE campaign_id = ?",
                               (campaign_id,)).fetchone()
            return 0 if row["m"] is None else row["m"] + 1

    def in_flight_count(self, campaign_id: str) -> int:
        """Episodes that exist but are not finished: the Agent plans nothing while one is running."""
        with self.db.transaction() as conn:
            self._campaign(conn, campaign_id)
            return conn.execute("SELECT COUNT(*) AS n FROM episodes WHERE campaign_id = ? AND state != ?",
                                (campaign_id, E.FINALIZED.value)).fetchone()["n"]

    def consecutive_rejections(self, campaign_id: str) -> int:
        """How many of the most recent candidates in a row were rejected (a planner or contract-design smell)."""
        with self.db.transaction() as conn:
            self._campaign(conn, campaign_id)
            count = 0
            for row in conn.execute("SELECT state FROM candidates WHERE campaign_id = ? ORDER BY planner_sequence DESC",
                                    (campaign_id,)):
                if row["state"] != K.REJECTED.value:
                    break
                count += 1
            return count

    def session_log(self, campaign_id: str, trigger_episode_id: str) -> list[dict[str, Any]]:
        """Every verification candidate linked to ``trigger_episode_id`` in submission order, with its result.

        ``outcome`` is the episode outcome, ``"REJECTED"`` for a candidate the safety rules refused, or
        None while the episode is still running. The Agent replays this log to rebuild where it was.
        """
        with self.db.transaction() as conn:
            self._campaign(conn, campaign_id)
            rows = conn.execute(
                "SELECT c.planner_sequence, c.role, c.conditions_json, c.state, c.id AS candidate_id,"
                " e.id AS episode_id, e.outcome FROM candidates c LEFT JOIN episodes e ON e.candidate_id = c.id"
                " WHERE c.campaign_id = ? AND c.linked_episode_id = ? ORDER BY c.planner_sequence",
                (campaign_id, trigger_episode_id)).fetchall()
            return [{"sequence": r["planner_sequence"], "role": r["role"], "conditions": json.loads(r["conditions_json"]),
                     "outcome": "REJECTED" if r["state"] == K.REJECTED.value else r["outcome"],
                     "episodeId": r["episode_id"]} for r in rows]

    def record_counterexample(self, campaign_id: str, original_episode_id: str, minimized: dict[str, Any],
                              intervals: dict[str, Any], reproductions: int, attempts: int,
                              origin: str = "unknown") -> dict[str, Any]:
        """Store a confirmed, minimized counterexample (HLD 08 §4). One per original episode."""
        if origin not in ("seeded", "natural", "unknown"):
            raise invalid("origin must be seeded, natural or unknown")
        if not (isinstance(reproductions, int) and isinstance(attempts, int) and 0 <= reproductions <= attempts):
            raise invalid("reproductions must be between 0 and attempts")
        with self.db.transaction() as conn:
            self._campaign(conn, campaign_id)
            episode = self._episode(conn, original_episode_id)
            if episode["campaign_id"] != campaign_id:
                raise invalid("the original episode belongs to another campaign")
            existing = conn.execute("SELECT id FROM counterexamples WHERE original_episode_id = ?",
                                    (original_episode_id,)).fetchone()
            if existing:
                return {"counterexampleId": existing["id"], "created": False}
            cx_id = new_id()
            conn.execute("INSERT INTO counterexamples VALUES (?,?,?,?,?,?,?,?,?)",
                         (cx_id, campaign_id, original_episode_id, _json(minimized), _json(intervals), reproductions,
                          attempts, origin, self._ts()))
            self._event(conn, "campaign", "COUNTEREXAMPLE_RECORDED", campaign_id=campaign_id, episode_id=original_episode_id,
                        actor=SYSTEM_ACTOR, reason_code="COUNTEREXAMPLE", reason=f"reproduced {reproductions} of {attempts}",
                        detail={"counterexampleId": cx_id})
            return {"counterexampleId": cx_id, "created": True}

    def counterexamples(self, campaign_id: str) -> list[dict[str, Any]]:
        with self.db.transaction() as conn:
            self._campaign(conn, campaign_id)
            return [{"id": r["id"], "originalEpisodeId": r["original_episode_id"], "minimized": json.loads(r["minimized_json"]),
                     "intervals": json.loads(r["intervals_json"]), "reproductions": r["reproductions"],
                     "attempts": r["attempts"], "origin": r["origin"]}
                    for r in conn.execute("SELECT * FROM counterexamples WHERE campaign_id = ? ORDER BY created_at, id",
                                          (campaign_id,))]

    def rejected_conditions(self, campaign_id: str) -> list[dict[str, Any]]:
        with self.db.transaction() as conn:
            self._campaign(conn, campaign_id)
            return [{"conditions": json.loads(r["conditions_json"]), "violations": json.loads(r["rejection_json"])}
                    for r in conn.execute("SELECT conditions_json, rejection_json FROM candidates"
                                          " WHERE campaign_id = ? AND state = ? ORDER BY planner_sequence",
                                          (campaign_id, K.REJECTED.value))]

    def list_events(self, campaign_id: str, after_id: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT * FROM events WHERE campaign_id = ? AND id > ? ORDER BY id LIMIT ?",
                                (campaign_id, after_id, max(1, min(limit, 5000)))).fetchall()
            return [{"id": r["id"], "entity": r["entity"], "episodeId": r["episode_id"], "attempt": r["attempt"],
                     "previousState": r["previous_state"], "newState": r["new_state"], "actorType": r["actor_type"],
                     "actorId": r["actor_id"], "reasonCode": r["reason_code"], "reason": r["reason"],
                     "backendTs": r["backend_ts"], "contractHash": r["contract_hash"], "fixtureId": r["fixture_id"]}
                    for r in rows]
