import sqlite3
import tempfile
import unittest
from pathlib import Path

from activequal.storage.database import Database
from activequal.storage.schema import MIGRATIONS


def seed(db):
    with db.transaction() as c:
        c.execute("INSERT INTO projects VALUES ('p', 'demo')")
        c.execute("INSERT INTO events (entity, campaign_id, new_state, actor_type, actor_id, reason_code, reason,"
                  " backend_ts) VALUES ('campaign', 'c', 'DRAFT', 'researcher', 'sam', 'CREATED', 'created', 't')")


class DatabaseTests(unittest.TestCase):
    def test_migrates_and_records_version(self):
        db = Database()
        self.assertEqual(db.one("PRAGMA user_version")[0], len(MIGRATIONS))
        tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
        for expected in ("projects", "contract_versions", "fixtures", "calibrations", "campaigns", "candidates",
                         "episodes", "leases", "observations", "results", "verdicts", "events", "traces",
                         "counterexamples", "contract_approvals"):
            self.assertIn(expected, tables)

    def test_reopening_a_file_database_does_not_remigrate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "aq.db"
            first = Database(path)
            seed(first)
            first.close()
            second = Database(path)
            self.assertEqual(second.one("SELECT COUNT(*) FROM projects")[0], 1)
            self.assertEqual(second.one("PRAGMA journal_mode")[0], "wal")

    def test_refuses_a_newer_database(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "aq.db"
            Database(path).close()
            raw = sqlite3.connect(path)
            raw.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
            raw.close()
            with self.assertRaises(RuntimeError):
                Database(path)

    def test_events_are_append_only(self):
        db = Database()
        seed(db)
        with self.assertRaises(sqlite3.DatabaseError):
            with db.transaction() as c:
                c.execute("UPDATE events SET reason = 'edited'")
        with self.assertRaises(sqlite3.DatabaseError):
            with db.transaction() as c:
                c.execute("DELETE FROM events")
        self.assertEqual(db.one("SELECT reason FROM events")["reason"], "created")

    def test_transaction_rolls_back_on_error(self):
        db = Database()
        with self.assertRaises(RuntimeError):
            with db.transaction() as c:
                c.execute("INSERT INTO projects VALUES ('p', 'demo')")
                raise RuntimeError("boom")
        self.assertEqual(db.one("SELECT COUNT(*) FROM projects")[0], 0)

    def test_foreign_keys_are_enforced(self):
        db = Database()
        with self.assertRaises(sqlite3.IntegrityError):
            with db.transaction() as c:
                c.execute("INSERT INTO fixtures VALUES ('f', 'missing', 'A', '[]', NULL, 'h', 't')")


if __name__ == "__main__":
    unittest.main()
