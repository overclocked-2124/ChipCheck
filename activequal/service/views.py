"""Read-only views the Console needs (HLD 09 §5): lists, the live lease, episode detail, report JSON, comparison.

Everything here reads through Backend's public methods, the report builder, and read-only SQL on ``backend.db``.
Nothing writes. Statistics are computed here, never in the browser (HLD 09 §9).
"""

from __future__ import annotations

import json
from typing import Any

from activequal.service import report, stats
from activequal.service.backend import Backend
from activequal.service.errors import invalid, not_found

MAX_COMPARE = 50


def list_contracts(backend: Backend) -> list[dict[str, Any]]:
    """Every contract version, newest first, with its approval state (HLD 09 §5 Contracts)."""
    rows = backend.db.query("SELECT contract_key, version FROM contract_versions ORDER BY created_at DESC, version DESC")
    out = []
    for row in rows:
        summary = backend.get_contract(row["contract_key"], row["version"])
        contract = summary.pop("contract", {}) or {}
        setup = contract.get("setup", {}) if isinstance(contract, dict) else {}
        out.append({**summary, "dut": setup.get("dut"), "fixture": setup.get("fixture")})
    return out


def list_fixtures(backend: Backend) -> list[dict[str, Any]]:
    from activequal.service.queries import fixture_view
    return [fixture_view(backend, r["id"]) for r in backend.db.query("SELECT id FROM fixtures ORDER BY id")]


def _lease(row: Any) -> dict[str, Any]:
    return {"id": row["id"], "episodeId": row["episode_id"], "owner": row["controller_instance_id"],
            "attempt": row["attempt"], "issuedAt": row["issued_at"], "expiresAt": row["expires_at"],
            "lastHeartbeatAt": row["last_heartbeat_at"], "state": row["state"]}


def campaign_lease(backend: Backend, campaign_id: str) -> dict[str, Any]:
    """The live lease of this campaign, if any: owner, real last heartbeat, expiry, or NEEDS_RECONCILIATION."""
    backend.get_campaign(campaign_id)
    row = backend.db.one(
        "SELECT l.* FROM leases l JOIN episodes e ON e.id = l.episode_id WHERE e.campaign_id = ?"
        " AND l.state IN ('ACTIVE', 'NEEDS_RECONCILIATION') ORDER BY l.issued_at DESC LIMIT 1", (campaign_id,))
    return {"lease": None if row is None else _lease(row)}


def campaign_contract(backend: Backend, campaign_id: str) -> dict[str, Any]:
    """The contract the campaign runs under, with the arming identity (hashes, calibration) and expected runtime."""
    facts = report.campaign_facts(backend, campaign_id)
    view, contract = facts["view"], facts["contract"]
    max_episode_s = (contract.get("safety") or {}).get("maxEpisodeS")
    remaining = (view["budget"]["discovery"] - view["budget"]["discoveryUsed"]
                 + view["budget"]["verification"] - view["budget"]["verificationUsed"])
    return {"contractId": facts["contractRow"]["contract_key"], "version": facts["contractRow"]["version"],
            "contractHash": view["contractHash"], "contract": contract, "approvals": facts["approvals"],
            "approvalsRequired": facts["approvalsRequired"], "armed": facts["armed"], "calibration": facts["calibration"],
            "maxEpisodeS": max_episode_s,
            "expectedMaxRuntimeS": None if not isinstance(max_episode_s, (int, float)) else max_episode_s * max(0, remaining)}


def campaign_records(backend: Backend, campaign_id: str) -> dict[str, Any]:
    """Every episode with requested and measured values, verdict and planner reason, plus refused candidates."""
    return {"episodes": report.collect_episodes(backend, campaign_id),
            "rejected": report.rejected_candidates(backend, campaign_id)}


def episode_detail(backend: Backend, episode_id: str) -> dict[str, Any]:
    """``Backend.get_episode`` plus the planner's reason, bench quality flags and events, traces and leases."""
    view = backend.get_episode(episode_id)
    record = next((r for r in report.collect_episodes(backend, view["campaignId"]) if r["episodeId"] == episode_id), None)
    leases = [_lease(r) for r in backend.db.query("SELECT * FROM leases WHERE episode_id = ? ORDER BY issued_at",
                                                  (episode_id,))]
    result = backend.db.one("SELECT payload_json, manifest_hash FROM results WHERE episode_id = ? ORDER BY attempt DESC",
                            (episode_id,))
    payload = json.loads(result["payload_json"]) if result else {}
    traces = [{"sha256": t["sha256"], "mediaType": t["media_type"], "bytes": t["bytes"]}
              for t in backend.db.query("SELECT sha256, media_type, bytes FROM traces WHERE episode_id = ?", (episode_id,))]
    return {**view, "planner": record["planner"] if record else None,
            "plannerSequence": record["plannerSequence"] if record else None,
            "discoveryIndex": record["discoveryIndex"] if record else None,
            "quality": payload.get("quality"), "benchEvents": payload.get("events", []),
            "safetyTrip": payload.get("safetyTrip"), "manifestHash": result["manifest_hash"] if result else None,
            "traces": traces, "leases": leases,
            "createdAt": record["createdAt"] if record else None, "finalizedAt": record["finalizedAt"] if record else None}


def campaign_report(backend: Backend, campaign_id: str) -> dict[str, Any]:
    return report.build_report(backend, campaign_id)


def compare(backend: Backend, campaign_ids: list[str]) -> dict[str, Any]:
    """Episodes to the first confirmed failure per campaign, and the HLD 06 §8 comparison grouped by contract hash."""
    ids = [c for c in dict.fromkeys(campaign_ids) if c]
    if not ids:
        raise invalid("name at least one campaign")
    if len(ids) > MAX_COMPARE:
        raise invalid(f"compare at most {MAX_COMPARE} campaigns at once")
    rows, records = [], []
    for cid in ids:
        if backend.db.one("SELECT 1 FROM campaigns WHERE id = ?", (cid,)) is None:
            raise not_found("campaign")
        rep = report.build_report(backend, cid)
        profile = rep["identity"]["contractHash"][:12]
        record = report.campaign_record(rep, profile)
        records.append(record)
        rows.append({"campaignId": cid, "planner": record["planner"], "seed": rep["identity"]["planner"]["seed"],
                     "state": rep["state"], "contract": profile,
                     "firstConfirmedFailureAt": record["episodes_to_failure"],
                     "firstObservedFailureAt": rep["metrics"]["firstObservedFailureIndex"],
                     "censoredAt": None if record["episodes_to_failure"] is not None else record["budget"],
                     "discoveryUsed": rep["budget"]["discovery"]["used"], "discoveryBudget": rep["budget"]["discovery"]["allowed"],
                     "verificationUsed": rep["budget"]["verification"]["used"], "stoppedEarly": record["stopped_early"],
                     "resultKind": rep["result"]["kind"]})
    return {"campaigns": rows, "comparison": stats.compare_planners(records)}
