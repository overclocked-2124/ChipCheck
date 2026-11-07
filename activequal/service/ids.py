"""Server-generated identifiers and the clock (HLD 05 §4: UUIDv7, sortable by creation time)."""

from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock:
    """A settable clock for tests (lease expiry, certificate-style checks)."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("clock needs a timezone-aware time")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def set(self, value: datetime) -> None:
        self._now = value

    def advance(self, seconds: float) -> None:
        from datetime import timedelta
        self._now += timedelta(seconds=seconds)


def isoformat(moment: datetime) -> str:
    """RFC 3339 UTC with millisecond precision; fixed width, so strings sort like times."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def parse_time(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


_lock = threading.Lock()
_last_ms = 0
_counter = 0


def new_id() -> str:
    """UUIDv7 as a string. Monotonic within the process even inside one millisecond."""
    global _last_ms, _counter
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms <= _last_ms:
            ms, _counter = _last_ms, _counter + 1
            if _counter >= 1 << 12:       # counter exhausted: move to the next millisecond
                ms, _counter = _last_ms + 1, 0
        else:
            _counter = 0
        _last_ms = ms
        counter = _counter
    rand = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | counter << 64 | 0b10 << 62 | rand
    return str(uuid.UUID(int=value))
