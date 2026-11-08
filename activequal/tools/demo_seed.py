"""Seed a running control plane for the simulated demo (PRD §18): the OLED contract approved by two
reviewers, fixture bench-A with a calibration, and the bench token written to a file.

    python -m activequal.tools.demo_seed --bench-token-out ~/.config/activequal/bench-A.token
    python -m activequal.controller.service.app --fixture-id bench-A --token-file ~/.config/activequal/bench-A.token

The reviewer passphrase is read from the terminal. The simulator's firmware hashes are recorded as
approved, so this is for the simulated bench only; a real bench records its own hashes.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from activequal.model.examples import oled_example_contract
from activequal.tools.stack import CAPABILITIES, MCU_FIRMWARE

CONFIG_DIR = Path.home() / ".config" / "activequal"


class Client:
    def __init__(self, base: str, token: str, passphrase: str) -> None:
        self.base, self.token, self.passphrase = base.rstrip("/"), token, passphrase

    def call(self, method: str, path: str, actor: str, body: Any = None, reviewer: bool = False) -> dict[str, Any]:
        headers = {"X-ActiveQual-Operator-Token": self.token, "X-ActiveQual-Actor": actor,
                   "Content-Type": "application/json"}
        if reviewer:
            headers["X-ActiveQual-Reviewer-Passphrase"] = self.passphrase
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"{method} {path} failed: {exc.code} {exc.read().decode(errors='replace')}") from exc


def seed(client: Client, fixture_id: str) -> dict[str, Any]:
    contract = client.call("POST", "/v1/contracts", "sam", {"contract": oled_example_contract()})
    key, version = contract["contractId"], contract["version"]
    for reviewer in ("dana", "alex"):
        client.call("POST", f"/v1/contracts/{key}/versions/{version}:approve", reviewer, {}, reviewer=True)
    fixture = client.call("POST", "/v1/fixtures", "dana",
                          {"fixtureId": fixture_id, "revision": "A", "capabilities": CAPABILITIES,
                           "approvedMcuFirmwareSha256": MCU_FIRMWARE}, reviewer=True)
    valid = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    client.call("POST", f"/v1/fixtures/{fixture_id}/calibrations", "sam",
                {"channels": {"supply.ch2": {"gain": 1.0, "offset": 0.0, "uncertainty": 0.005}},
                 "meterIdentity": "simulated meter", "operator": "sam", "validUntil": valid})
    return {"contractId": key, "version": version, "fixtureId": fixture_id, "benchToken": fixture["token"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the simulated demo on a running control plane")
    parser.add_argument("--control-plane", default=os.environ.get("ACTIVEQUAL_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--token-file", type=Path, default=CONFIG_DIR / "operator.token")
    parser.add_argument("--fixture-id", default="bench-A")
    parser.add_argument("--bench-token-out", type=Path, default=CONFIG_DIR / "bench-A.token")
    args = parser.parse_args(argv)
    passphrase = os.environ.get("ACTIVEQUAL_REVIEWER_PASSPHRASE") or getpass.getpass("Reviewer passphrase: ")
    client = Client(args.control_plane, args.token_file.read_text(encoding="utf-8").strip(), passphrase)
    result = seed(client, args.fixture_id)
    args.bench_token_out.parent.mkdir(parents=True, exist_ok=True)
    args.bench_token_out.write_text(result.pop("benchToken") + "\n", encoding="utf-8")
    os.chmod(args.bench_token_out, 0o600)
    print(json.dumps({**result, "benchTokenFile": str(args.bench_token_out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
