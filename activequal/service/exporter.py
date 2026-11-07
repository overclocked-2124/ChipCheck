"""Control-plane report export: writes an evidence bundle under the data directory and returns the summary."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from activequal.service.backend import Backend
from activequal.service.bundle import BundleError, export_bundle
from activequal.service.errors import invalid
from activequal.service.report import build_report, render_markdown


def make_exporter(export_dir: str | Path) -> Callable[[Backend, str], dict[str, Any]]:
    root = Path(export_dir)

    def export(backend: Backend, campaign_id: str) -> dict[str, Any]:
        report = build_report(backend, campaign_id)
        target = root / f"{campaign_id}-{time.strftime('%Y%m%dT%H%M%S')}"
        try:
            manifest = export_bundle(backend, campaign_id, target, allow_partial=True)
        except BundleError as exc:
            raise invalid(str(exc)) from exc
        return {"bundlePath": str(target), "manifest": manifest, "report": report,
                "markdown": render_markdown(report)}

    return export
