"""The bench's local evidence spool (HLD 08 §3, HLD 03 §8 ``EVIDENCE_PENDING``).

One file per pending result, written atomically and flushed to disk before any upload is
attempted, so a control-plane outage or a bench crash never loses an accepted measurement.
Files are removed only after Backend accepted the result (or returned the stored one).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterator


class Spool:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, episode_id: str, attempt: int) -> Path:
        safe = "".join(c for c in episode_id if c.isalnum() or c in "-_")
        if safe != episode_id or not safe:
            raise ValueError("episode id is not safe to use as a file name")
        return self.directory / f"{safe}.{int(attempt)}.json"

    def save(self, payload: dict[str, Any]) -> Path:
        path = self._path(payload["episodeId"], payload["attempt"])
        fd, tmp = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return path

    def pending(self) -> Iterator[dict[str, Any]]:
        for path in sorted(self.directory.glob("*.json")):
            yield json.loads(path.read_text(encoding="utf-8"))

    def remove(self, payload: dict[str, Any]) -> None:
        self._path(payload["episodeId"], payload["attempt"]).unlink(missing_ok=True)

    def __len__(self) -> int:
        return sum(1 for _ in self.directory.glob("*.json"))
