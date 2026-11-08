"""Rail calibration against a trusted meter (HLD 02 §18 test 2, HLD 10 WP9, HLD 05 calibration record).

Input is a JSON file of points per channel, each the bench read-back and the meter reading at the
same setpoint, taken at least at the minimum, midpoint and maximum test values:

    {"meter": "Fluke 87V #1234", "meterUncertaintyV": 0.002,
     "channels": {"supply.ch2": [{"setV": 3.0, "readV": 2.991, "meterV": 3.002}, ...]}}

The fit is ordinary least squares, ``meter = gain * read + offset``. The recorded uncertainty is
the expanded uncertainty (k = 2) of the residuals combined in quadrature with the meter's own,
so a fit can never claim better accuracy than its reference.

    python -m activequal.tools.calibrate points.json --operator dana            # print the record
    python -m activequal.tools.calibrate points.json --operator dana --post     # record it
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MIN_POINTS = 3
MAX_GAIN_ERROR = 0.05            # a gain more than 5% from 1 means wiring or range is wrong, not drift
VALID_DAYS = 30


class CalibrationError(ValueError):
    pass


@dataclass(frozen=True)
class ChannelFit:
    gain: float
    offset: float
    uncertainty: float
    max_residual: float


def fit_channel(points: list[dict[str, float]], meter_uncertainty: float) -> ChannelFit:
    if len(points) < MIN_POINTS:
        raise CalibrationError(f"need at least {MIN_POINTS} points (minimum, midpoint, maximum)")
    xs, ys = [], []
    for p in points:
        x, y = p.get("readV"), p.get("meterV")
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x, y)):
            raise CalibrationError("every point needs finite readV and meterV")
        xs.append(float(x)); ys.append(float(y))
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-12:
        raise CalibrationError("points must span the range; all read-backs are the same")
    gain = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    offset = my - gain * mx
    if abs(gain - 1.0) > MAX_GAIN_ERROR:
        raise CalibrationError(f"gain {gain:.4f} is more than {MAX_GAIN_ERROR:.0%} from 1; check wiring and range")
    residuals = [y - (gain * x + offset) for x, y in zip(xs, ys)]
    dof = max(1, n - 2)
    sigma = math.sqrt(sum(r * r for r in residuals) / dof)
    expanded = math.sqrt((2 * sigma) ** 2 + meter_uncertainty ** 2)
    return ChannelFit(gain, offset, expanded, max(abs(r) for r in residuals))


def build_record(data: dict[str, Any], operator: str, now: datetime | None = None) -> dict[str, Any]:
    meter = str(data.get("meter", "")).strip()
    if not meter:
        raise CalibrationError("the meter identity is required")
    meter_u = data.get("meterUncertaintyV", 0.0)
    if not isinstance(meter_u, (int, float)) or meter_u < 0:
        raise CalibrationError("meterUncertaintyV must be a non-negative number")
    channels = data.get("channels")
    if not isinstance(channels, dict) or not channels:
        raise CalibrationError("channels must map at least one channel to its points")
    fits = {name: fit_channel(points, float(meter_u)) for name, points in channels.items()}
    valid_until = (now or datetime.now(timezone.utc)) + timedelta(days=VALID_DAYS)
    return {"channels": {name: {"gain": round(f.gain, 6), "offset": round(f.offset, 6),
                                "uncertainty": round(f.uncertainty, 6)} for name, f in fits.items()},
            "meterIdentity": meter, "operator": operator, "validUntil": valid_until.isoformat()}


def post_record(base_url: str, fixture_id: str, record: dict[str, Any], token: str, actor: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/fixtures/{fixture_id}/calibrations", method="POST",
        data=json.dumps(record).encode(), headers={"Content-Type": "application/json",
                                                   "X-ActiveQual-Operator-Token": token, "X-ActiveQual-Actor": actor})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fit rail calibration from meter readings")
    parser.add_argument("points", type=Path)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--post", action="store_true", help="record it on the control plane")
    parser.add_argument("--fixture-id", default="bench-A")
    parser.add_argument("--control-plane", default=os.environ.get("ACTIVEQUAL_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--token-file", type=Path, default=Path.home() / ".config" / "activequal" / "operator.token")
    args = parser.parse_args(argv)
    try:
        record = build_record(json.loads(args.points.read_text(encoding="utf-8")), args.operator)
    except (CalibrationError, json.JSONDecodeError, OSError) as exc:
        print(f"calibration refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(record, indent=2))
    if args.post:
        result = post_record(args.control_plane, args.fixture_id, record,
                             args.token_file.read_text(encoding="utf-8").strip(), args.operator)
        print(f"recorded calibration {result.get('calibrationId')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
