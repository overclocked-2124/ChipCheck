"""Control-plane entry point: Backend, Agent runner, Decision (in process), HTTP API on loopback.

Configuration comes from a JSON file outside the repository (HLD 07 §8), for example
``~/.config/activequal/control-plane.json``::

    {"database": "/var/lib/activequal/campaigns.db", "traceDir": "/var/lib/activequal/traces",
     "operatorTokenFile": "/home/me/.config/activequal/operator.token",
     "reviewerPassphraseHash": "scrypt$...$..."}

``python -m activequal.service.app --init`` writes a starter config, a fresh operator token file (mode
0600) and prints the reviewer passphrase hash command to run. Environment overrides:
ACTIVEQUAL_CONFIG, ACTIVEQUAL_HOST, ACTIVEQUAL_PORT.
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import secrets
import signal
import threading
from pathlib import Path
from typing import Any

from activequal.service.auth import AuthConfig, hash_passphrase

DEFAULT_CONFIG = Path.home() / ".config" / "activequal" / "control-plane.json"
DEFAULT_DATA = Path.home() / ".local" / "share" / "activequal"


def load_config(path: Path) -> tuple[dict[str, Any], AuthConfig]:
    config = json.loads(path.read_text(encoding="utf-8"))
    token_path = Path(config["operatorTokenFile"]).expanduser()
    if token_path.stat().st_mode & 0o077:
        raise SystemExit(f"{token_path} must not be readable by other users (chmod 600)")
    return config, AuthConfig(token_path.read_text(encoding="utf-8").strip(), config["reviewerPassphraseHash"])


def init_config(path: Path) -> None:
    if path.exists():
        raise SystemExit(f"{path} already exists; delete it first if you really want a new one")
    path.parent.mkdir(parents=True, exist_ok=True)
    token_path = path.parent / "operator.token"
    fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(secrets.token_urlsafe(32) + "\n")
    passphrase = getpass.getpass("Reviewer passphrase (needed to approve contracts and clear lockouts): ")
    if len(passphrase) < 10:
        token_path.unlink()
        raise SystemExit("use a passphrase of at least 10 characters")
    DEFAULT_DATA.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"database": str(DEFAULT_DATA / "campaigns.db"), "traceDir": str(DEFAULT_DATA / "traces"),
                                "operatorTokenFile": str(token_path),
                                "reviewerPassphraseHash": hash_passphrase(passphrase)}, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    print(f"wrote {path} and {token_path}")


def build(config: dict[str, Any], auth: AuthConfig, software_version: str):
    from activequal.decision.service.decision import propose
    from activequal.service.backend import Backend
    from activequal.service.http_api import Api
    from activequal.service.runner import AgentRunner
    from activequal.storage.database import Database

    backend = Backend(Database(config["database"]), config["traceDir"], software_version=software_version)
    runner = AgentRunner(backend, propose)
    from activequal.service.exporter import make_exporter
    exporter = make_exporter(Path(config["database"]).parent / "exports")
    return backend, runner, Api(backend, auth, propose, runner, exporter)


def software_version() -> str:
    import subprocess
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
                             cwd=Path(__file__).resolve().parent)
        return "git:" + out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main(argv: list[str] | None = None) -> None:
    from activequal.service.http_api import ApiServer

    parser = argparse.ArgumentParser(description="ActiveQual control plane (loopback only)")
    parser.add_argument("--config", type=Path, default=Path(os.environ.get("ACTIVEQUAL_CONFIG", DEFAULT_CONFIG)))
    parser.add_argument("--host", default=os.environ.get("ACTIVEQUAL_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ACTIVEQUAL_PORT", "8001")))
    parser.add_argument("--init", action="store_true", help="create a starter configuration and operator token")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.init:
        init_config(args.config)
        return
    if not args.config.exists():
        raise SystemExit(f"{args.config} not found; run with --init first")
    config, auth = load_config(args.config)
    backend, runner, api = build(config, auth, software_version())
    server = ApiServer(api, args.host, args.port)
    runner.start()
    server.start()
    logging.getLogger("activequal").info("control plane listening on %s:%s", args.host, server.port)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    stop.wait()
    runner.stop()
    server.stop()
    backend.db.close()


if __name__ == "__main__":
    main()
