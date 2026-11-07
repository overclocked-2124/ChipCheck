"""Bench-process entry point: Controller + Adapter, pulling work from the control plane.

The bench never listens on a port; it only calls the control plane (HLD 01 §8.1, HLD 07 §3). The
fixture's bearer token comes from a file readable only by the bench user (HLD 07 §8).

    python -m activequal.controller.service.app --fixture-id bench-A --token-file ~/.config/activequal/bench-A.token \
        --mode sim --profile B1w
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
import time
from pathlib import Path

from activequal.controller.service.controller import Controller
from activequal.controller.service.http_client import HttpBackendClient
from activequal.controller.service.spool import Spool

log = logging.getLogger("activequal.bench")


def read_token(path: Path) -> str:
    if path.stat().st_mode & 0o077:
        raise SystemExit(f"{path} must not be readable by other users (chmod 600)")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit(f"{path} is empty")
    return token


def build_adapter(mode: str, profile: str, noise_seed: int):
    if mode == "sim":
        from activequal.adapter.service.simulator import SimulatedBenchAdapter
        return SimulatedBenchAdapter(profile, noise_seed=noise_seed)
    raise SystemExit(f"bench mode {mode!r} is not available yet; use --mode sim")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="ActiveQual bench process")
    parser.add_argument("--control-plane", default=os.environ.get("ACTIVEQUAL_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--spool-dir", type=Path, default=Path.home() / ".local" / "share" / "activequal" / "spool")
    parser.add_argument("--mode", choices=["sim", "serial"], default="sim")
    parser.add_argument("--profile", default="B3", help="simulator benchmark profile (sim mode)")
    parser.add_argument("--noise-seed", type=int, default=0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--instance-id", default=f"controller-{os.getpid()}")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    client = HttpBackendClient(args.control_plane, read_token(args.token_file))
    controller = Controller(client, build_adapter(args.mode, args.profile, args.noise_seed), Spool(args.spool_dir),
                            args.fixture_id, instance_id=args.instance_id)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    # Startup order (HLD 07 §4.1): outputs to shutdown, report health, then begin polling for claims.
    while not stop.is_set():
        try:
            report = controller.run_once()
        except Exception:
            log.exception("run failed; the bench stays in its safe state")
            report = None
        if report is not None:
            log.info("episode %s: %s", report.episode_id, report.status)
        else:
            stop.wait(args.poll_interval)


if __name__ == "__main__":
    main()
