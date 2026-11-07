"""Connection management for the campaign database.

One control-plane process owns the database (HLD 10 §5.3), so there is a single writer.
Connections use WAL, enforce foreign keys and wait for locks instead of failing immediately.
Writes go through ``transaction()``, which opens an IMMEDIATE transaction so two writers can
never interleave a read-then-write (the atomic episode claim relies on this).
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from activequal.storage.schema import MIGRATIONS

BUSY_TIMEOUT_MS = 5000


class Database:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        # check_same_thread=False: the HTTP server is threaded; self._lock serializes use.
        self._conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = FULL")
        self.migrate()

    def migrate(self) -> None:
        with self._lock:
            applied = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if applied > len(MIGRATIONS):
                raise RuntimeError(f"database is at version {applied}, newer than this software ({len(MIGRATIONS)})")
            for number, script in enumerate(MIGRATIONS[applied:], start=applied + 1):
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    for statement in _split(script):
                        self._conn.execute(statement)
                    self._conn.execute(f"PRAGMA user_version = {number}")
                    self._conn.execute("COMMIT")
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a block atomically; any exception rolls everything back."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _split(script: str) -> list[str]:
    """Split a migration into statements. ``sqlite3.complete_statement`` copes with the triggers' inner ';'."""
    statements, buffer = [], ""
    for line in script.splitlines():
        buffer += line + "\n"
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        raise ValueError("migration ends with an incomplete statement")
    return statements
