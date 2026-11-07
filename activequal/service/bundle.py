"""Evidence bundle export and verification (WP15, FR-15, NFR-09, HLD 08 §6).

Layout (one directory per campaign)::

    manifest.json        ids, versions, hashes, software commit, export time (from ``backend.clock``)
    contract.json        the canonical contract text exactly as stored, its hash, and the approvals
    calibration.json     the calibration the campaign was armed with and the arming tuple
    planner.json         method, config, seed, plan, budgets, candidates the safety rules refused
    episodes.jsonl       one record per episode (HLD 08 §5), including invalid and aborted ones
    events.jsonl         the audit history, ordered by event id
    counterexamples/     one JSON file per counterexample
    traces/              raw trace files named by their SHA-256
    report.md            the report in PRD §19.2 language
    report.json          the same report, machine readable
    checksums.sha256     ``sha256sum`` lines for every other file, sorted by path

Seeded-fault ground-truth labels are never written here. They are exported separately once the evaluation is
frozen (HLD 08 §6, PRD §22.4); nothing in this module reads the simulator or any fault label.

The export is a pure function of the campaign's stored state and ``backend.clock``, so exporting the same
finished campaign twice gives byte-identical directories. Nothing depends on the output path.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from activequal.service.backend import Backend
from activequal.service.ids import isoformat
from activequal.service.report import (TERMINAL_STATES, build_report, campaign_facts, collect_episodes,
                                       render_markdown, rejected_candidates, to_json)

BUNDLE_SCHEMA = "activequal.bundle/1"
CHECKSUMS = "checksums.sha256"
_CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9._\-][A-Za-z0-9._\-/]*)$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class BundleError(RuntimeError):
    """The campaign cannot be exported (not finished, trace missing or corrupt, output directory in use)."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text(value: Any) -> bytes:
    return (to_json(value, indent=2) + "\n").encode("utf-8")


def _jsonl(rows: list[Any]) -> bytes:
    return "".join(to_json(row) + "\n" for row in rows).encode("utf-8")


def _events(backend: Backend, campaign_id: str, contract_hash: str, fixture_id: str) -> list[dict[str, Any]]:
    """The campaign's own events plus the contract's and the fixture's events up to the campaign's last event."""
    db = backend.db
    last = db.one("SELECT COALESCE(MAX(id), 0) AS m FROM events WHERE campaign_id = ?", (campaign_id,))["m"]
    rows = db.query(
        "SELECT * FROM events WHERE campaign_id = ? OR (id <= ? AND ((entity = 'contract' AND contract_hash = ?)"
        " OR (entity = 'fixture' AND fixture_id = ?))) ORDER BY id", (campaign_id, last, contract_hash, fixture_id))
    return [{"id": r["id"], "entity": r["entity"], "campaignId": r["campaign_id"], "episodeId": r["episode_id"],
             "attempt": r["attempt"], "previousState": r["previous_state"], "newState": r["new_state"],
             "actorType": r["actor_type"], "actorId": r["actor_id"], "reasonCode": r["reason_code"],
             "reason": r["reason"], "backendTs": r["backend_ts"], "controllerTs": r["controller_ts"],
             "contractHash": r["contract_hash"], "fixtureId": r["fixture_id"],
             "detail": None if r["detail_json"] is None else json.loads(r["detail_json"])} for r in rows]


def export_bundle(backend: Backend, campaign_id: str, directory: str | Path, *, allow_partial: bool = False
                  ) -> dict[str, Any]:
    """Write the evidence bundle and return its manifest. Refuses a campaign that has not finished."""
    view = backend.get_campaign(campaign_id)
    partial = view["state"] not in TERMINAL_STATES
    if partial and not allow_partial:
        raise BundleError(f"campaign is {view['state']}, not COMPLETED, ABORTED or LOCKED_OUT; "
                          "pass allow_partial=True to export a partial bundle")
    out = Path(directory)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise BundleError(f"{out} already exists and is not an empty directory")

    facts = campaign_facts(backend, campaign_id)
    report = build_report(backend, campaign_id)
    episodes = collect_episodes(backend, campaign_id)
    events = _events(backend, campaign_id, view["contractHash"], view["fixtureId"])
    row = facts["contractRow"]
    files: dict[str, bytes] = {}

    files["contract.json"] = _text({
        "schema": BUNDLE_SCHEMA + "/contract", "contractId": row["contract_key"], "version": row["version"],
        "contractHash": row["contract_hash"], "canonicalJson": row["canonical_json"],
        "approvalsRequired": facts["approvalsRequired"], "approvals": facts["approvals"]})
    files["calibration.json"] = _text({
        "calibrationId": facts["armed"].get("calibrationId"), "calibration": facts["calibration"],
        "fixtureId": view["fixtureId"], "fixtureRevision": facts["fixtureRevision"], "armedTuple": facts["armed"]})
    files["planner.json"] = _text({
        "method": view["planner"]["method"], "config": view["planner"]["config"], "seed": view["seed"],
        "plan": view["plan"], "discoveryBudget": view["budget"]["discovery"],
        "verificationBudget": view["budget"]["verification"], "softwareVersion": view["softwareVersion"],
        "rejectedCandidates": rejected_candidates(backend, campaign_id)})
    files["episodes.jsonl"] = _jsonl(episodes)
    files["events.jsonl"] = _jsonl(events)

    by_id = {e["episodeId"]: e for e in episodes}
    for cx in report["counterexamples"]:
        cited = [by_id[i] for i in cx["episodeIds"] if i in by_id]
        ids = set(cx["episodeIds"])
        files[f"counterexamples/{cx['id']}.json"] = _text({
            "counterexample": cx, "episodes": cited,
            "hashes": {"contractHash": view["contractHash"], "fixtureId": view["fixtureId"],
                       "fixtureRevision": facts["fixtureRevision"], "calibrationId": facts["armed"].get("calibrationId"),
                       "dutFirmwareSha256": facts["armed"].get("dutFirmwareSha256"),
                       "mcuFirmwareSha256": facts["armed"].get("mcuFirmwareSha256"),
                       "softwareVersion": view["softwareVersion"]},
            "safetyAndStateEvents": [ev for ev in events if ev["episodeId"] in ids]})

    trace_index = []
    for trace in backend.db.query(
            "SELECT t.* FROM traces t JOIN episodes e ON e.id = t.episode_id WHERE e.campaign_id = ? ORDER BY t.sha256",
            (campaign_id,)):
        path = Path(trace["path"])
        if not path.is_file():
            raise BundleError(f"trace {trace['sha256']} is missing from the trace store")
        data = path.read_bytes()
        if _sha256(data) != trace["sha256"]:
            raise BundleError(f"trace {trace['sha256']} does not match its hash in the trace store")
        files[f"traces/{trace['sha256']}"] = data
        trace_index.append({"sha256": trace["sha256"], "bytes": len(data), "mediaType": trace["media_type"],
                            "episodeId": trace["episode_id"]})

    files["report.md"] = (render_markdown(report) + "\n").encode("utf-8")
    files["report.json"] = _text(report)

    manifest = {
        "schema": BUNDLE_SCHEMA, "campaignId": campaign_id, "partial": partial, "campaignState": view["state"],
        "exportedAt": isoformat(backend.clock.now()), "stop": report["stop"],
        "software": {"campaign": view["softwareVersion"], "exporter": backend.software_version},
        "contract": {"id": row["contract_key"], "version": row["version"], "hash": row["contract_hash"]},
        "fixtureId": view["fixtureId"], "fixtureRevision": facts["fixtureRevision"],
        "calibrationId": facts["armed"].get("calibrationId"),
        "dutFirmwareSha256": facts["armed"].get("dutFirmwareSha256"),
        "mcuFirmwareSha256": facts["armed"].get("mcuFirmwareSha256"),
        "planner": {"method": view["planner"]["method"], "seed": view["seed"], "sha256": _sha256(files["planner.json"])},
        "counts": {"episodes": len(episodes), "events": len(events), "counterexamples": len(report["counterexamples"]),
                   "traces": len(trace_index)},
        "counterexamples": [cx["id"] for cx in report["counterexamples"]], "traces": trace_index,
        "groundTruth": "not included; exported separately after the evaluation freeze (HLD 08 section 6)"}
    files["manifest.json"] = _text(manifest)

    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (out / CHECKSUMS).write_bytes(_checksum_text({name: _sha256(data) for name, data in files.items()}).encode("ascii"))
    return manifest


def _checksum_text(digests: dict[str, str]) -> str:
    return "".join(f"{digests[name]}  {name}\n" for name in sorted(digests))


# ------------------------------------------------------------------------------ verification

def verify_bundle(directory: str | Path) -> list[str]:
    """Return a list of problems; an empty list means the bundle is intact and consistent."""
    root = Path(directory)
    if not root.is_dir():
        return [f"{root} is not a directory"]
    problems: list[str] = []
    on_disk: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            problems.append(f"{path.relative_to(root).as_posix()}: symbolic links are not allowed")
        elif path.is_file():
            on_disk[path.relative_to(root).as_posix()] = path

    listed: dict[str, str] = {}
    checksum_path = on_disk.get(CHECKSUMS)
    if checksum_path is None:
        problems.append(f"{CHECKSUMS} is missing")
    else:
        raw = checksum_path.read_bytes()
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError:
            text = None
            problems.append(f"{CHECKSUMS} is not ASCII text")
        if text is not None:
            for number, line in enumerate(text.split("\n")[:-1] if text.endswith("\n") else text.split("\n"), start=1):
                match = _CHECKSUM_LINE.match(line)
                if match is None or ".." in match.group(2).split("/"):
                    problems.append(f"{CHECKSUMS} line {number} is malformed")
                    continue
                if match.group(2) in listed:
                    problems.append(f"{CHECKSUMS} lists {match.group(2)} more than once")
                listed[match.group(2)] = match.group(1)
            if not text.endswith("\n"):
                problems.append(f"{CHECKSUMS} does not end with a newline")
            elif not any("malformed" in p or "more than once" in p for p in problems) and text != _checksum_text(listed):
                problems.append(f"{CHECKSUMS} is not in canonical form (sorted sha256sum lines)")

    expected = set(listed)
    actual = set(on_disk) - {CHECKSUMS}
    for name in sorted(expected - actual):
        problems.append(f"{name}: listed in {CHECKSUMS} but missing")
    for name in sorted(actual - expected):
        problems.append(f"{name}: present but not listed in {CHECKSUMS}")
    for name in sorted(expected & actual):
        if _sha256(on_disk[name].read_bytes()) != listed[name]:
            problems.append(f"{name}: checksum mismatch")
    for required in ("manifest.json", "contract.json", "calibration.json", "planner.json", "episodes.jsonl",
                     "events.jsonl", "report.md", "report.json"):
        if required not in actual and required not in expected:
            problems.append(f"{required}: required file is absent")

    documents: dict[str, Any] = {}
    for name, path in sorted(on_disk.items()):
        if name == CHECKSUMS or not (name.endswith(".json") or name.endswith(".jsonl")):
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            problems.append(f"{name}: not valid UTF-8")
            continue
        if name.endswith(".jsonl"):
            rows = []
            lines = text.split("\n")
            if lines[-1] == "":
                lines.pop()
            for number, line in enumerate(lines, start=1):
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    problems.append(f"{name} line {number}: not valid JSON")
            documents[name] = rows
        else:
            try:
                documents[name] = json.loads(text)
            except ValueError:
                problems.append(f"{name}: not valid JSON")

    for name in sorted(actual):
        if name.startswith("traces/") and name.count("/") == 1:
            if _HEX64.match(name[len("traces/"):]) is None:
                problems.append(f"{name}: trace file names must be a SHA-256")
            elif _sha256(on_disk[name].read_bytes()) != name[len("traces/"):]:
                problems.append(f"{name}: trace content does not match its hash")
        elif name.startswith("traces/"):
            problems.append(f"{name}: unexpected path under traces/")
    problems += _consistency(documents, actual, on_disk)
    return problems


def _consistency(docs: dict[str, Any], files: set[str], on_disk: dict[str, Path]) -> list[str]:
    problems: list[str] = []
    manifest, contract = docs.get("manifest.json"), docs.get("contract.json")
    if isinstance(contract, dict) and isinstance(contract.get("canonicalJson"), str):
        if _sha256(contract["canonicalJson"].encode("utf-8")) != contract.get("contractHash"):
            problems.append("contract.json: canonicalJson does not hash to contractHash")
        if isinstance(manifest, dict) and manifest.get("contract", {}).get("hash") != contract.get("contractHash"):
            problems.append("manifest.json: contract hash differs from contract.json")
    if isinstance(manifest, dict):
        traces = {t.get("sha256") for t in manifest.get("traces", []) if isinstance(t, dict)}
        if traces != {n[len("traces/"):] for n in files if n.startswith("traces/")}:
            problems.append("manifest.json: trace list differs from the files under traces/")
        cx_files = {n[len("counterexamples/"):-len(".json")] for n in files
                    if n.startswith("counterexamples/") and n.endswith(".json")}
        if set(manifest.get("counterexamples", [])) != cx_files:
            problems.append("manifest.json: counterexample list differs from the files under counterexamples/")
        counts = manifest.get("counts", {})
        for key, name in (("episodes", "episodes.jsonl"), ("events", "events.jsonl")):
            if name in docs and counts.get(key) != len(docs[name]):
                problems.append(f"manifest.json: {key} count differs from {name}")
        if "planner.json" in on_disk and manifest.get("planner", {}).get("sha256") != _sha256(on_disk["planner.json"].read_bytes()):
            problems.append("manifest.json: planner hash differs from planner.json")
        report = docs.get("report.json")
        if isinstance(report, dict) and report.get("partial") != manifest.get("partial"):
            problems.append("manifest.json and report.json disagree on partial")
        for record in docs.get("episodes.jsonl", []):
            for digest in record.get("traces", []) if isinstance(record, dict) else []:
                if digest not in traces:
                    problems.append(f"episodes.jsonl: episode {record.get('episodeId')} cites trace {digest} not in the bundle")
    return problems
