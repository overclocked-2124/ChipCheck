"""Read-only queries the HTTP layer needs that are not Backend operations (fixtures, listings, metrics)."""

from __future__ import annotations

import json
from typing import Any

from activequal.service.backend import Backend
from activequal.service.errors import not_found


def fixture_view(backend: Backend, fixture_id: str) -> dict[str, Any]:
    row = backend.db.one("SELECT * FROM fixtures WHERE id = ?", (fixture_id,))
    if row is None:
        raise not_found("fixture")
    calibration = None
    if row["current_calibration_id"]:
        cal = backend.db.one("SELECT * FROM calibrations WHERE id = ?", (row["current_calibration_id"],))
        calibration = {"id": cal["id"], "channels": json.loads(cal["channels_json"]), "meter": cal["meter_identity"],
                       "operator": cal["operator"], "createdAt": cal["created_at"], "validUntil": cal["valid_until"]}
    return {"id": row["id"], "revision": row["revision"], "capabilities": json.loads(row["capabilities_json"]),
            "calibration": calibration, "health": json.loads(row["health_json"]) if row["health_json"] else None,
            "healthAt": row["health_at"], "approvedMcuFirmwareSha256": row["approved_mcu_firmware_sha256"]}


def running_campaign_ids(backend: Backend) -> list[str]:
    return [r["id"] for r in backend.db.query("SELECT id FROM campaigns WHERE state = 'RUNNING' ORDER BY created_at")]


def list_campaigns(backend: Backend, limit: int = 100) -> list[dict[str, Any]]:
    rows = backend.db.query("SELECT id FROM campaigns ORDER BY created_at DESC, id DESC LIMIT ?", (max(1, min(limit, 500)),))
    return [backend.get_campaign(r["id"]) for r in rows]


def metrics_text(backend: Backend) -> str:
    """Prometheus text format (HLD 08 §7)."""
    lines: list[str] = []

    def family(name: str, help_text: str, rows: list[tuple[dict[str, str], float]]) -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        for labels, value in rows:
            rendered = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
            lines.append(f"{name}{{{rendered}}} {value:g}" if rendered else f"{name} {value:g}")

    q = backend.db.query
    family("activequal_episodes", "Episodes by outcome and role", [
        ({"outcome": r["outcome"] or "IN_FLIGHT", "role": r["role"]}, r["n"]) for r in q(
            "SELECT outcome, role, COUNT(*) AS n FROM episodes GROUP BY outcome, role")])
    rejections: dict[str, int] = {}
    for r in q("SELECT rejection_json FROM candidates WHERE state = 'REJECTED'"):
        for violation in json.loads(r["rejection_json"] or "[]"):
            rejections[violation["code"]] = rejections.get(violation["code"], 0) + 1
    family("activequal_candidate_rejections", "Rejected candidates by reason", [
        ({"reason": code}, n) for code, n in sorted(rejections.items())])
    family("activequal_campaigns", "Campaigns by state", [
        ({"state": r["state"]}, r["n"]) for r in q("SELECT state, COUNT(*) AS n FROM campaigns GROUP BY state")])
    family("activequal_lease_expiries", "Leases that expired and needed reconciliation", [
        ({}, q("SELECT COUNT(*) AS n FROM events WHERE reason_code = 'LEASE_EXPIRED'")[0]["n"])])
    family("activequal_safety_trips", "Safety trips recorded", [
        ({}, q("SELECT COUNT(*) AS n FROM verdicts WHERE outcome = 'SAFETY_ABORT'")[0]["n"])])
    lines.append("")
    return "\n".join(lines)
