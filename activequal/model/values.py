"""Small validated-value helpers shared by the contract parsers."""

from __future__ import annotations

import math
from typing import Any

from activequal.model.errors import InvalidRequest


def number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise InvalidRequest(f"{name} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequest(f"{name} must be a number") from exc
    if not math.isfinite(result):
        raise InvalidRequest(f"{name} must be finite")
    return result


def options(value: Any, name: str, allowed: set[str] | None = None) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > 20:
        raise InvalidRequest(f"{name} must have 1–20 options")
    result = [str(item).strip().lower() for item in value]
    if any(not item or len(item) > 60 for item in result) or len(set(result)) != len(result):
        raise InvalidRequest(f"{name} contains empty or duplicate options")
    if allowed and any(item not in allowed for item in result):
        raise InvalidRequest(f"{name} has an unsupported option")
    return result
