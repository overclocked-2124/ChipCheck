"""Campaign report (WP15, FR-15): a machine-readable dict and a Markdown rendering in PRD §19.2 result language.

``build_report`` reads a campaign only through Backend's public methods and read-only SQL on ``backend.db``;
it never writes. Every claim carries the episode ids it rests on (FR-15). The wording is deliberately narrow:
a pass applies only to the tested conditions, "no failure found" is always "within the tested conditions and
budget", and the origin of a failure (seeded, natural, unknown) is the stored label, never inferred.

Episode order is the planner's submission order (``candidates.planner_sequence``). Timestamps cannot order
episodes: a fixed test clock gives every row the same time.
"""

from __future__ import annotations

import json
from typing import Any

from activequal.service import oracle, stats
from activequal.service.backend import ROLE_DISCOVERY, Backend
from activequal.service.states import CampaignState

REPORT_SCHEMA = "activequal.report/1"
# States a campaign stops in. LOCKED_OUT can later return to DRAFT; a report taken then records the lockout
# as it stood, and a later export records what followed.
TERMINAL_STATES = frozenset({"COMPLETED", "ABORTED", "LOCKED_OUT"})
CAMPAIGN_STATES = frozenset(s.value for s in CampaignState)

# PRD §19.2 result language.
NO_FAILURE_SENTENCE = "No failure found within the tested conditions and budget."
KIND_COUNTEREXAMPLE = "COUNTEREXAMPLE_FOUND"
KIND_NO_COUNTEREXAMPLE = "NO_COUNTEREXAMPLE_FOUND"
KIND_UNCONFIRMED = "FAILURE_OBSERVED_NOT_CONFIRMED"
KIND_INCONCLUSIVE = "CAMPAIGN_INCONCLUSIVE"
KIND_SAFETY_ABORT = "SAFETY_ABORT"
INCONCLUSIVE_FRACTION = 0.25     # invalid share of all episodes at or above which the campaign is called inconclusive

ORIGIN_LABELS = {"seeded": "seeded (the fault was injected on purpose)", "natural": "natural (found, not injected)",
                 "unknown": "unknown (origin not labelled)"}

LIMITATIONS = (
    "A pass applies only to the conditions that were tested, at the budget that was used. Conditions that were not "
    "tested are not covered by any statement in this report.",
    "This report is not a compliance, conformity or approval statement and gives no assurance about untested conditions "
    "or about other units of the device.",
    "Verdicts follow the approved contract version above; limits, guard bands and measurement uncertainties are the "
    "contract's. Requested and measured values are shown separately because they differ.",
    "Episodes to first failure counts the discovery pool only. Verification episodes (replays, minimization, "
    "necessity probes, bracketing) are reported separately and never count toward it.",
)


def to_json(value: Any, indent: int | None = None) -> str:
    """Canonical JSON text: sorted keys, fixed separators, no NaN. Used for report.json and the bundle."""
    if indent is None:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return json.dumps(value, sort_keys=True, indent=indent, ensure_ascii=False, allow_nan=False)


def _pool(role: str) -> str:
    return "discovery" if role == ROLE_DISCOVERY else "verification"


def _loads(text: str | None, default: Any = None) -> Any:
    return default if text is None else json.loads(text)


# ------------------------------------------------------------------------------ data access

def campaign_facts(backend: Backend, campaign_id: str) -> dict[str, Any]:
    """Campaign, contract, approvals, calibration and arming tuple (public view plus read-only SQL)."""
    view = backend.get_campaign(campaign_id)
    db = backend.db
    campaign = db.one("SELECT * FROM campaigns WHERE id = ?", (campaign_id,))
    version = db.one("SELECT * FROM contract_versions WHERE id = ?", (campaign["contract_version_id"],))
    contract = backend.get_contract(version["contract_key"], version["version"])
    approvals = [{"reviewer": r["reviewer"], "approvedAt": r["approved_at"]} for r in db.query(
        "SELECT reviewer, approved_at FROM contract_approvals WHERE contract_version_id = ? ORDER BY approved_at, reviewer",
        (version["id"],))]
    armed = _loads(campaign["armed_tuple_json"], {})
    calibration = None
    if armed.get("calibrationId"):
        row = db.one("SELECT * FROM calibrations WHERE id = ?", (armed["calibrationId"],))
        if row is not None:
            calibration = {"id": row["id"], "fixtureId": row["fixture_id"], "channels": json.loads(row["channels_json"]),
                           "meterIdentity": row["meter_identity"], "operator": row["operator"],
                           "createdAt": row["created_at"], "validUntil": row["valid_until"]}
    fixture = db.one("SELECT revision FROM fixtures WHERE id = ?", (campaign["fixture_id"],))
    return {"view": view, "contractRow": version, "contract": contract["contract"], "approvals": approvals,
            "approvalsRequired": version["approvals_required"], "armed": armed, "calibration": calibration,
            "fixtureRevision": fixture["revision"] if fixture else None}


def collect_episodes(backend: Backend, campaign_id: str) -> list[dict[str, Any]]:
    """One record per episode in planner order, in the HLD 08 §5 shape (including invalid and aborted episodes)."""
    db = backend.db
    campaign = db.one("SELECT planner_method, software_version FROM campaigns WHERE id = ?", (campaign_id,))
    if campaign is None:
        backend.get_campaign(campaign_id)          # raises the standard not-found error
    rows = db.query(
        "SELECT e.*, c.planner_sequence, c.planner_reason, c.reason_code AS cand_reason_code, c.repeat_reason"
        " FROM episodes e JOIN candidates c ON c.id = e.candidate_id WHERE e.campaign_id = ?"
        " ORDER BY c.planner_sequence", (campaign_id,))
    records, discovery_index = [], 0
    for row in rows:
        pool = _pool(row["role"])
        if pool == "discovery":
            discovery_index += 1
        verdict = db.one("SELECT * FROM verdicts WHERE episode_id = ?", (row["id"],))
        measured = {o["metric"]: {"value": o["measured"], "uncertainty": o["uncertainty"], "requested": o["requested"]}
                    for o in db.query("SELECT * FROM observations WHERE episode_id = ? AND attempt = ? ORDER BY metric",
                                      (row["id"], row["attempt"]))}
        result = db.one("SELECT payload_json FROM results WHERE episode_id = ? AND attempt = ?", (row["id"], row["attempt"]))
        payload = json.loads(result["payload_json"]) if result else {}
        records.append({
            "episodeId": row["id"], "campaignId": campaign_id, "attempt": row["attempt"], "role": row["role"],
            "pool": pool, "state": row["state"], "outcome": row["outcome"], "linkedEpisodeId": row["linked_episode_id"],
            "plannerSequence": row["planner_sequence"], "discoveryIndex": discovery_index if pool == "discovery" else None,
            "requested": json.loads(row["requested_json"]), "measured": measured,
            "verdict": None if verdict is None else {
                "outcome": verdict["outcome"], "reasonCode": verdict["reason_code"], "reason": verdict["reason"],
                "margins": json.loads(verdict["margins_json"]), "robustness": verdict["robustness"],
                "requirements": json.loads(verdict["requirements_json"])},
            "planner": {"method": campaign["planner_method"], "reason": row["planner_reason"],
                        "reasonCode": row["cand_reason_code"], "repeatReason": row["repeat_reason"]},
            "traces": [t["sha256"] for t in payload.get("traces", [])],
            "events": payload.get("events", []), "quality": payload.get("quality"),
            "contractHash": row["contract_hash"], "fixtureId": row["fixture_id"], "software": campaign["software_version"],
            "createdAt": row["created_at"], "finalizedAt": row["finalized_at"]})
    return records


def rejected_candidates(backend: Backend, campaign_id: str) -> list[dict[str, Any]]:
    """Candidates the safety rules refused: they have no episode and spend no budget, but nothing is dropped."""
    return [{"candidateId": r["id"], "plannerSequence": r["planner_sequence"], "role": r["role"],
             "conditions": json.loads(r["conditions_json"]), "violations": json.loads(r["rejection_json"] or "[]"),
             "plannerReason": r["planner_reason"], "reasonCode": r["reason_code"]}
            for r in backend.db.query("SELECT * FROM candidates WHERE campaign_id = ? AND state = 'REJECTED'"
                                      " ORDER BY planner_sequence", (campaign_id,))]


def _all_events(backend: Backend, campaign_id: str) -> list[dict[str, Any]]:
    events, after = [], 0
    while True:
        page = backend.list_events(campaign_id, after_id=after, limit=5000)
        events.extend(page)
        if len(page) < 5000:
            return events
        after = page[-1]["id"]


# ------------------------------------------------------------------------------ formatting helpers

def _num(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _conditions(conditions: dict[str, Any]) -> str:
    return ", ".join(f"{k}={_num(v)}" for k, v in sorted(conditions.items())) or "(none)"


def _ids(ids: list[str]) -> str:
    return ", ".join(ids) if ids else "none"


def _rate(summary: dict[str, Any]) -> str:
    text = f"{summary['numerator']}/{summary['denominator']}"
    if summary["wilson95"] is not None:
        low, high = summary["wilson95"]
        text += f" (rate {summary['rate']:.3f}, 95% Wilson interval {low:.3f} to {high:.3f})"
    return text


# ------------------------------------------------------------------------------ build

def build_report(backend: Backend, campaign_id: str) -> dict[str, Any]:
    facts = campaign_facts(backend, campaign_id)
    view, contract = facts["view"], facts["contract"]
    episodes = collect_episodes(backend, campaign_id)
    rejected = rejected_candidates(backend, campaign_id)
    by_id = {e["episodeId"]: e for e in episodes}
    state = view["state"]
    partial = state not in TERMINAL_STATES
    budget = view["budget"]

    # ----- outcomes: every episode is counted, nothing is dropped
    by_outcome: dict[str, list[str]] = {}
    by_reason: dict[str, dict[str, list[str]]] = {}
    pools = {"discovery": {}, "verification": {}}
    by_role: dict[str, int] = {}
    for e in episodes:
        outcome = e["outcome"] or "IN_FLIGHT"
        by_outcome.setdefault(outcome, []).append(e["episodeId"])
        pools[e["pool"]][outcome] = pools[e["pool"]].get(outcome, 0) + 1
        by_role[e["role"]] = by_role.get(e["role"], 0) + 1
        if e["verdict"] is not None:
            by_reason.setdefault(outcome, {}).setdefault(e["verdict"]["reasonCode"], []).append(e["episodeId"])
    invalid = by_outcome.get(oracle.INVALID_EXPERIMENT, [])
    inconclusive = [i for i in invalid if by_id[i]["verdict"] and by_id[i]["verdict"]["reasonCode"] == oracle.INCONCLUSIVE]
    safety_aborts = by_outcome.get(oracle.SAFETY_ABORT, [])
    failures = by_outcome.get(oracle.DUT_FAILURE, [])
    passes = by_outcome.get(oracle.PASS, [])
    valid = len(passes) + len(failures)
    total = len(episodes)
    outcomes = {
        "total": total, "valid": valid,
        "counts": {k: len(v) for k, v in sorted(by_outcome.items())},
        "episodeIds": {k: v for k, v in sorted(by_outcome.items())},
        "invalid": len(invalid), "inconclusive": len(inconclusive), "safetyAborts": len(safety_aborts),
        "invalidByReason": {k: len(v) for k, v in sorted(by_reason.get(oracle.INVALID_EXPERIMENT, {}).items())},
        "byPool": {p: dict(sorted(c.items())) for p, c in pools.items()},
        "byRole": dict(sorted(by_role.items())),
        "candidatesRejected": {
            "count": len(rejected), "candidateIds": [r["candidateId"] for r in rejected],
            "byCode": _count([v["code"] for r in rejected for v in r["violations"]]),
            "note": "refused before any hardware was touched (safety rules, or BUDGET_EXHAUSTED when a pool was "
                    "already spent); no episode exists and no budget was spent"},
    }

    # ----- budget and use per pool
    discovery_used = sum(1 for e in episodes if e["pool"] == "discovery")
    verification_used = total - discovery_used
    budget_out = {
        "discovery": {"allowed": budget["discovery"], "used": discovery_used,
                      "remaining": budget["discovery"] - discovery_used},
        "verification": {"allowed": budget["verification"], "used": verification_used,
                         "remaining": budget["verification"] - verification_used},
        "byRole": dict(sorted(by_role.items()))}

    # ----- stop reason: the last campaign state change that ended the campaign
    events = _all_events(backend, campaign_id)
    changes = [ev for ev in events if ev["entity"] == "campaign" and ev["newState"] in CAMPAIGN_STATES]
    stop = None
    if not partial:
        ended = [ev for ev in changes if ev["newState"] in TERMINAL_STATES]
        if ended:
            last = ended[-1]
            stop = {"state": last["newState"], "reasonCode": last["reasonCode"], "reason": last["reason"],
                    "eventId": last["id"], "backendTs": last["backendTs"], "actorId": last["actorId"]}
    lockouts = [{"eventId": ev["id"], "reasonCode": ev["reasonCode"], "reason": ev["reason"], "backendTs": ev["backendTs"]}
                for ev in changes if ev["newState"] == "LOCKED_OUT"]

    # ----- counterexamples
    cxs = _counterexamples(backend, campaign_id, contract, by_id)
    cx_origins = {c["originalEpisodeId"]: c for c in cxs}
    first_confirmed = None
    for e in episodes:
        if e["pool"] == "discovery" and e["episodeId"] in cx_origins:
            first_confirmed = e
            break
    first_observed = next((e for e in episodes if e["pool"] == "discovery" and e["outcome"] == oracle.DUT_FAILURE), None)
    metrics = {
        "episodesToFirstConfirmedFailure": None if first_confirmed is None else first_confirmed["discoveryIndex"],
        "firstConfirmedFailureEpisodeId": None if first_confirmed is None else first_confirmed["episodeId"],
        "censoredAtBudget": None if first_confirmed is not None else budget["discovery"],
        "firstObservedFailureIndex": None if first_observed is None else first_observed["discoveryIndex"],
        "firstObservedFailureEpisodeId": None if first_observed is None else first_observed["episodeId"],
        "discoveryEpisodesUsed": discovery_used, "verificationEpisodesUsed": verification_used, "totalEpisodesUsed": total,
        "definition": "1-based index of the first confirmed counterexample's original episode among discovery-pool "
                      "episodes in planner order; None means no failure was confirmed and the observation is censored "
                      "at the discovery budget. Verification episodes never count toward it (HLD 04 §14, HLD 06 §8)."}

    # ----- requirement margins
    requirements = _requirement_summaries(contract, episodes)

    # ----- headline result and claims
    claims: list[dict[str, Any]] = []
    result = _result(state, partial, episodes, cxs, outcomes, failures, safety_aborts, inconclusive, invalid, valid, total,
                     budget_out, first_observed, claims)

    for outcome, ids in sorted(by_outcome.items()):
        claims.append({"claim": f"{len(ids)} episode(s) ended {outcome}", "episodeIds": ids})
    for r in requirements:
        if r["minMarginEpisodeId"]:
            claims.append({"claim": f"requirement {r['id']}: smallest margin {_num(r['minMargin'])} over "
                                    f"{r['evaluated']} episode(s)", "episodeIds": [r["minMarginEpisodeId"]]})
    for c in cxs:
        claims.append({"claim": f"counterexample {c['id']}: {c['reproduction']['numerator']}/"
                                f"{c['reproduction']['denominator']} replays failed again",
                       "episodeIds": c["episodeIds"]})
    if stop:
        claims.append({"claim": f"the campaign ended {stop['state']}: {stop['reason']}", "episodeIds": [],
                       "eventIds": [stop["eventId"]]})
    if rejected:
        claims.append({"claim": f"{len(rejected)} candidate(s) were refused by the safety rules before running",
                       "episodeIds": [], "candidateIds": [r["candidateId"] for r in rejected]})
    if metrics["episodesToFirstConfirmedFailure"] is not None:
        claims.append({"claim": f"first confirmed failure at discovery episode {metrics['episodesToFirstConfirmedFailure']}",
                       "episodeIds": [metrics["firstConfirmedFailureEpisodeId"]]})

    index = [{"episodeId": e["episodeId"], "plannerSequence": e["plannerSequence"], "pool": e["pool"], "role": e["role"],
              "discoveryIndex": e["discoveryIndex"], "outcome": e["outcome"], "linkedEpisodeId": e["linkedEpisodeId"],
              "reasonCode": e["verdict"]["reasonCode"] if e["verdict"] else None,
              "robustness": e["verdict"]["robustness"] if e["verdict"] else None} for e in episodes]
    planner = view["planner"]
    return {
        "schema": REPORT_SCHEMA, "campaignId": campaign_id, "state": state, "partial": partial,
        "identity": {
            "contractId": facts["contractRow"]["contract_key"], "contractVersion": facts["contractRow"]["version"],
            "contractHash": view["contractHash"], "approvals": facts["approvals"],
            "approvalsRequired": facts["approvalsRequired"],
            "fixtureId": view["fixtureId"], "fixtureRevision": facts["fixtureRevision"],
            "calibrationId": facts["armed"].get("calibrationId"),
            "dutFirmwareSha256": facts["armed"].get("dutFirmwareSha256"),
            "mcuFirmwareSha256": facts["armed"].get("mcuFirmwareSha256"),
            "planner": {"method": planner["method"], "config": planner["config"], "seed": view["seed"], "plan": view["plan"]},
            "softwareVersion": view["softwareVersion"], "dut": contract.get("setup", {}).get("dut")},
        "budget": budget_out, "outcomes": outcomes, "stop": stop, "lockouts": lockouts, "metrics": metrics,
        "requirements": requirements, "result": result, "counterexamples": cxs, "episodes": index,
        "claims": claims, "limitations": list(LIMITATIONS),
    }


def _count(items: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        out[item] = out.get(item, 0) + 1
    return dict(sorted(out.items()))


def _requirement_summaries(contract: dict[str, Any], episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for req in contract.get("requirements", []):
        rid = req["id"]
        margins, status = [], {"PASS": [], "FAIL": [], "INCONCLUSIVE": []}
        for e in episodes:
            verdict = e["verdict"]
            if not verdict or rid not in verdict["margins"]:
                continue
            margins.append((verdict["margins"][rid], e["episodeId"]))
            status.setdefault(verdict["requirements"].get(rid, "PASS"), []).append(e["episodeId"])
        worst = min(margins, key=lambda m: (m[0], m[1])) if margins else None
        out.append({
            "id": rid, "metric": req.get("metric"), "op": req.get("op"),
            "limit": {k: req[k] for k in ("limit", "lo", "hi") if k in req}, "evaluated": len(margins),
            "pass": len(status["PASS"]), "fail": len(status["FAIL"]), "inconclusive": len(status["INCONCLUSIVE"]),
            "minMargin": None if worst is None else worst[0], "minMarginEpisodeId": None if worst is None else worst[1],
            "meanMargin": None if not margins else sum(m for m, _ in margins) / len(margins),
            "maxMargin": None if not margins else max(m for m, _ in margins),
            "failedEpisodeIds": status["FAIL"], "inconclusiveEpisodeIds": status["INCONCLUSIVE"],
            "marginNote": "margins are normalized to [-1, 1]; negative means the limit was crossed"})
    return out


def _counterexamples(backend: Backend, campaign_id: str, contract: dict[str, Any],
                     by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    reqs = {r["id"]: r for r in contract.get("requirements", [])}
    out = []
    for cx in backend.counterexamples(campaign_id):
        original = by_id[cx["originalEpisodeId"]]
        log = backend.session_log(campaign_id, cx["originalEpisodeId"])
        verdict = original["verdict"] or {"requirements": {}, "margins": {}}
        violated = []
        for rid, status in sorted(verdict["requirements"].items()):
            if status != "FAIL":
                continue
            metric = reqs.get(rid, {}).get("metric")
            measured = original["measured"].get(metric, {})
            violated.append({"requirement": rid, "metric": metric, "margin": verdict["margins"].get(rid),
                             "measuredValue": measured.get("value"), "uncertainty": measured.get("uncertainty"),
                             "unit": contract.get("observations", {}).get(metric, {}).get("unit")})
        minimized = cx["minimized"]
        interval_body = cx["intervals"].get("intervals", {}) if isinstance(cx["intervals"], dict) else {}
        confirm = [e for e in log if e["role"] == "confirm"]
        unusable = sum(1 for e in confirm if e["outcome"] not in ("REJECTED", "PASS", oracle.DUT_FAILURE))
        by_role: dict[str, list[str]] = {}
        for entry in log:
            if entry["episodeId"]:
                by_role.setdefault(entry["role"], []).append(entry["episodeId"])
        verification_ids = [e["episodeId"] for e in log if e["episodeId"]]
        reproduction = {**stats.proportion_summary(cx["reproductions"], cx["attempts"]),
                        "unusableReplays": unusable,
                        "meetsTenReplays": cx["attempts"] >= 10,
                        "note": "replays of the failing point after the original failure; the original discovery episode "
                                "is not counted. Fewer than 10 replays means the measured rate is reported as it is "
                                "(FR-13)."}
        out.append({
            "id": cx["id"], "originalEpisodeId": cx["originalEpisodeId"], "origin": cx["origin"],
            "originLabel": ORIGIN_LABELS[cx["origin"]], "violated": violated,
            "original": {"requested": original["requested"], "measured": original["measured"],
                         "verdict": original["verdict"], "discoveryIndex": original["discoveryIndex"],
                         "plannerReason": original["planner"]["reason"]},
            "minimized": {"conditions": minimized.get("conditions", {}), "removed": minimized.get("removed", []),
                          "kept": minimized.get("kept", []), "necessity": minimized.get("necessity", {})},
            "intervals": {name: {"low": iv.get("low"), "high": iv.get("high"), "step": iv.get("step"),
                                 "sides": {side: {"lastFail": s.get("lastFail"), "firstPass": s.get("firstPass"),
                                                  "resolution": s.get("resolution"), "note": s.get("note")}
                                           for side, s in sorted(iv.get("sides", {}).items())}}
                          for name, iv in sorted(interval_body.items())},
            "budgetExhausted": bool(cx["intervals"].get("budgetExhausted")) if isinstance(cx["intervals"], dict) else False,
            "reproduction": reproduction,
            "verification": {"episodes": [{"sequence": e["sequence"], "role": e["role"], "episodeId": e["episodeId"],
                                           "outcome": e["outcome"], "conditions": e["conditions"]} for e in log],
                             "episodeIdsByRole": dict(sorted(by_role.items()))},
            "nearbyPassing": [{"episodeId": e["episodeId"], "role": e["role"], "conditions": e["conditions"]}
                              for e in log if e["outcome"] == oracle.PASS and e["episodeId"]],
            "episodeIds": [cx["originalEpisodeId"], *verification_ids]})
    return out


def _result(state, partial, episodes, cxs, outcomes, failures, safety_aborts, inconclusive, invalid, valid, total,
            budget, first_observed, claims) -> dict[str, Any]:
    """The headline in PRD §19.2 language. One kind, plus extra statements for anything else that matters."""
    statements: list[dict[str, Any]] = []
    discovery_valid = sum(1 for e in episodes if e["pool"] == "discovery" and e["outcome"] in ("PASS", "DUT_FAILURE"))

    def add(text: str, ids: list[str]) -> None:
        statements.append({"text": text, "episodeIds": ids})

    if cxs:
        kind = KIND_COUNTEREXAMPLE
        for c in cxs:
            first = c["violated"][0] if c["violated"] else None
            what = (f"requirement {first['requirement']} failed at measured condition {first['metric']} = "
                    f"{_num(first['measuredValue'])}{' ' + first['unit'] if first.get('unit') else ''}"
                    if first else "a requirement failed")
            add(f"Counterexample found: {what} (requested {_conditions(c['original']['requested'])}); reproduced "
                f"{c['reproduction']['numerator']}/{c['reproduction']['denominator']}; origin {c['originLabel']}.",
                c["episodeIds"])
    elif safety_aborts and not failures:
        kind = KIND_SAFETY_ABORT
    elif failures:
        kind = KIND_UNCONFIRMED
    elif total and (len(invalid) / total >= INCONCLUSIVE_FRACTION or valid == 0):
        kind = KIND_INCONCLUSIVE
    else:
        kind = KIND_NO_COUNTEREXAMPLE

    if kind == KIND_UNCONFIRMED:
        ids = [e["episodeId"] for e in episodes if e["outcome"] == "DUT_FAILURE" and e["pool"] == "discovery"]
        add(f"Failure observed but not confirmed: {len(failures)} failing episode(s), first at discovery episode "
            f"{first_observed['discoveryIndex'] if first_observed else 'n/a'}; no replay set reproduced it or "
            f"verification did not complete. No counterexample is claimed.", ids or failures)
    if kind == KIND_NO_COUNTEREXAMPLE:
        add(f"No counterexample found within budget: {valid} valid episode(s) "
            f"({discovery_valid} discovery) of {total} run. {NO_FAILURE_SENTENCE}",
            [e["episodeId"] for e in episodes if e["outcome"] in ("PASS", "DUT_FAILURE")])
    if invalid:
        other = {k: v for k, v in outcomes["invalidByReason"].items() if k != oracle.INCONCLUSIVE}
        add(("Campaign inconclusive: " if kind == KIND_INCONCLUSIVE else "Invalid episodes: ")
            + f"{len(invalid)}/{total} episodes invalid; {len(inconclusive)} inconclusive (measurement inside the "
            f"guard band) and {sum(other.values())} for other reasons ("
            + (", ".join(f"{k} x{v}" for k, v in other.items()) or "none") + "). Invalid episodes are neither passes nor failures.",
            invalid_ids(episodes))
    if safety_aborts:
        add(f"Safety abort: {len(safety_aborts)} episode(s) ended with a safety trip"
            + ("; the campaign locked out and no further adaptive exploration was performed." if state == "LOCKED_OUT"
               else "."), safety_aborts)
    if kind == KIND_INCONCLUSIVE and not invalid:
        add("Campaign inconclusive: no valid episode was recorded.", [])
    if partial:
        add(f"Partial report: the campaign is {state}, so these results are incomplete.", [])
    return {"kind": kind, "statements": statements,
            "headline": statements[0]["text"] if statements else "No episodes were run."}


def invalid_ids(episodes: list[dict[str, Any]]) -> list[str]:
    return [e["episodeId"] for e in episodes if e["outcome"] == oracle.INVALID_EXPERIMENT]


def _reasons(outcomes: dict[str, Any]) -> str:
    return ", ".join(f"{k} x{v}" for k, v in outcomes["invalidByReason"].items()) or "none"


def campaign_record(report: dict[str, Any], profile: str) -> dict[str, Any]:
    """The per-campaign record ``stats.compare_planners`` takes. ``profile`` names the benchmark; Backend does not know it.

    A campaign that confirmed a failure is an event at its discovery index. One that did not is censored at the
    discovery episodes it actually ran: if it stopped early (planner failure, invalid streak, lockout, abort) it
    must not claim follow-up it never had, so ``budget`` is the smaller of the allowed budget and the episodes used.
    ``state``, ``stop_reason_code`` and ``stopped_early`` are extra keys the comparison ignores, kept for exclusion lists.
    """
    allowed, used = report["budget"]["discovery"]["allowed"], report["budget"]["discovery"]["used"]
    found = report["metrics"]["episodesToFirstConfirmedFailure"]
    stop = report["stop"] or {}
    return {"planner": report["identity"]["planner"]["method"], "profile": profile, "episodes_to_failure": found,
            "budget": allowed if found is not None else max(1, min(allowed, used)),
            "state": report["state"], "stop_reason_code": stop.get("reasonCode"),
            "stopped_early": found is None and used < allowed}


# ------------------------------------------------------------------------------ markdown

def render_markdown(report: dict[str, Any]) -> str:
    ident, budget, outcomes, metrics = report["identity"], report["budget"], report["outcomes"], report["metrics"]
    lines: list[str] = [f"# ActiveQual campaign report {report['campaignId']}", ""]
    if report["partial"]:
        lines += [f"> **PARTIAL REPORT.** The campaign is {report['state']}; results are incomplete.", ""]
    lines += ["## Result", "", f"Result kind: {report['result']['kind']}", ""]
    for st in report["result"]["statements"] or [{"text": report["result"]["headline"], "episodeIds": []}]:
        lines.append(f"- {_bold_label(st['text'])}" + (f" (episodes: {_ids(st['episodeIds'])})" if st["episodeIds"] else ""))
    lines.append("")

    lines += ["## Campaign identity", "",
              f"- Contract: {ident['contractId']} version {ident['contractVersion']}, hash `{ident['contractHash']}`; "
              f"approved by {', '.join(a['reviewer'] for a in ident['approvals']) or 'nobody'} "
              f"({len(ident['approvals'])} of {ident['approvalsRequired']} required)",
              f"- Device under test: {ident['dut']}; DUT firmware `{ident['dutFirmwareSha256']}`; "
              f"test-controller firmware `{ident['mcuFirmwareSha256']}`",
              f"- Fixture: {ident['fixtureId']} revision {ident['fixtureRevision']}; calibration `{ident['calibrationId']}`",
              f"- Planner: {ident['planner']['method']}, seed {ident['planner']['seed']}, plan {_plan(ident['planner']['plan'])}, "
              f"config {to_json(ident['planner']['config'])}",
              f"- Software version: {ident['softwareVersion']}", ""]

    lines += ["## Budget and use", "", "| Pool | Allowed | Used | Remaining |", "|---|---:|---:|---:|"]
    for pool in ("discovery", "verification"):
        b = budget[pool]
        lines.append(f"| {pool} | {b['allowed']} | {b['used']} | {b['remaining']} |")
    lines += ["", "Episodes by role: " + (", ".join(f"{r} {n}" for r, n in budget["byRole"].items()) or "none"), ""]
    lines += [f"Episodes to first confirmed failure (discovery pool only): "
              + (f"{metrics['episodesToFirstConfirmedFailure']} (episode {metrics['firstConfirmedFailureEpisodeId']})"
                 if metrics["episodesToFirstConfirmedFailure"] is not None
                 else f"none; censored at the discovery budget of {metrics['censoredAtBudget']}"),
              f"Total episodes used (all pools, reported separately): {metrics['totalEpisodesUsed']} "
              f"({metrics['discoveryEpisodesUsed']} discovery, {metrics['verificationEpisodesUsed']} verification)", ""]

    lines += ["## Outcomes", "", "| Outcome | Count | Episodes |", "|---|---:|---|"]
    for outcome, count in outcomes["counts"].items():
        lines.append(f"| {outcome} | {count} | {_ids(outcomes['episodeIds'][outcome])} |")
    if not outcomes["counts"]:
        lines.append("| (no episodes) | 0 | none |")
    lines += ["", f"Invalid: {outcomes['invalid']} (of which {outcomes['inconclusive']} inconclusive inside the guard band; "
                  f"by reason: {_reasons(outcomes)}). Safety aborts: {outcomes['safetyAborts']}. "
                  f"Candidates refused by the safety rules before running: {outcomes['candidatesRejected']['count']}"
                  + (f" ({', '.join(f'{k} x{v}' for k, v in outcomes['candidatesRejected']['byCode'].items())}; "
                     f"candidates {', '.join(outcomes['candidatesRejected']['candidateIds'])})"
                     if outcomes['candidatesRejected']['count'] else "") + ".", ""]

    lines += ["## Stop reason", ""]
    if report["stop"]:
        s = report["stop"]
        lines += [f"The campaign ended {s['state']}"
                  + (f" ({s['reasonCode']})" if s["reasonCode"] != s["state"] else "") + f": {s['reason']} (event {s['eventId']})"]
    else:
        lines += [f"The campaign has not ended; it is {report['state']}."]
    for lk in report["lockouts"]:
        lines.append(f"- Lockout at {lk['backendTs']}: {lk['reasonCode']}: {lk['reason']}")
    lines.append("")

    lines += ["## Requirement margins", "",
              "Margins are normalized to [-1, 1]; negative means the limit was crossed. Smallest margin and its episode:", "",
              "| Requirement | Metric | Evaluated | Pass | Fail | Inconclusive | Smallest margin | Episode |",
              "|---|---|---:|---:|---:|---:|---:|---|"]
    for r in report["requirements"]:
        lines.append(f"| {r['id']} | {r['metric']} | {r['evaluated']} | {r['pass']} | {r['fail']} | {r['inconclusive']} | "
                     f"{_num(r['minMargin']) if r['minMargin'] is not None else 'n/a'} | {r['minMarginEpisodeId'] or 'n/a'} |")
    lines.append("")

    lines += ["## Counterexamples", ""]
    if not report["counterexamples"]:
        lines += ["None confirmed." + (f" {NO_FAILURE_SENTENCE}" if report["result"]["kind"] == KIND_NO_COUNTEREXAMPLE else ""), ""]
    for n, c in enumerate(report["counterexamples"], start=1):
        lines += _render_counterexample(n, c)

    lines += ["## Claims and the episodes behind them", ""]
    for claim in report["claims"]:
        cites = [f"episodes: {_ids(claim['episodeIds'])}"] if claim["episodeIds"] else []
        cites += [f"event: {', '.join(str(i) for i in claim['eventIds'])}"] if claim.get("eventIds") else []
        cites += [f"candidates: {', '.join(claim['candidateIds'])}"] if claim.get("candidateIds") else []
        lines.append(f"- {claim['claim']} ({'; '.join(cites) or 'episodes: none'})")
    lines.append("")

    lines += ["## Episode index", "", "| Episode | Seq | Pool | Role | Outcome | Reason code | Robustness | Linked to |",
              "|---|---:|---|---|---|---|---:|---|"]
    for e in report["episodes"]:
        rob = "n/a" if e["robustness"] is None else _num(e["robustness"])
        lines.append(f"| {e['episodeId']} | {e['plannerSequence']} | {e['pool']} | {e['role']} | {e['outcome'] or 'IN_FLIGHT'} | "
                     f"{e['reasonCode'] or 'n/a'} | {rob} | {e['linkedEpisodeId'] or ''} |")
    lines.append("")

    lines += ["## Limitations", ""] + [f"- {text}" for text in report["limitations"]] + [""]
    return "\n".join(lines)


_LABELS = ("Counterexample found:", "No counterexample found within budget:", "Campaign inconclusive:",
           "Safety abort:", "Failure observed but not confirmed:", "Partial report:", "Invalid episodes:")


def _bold_label(text: str) -> str:
    for label in _LABELS:
        if text.startswith(label):
            return f"**{label}**{text[len(label):]}"
    return text


def _found(value: Any) -> str:
    return "none found" if value is None else _num(value)


def _plan(plan: Any) -> str:
    return plan if isinstance(plan, str) else to_json(plan)


def _render_counterexample(n: int, c: dict[str, Any]) -> list[str]:
    rep = c["reproduction"]
    lines = [f"### Counterexample {n}: {c['id']}", "",
             f"- Origin: {c['originLabel']}",
             f"- Original episode: {c['originalEpisodeId']} (discovery episode {c['original']['discoveryIndex']}); "
             f"planner reason: {c['original']['plannerReason']}",
             f"- Reproduction: the failing point failed again in {_rate(rep)} replays (the original discovery episode is "
             f"not counted); unusable replays {rep['unusableReplays']}."
             + ("" if rep["meetsTenReplays"] else " Fewer than 10 replays were run, so the measured rate is reported as it is (FR-13)."),
             ]
    for v in c["violated"]:
        lines.append(f"- Violated requirement {v['requirement']} on {v['metric']}: measured {_num(v['measuredValue'])}"
                     f"{' ' + v['unit'] if v.get('unit') else ''}"
                     + (f" +/- {_num(v['uncertainty'])}" if v.get("uncertainty") is not None else "")
                     + f", margin {_num(v['margin'])} (episode {c['originalEpisodeId']})")
    lines += ["", "Requested conditions (original):", "", f"    {_conditions(c['original']['requested'])}", "",
              "Measured values (original, each with its uncertainty):", ""]
    for metric, m in c["original"]["measured"].items():
        lines.append(f"- {metric}: {_num(m['value'])}" + (f" +/- {_num(m['uncertainty'])}" if m.get("uncertainty") is not None else ""))
    mn = c["minimized"]
    lines += ["", "Minimized conditions:", "", f"    {_conditions(mn['conditions'])}", "",
              f"- Returned to nominal with the failure persisting (removed): {', '.join(mn['removed']) or 'none'}",
              f"- Kept, because the failure needs them: {', '.join(mn['kept']) or 'none'}",
              "- Necessity probes: " + (", ".join(f"{k}: {v}" for k, v in sorted(mn['necessity'].items())) or "none run")]
    if c["intervals"]:
        lines += ["", "Failure intervals (last failing value to first passing value, with resolution and note per side):", ""]
        for name, iv in c["intervals"].items():
            lines.append(f"- {name}: fails from {_num(iv['low'])} to {_num(iv['high'])} (step {_num(iv['step'])})")
            for side, s in iv["sides"].items():
                lines.append(f"    - {side} side: last failing {_num(s['lastFail'])}, first passing {_found(s['firstPass'])}, "
                             f"resolution {_found(s['resolution'])}; {s['note']}")
    if c["budgetExhausted"]:
        lines += ["", "The verification budget ran out before every interval was resolved."]
    lines += ["", "Verification episodes:", ""]
    for e in c["verification"]["episodes"]:
        lines.append(f"- {e['sequence']}. {e['role']}: {e['outcome']} (episode {e['episodeId'] or 'none: candidate refused'}), "
                     f"conditions {_conditions(e['conditions'])}")
    if not c["verification"]["episodes"]:
        lines.append("- none")
    lines += ["", f"Nearby passing episodes: {_ids([p['episodeId'] for p in c['nearbyPassing']])}",
              f"Episodes cited: {_ids(c['episodeIds'])}", ""]
    return lines
