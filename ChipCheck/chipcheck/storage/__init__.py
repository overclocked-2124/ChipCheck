"""SQLite storage for ChipCheck campaign records.

Stores all experiment configurations, results, oracle verdicts,
robustness scores, and campaign metadata.
"""

from __future__ import annotations

import json
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from chipcheck.models import (
    CampaignRecord, ExperimentConfig, ExecutionResult, ExecutionStatus,
    OracleVerdict, OracleOutcome,
)

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id TEXT PRIMARY KEY,
    contract_id TEXT,
    contract_version TEXT,
    planner_type TEXT,
    benchmark TEXT,
    seed INTEGER,
    budget INTEGER,
    created_at TEXT,
    status TEXT DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    experiment_id INTEGER NOT NULL,
    trial_index INTEGER,
    phase TEXT DEFAULT 'discovery',
    input_json TEXT,
    output_json TEXT,
    -- Input parameters (denormalized for querying)
    sampling_interval_ms REAL,
    duration_ms REAL,
    sensor_type TEXT,
    number_of_samples INTEGER,
    deadline_ms REAL,
    -- Execution
    execution_status TEXT,
    -- Oracle
    oracle_outcome TEXT,
    robustness REAL,
    -- Measurements
    actual_average_interval_ms REAL,
    min_interval_ms REAL,
    max_interval_ms REAL,
    average_jitter_ms REAL,
    total_samples INTEGER,
    missed_deadlines INTEGER,
    failed_reads INTEGER,
    execution_time_ms REAL,
    average_read_execution_time_ms REAL,
    max_read_execution_time_ms REAL,
    -- Metadata
    planner_type TEXT,
    benchmark TEXT,
    seed INTEGER,
    timestamp TEXT,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id)
);

CREATE TABLE IF NOT EXISTS confirmations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    original_experiment_id INTEGER NOT NULL,
    replay_experiment_id INTEGER NOT NULL,
    replay_index INTEGER,
    oracle_outcome TEXT,
    robustness REAL,
    execution_status TEXT,
    missed_deadlines INTEGER,
    max_read_execution_time_ms REAL,
    timestamp TEXT,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id)
);

CREATE TABLE IF NOT EXISTS boundary_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    experiment_id INTEGER NOT NULL,
    trial_index INTEGER,
    oracle_outcome TEXT,
    robustness REAL,
    abs_robustness REAL,
    input_json TEXT,
    sampling_interval_ms REAL,
    sensor_type TEXT,
    number_of_samples INTEGER,
    deadline_ms REAL,
    timestamp TEXT,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id)
);

CREATE TABLE IF NOT EXISTS rejected_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    experiment_id INTEGER,
    input_json TEXT,
    rejection_reasons TEXT,
    timestamp TEXT,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id)
);
"""


class CampaignStorage:
    """SQLite-backed storage for ChipCheck campaigns."""

    def __init__(self, db_path: str = "chipcheck_results.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def create_campaign(
        self,
        campaign_id: str,
        contract_id: str,
        contract_version: str,
        planner_type: str,
        benchmark: str,
        seed: int,
        budget: int,
    ) -> None:
        self.conn.execute(
            "INSERT INTO campaigns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, contract_id, contract_version, planner_type,
             benchmark, seed, budget,
             datetime.now(timezone.utc).isoformat(), "running"),
        )
        self.conn.commit()

    def store_experiment(
        self,
        campaign_id: str,
        config: ExperimentConfig,
        result: Optional[ExecutionResult],
        verdict: Optional[OracleVerdict],
        phase: str = "discovery",
        trial_index: int = 0,
        planner_type: str = "",
        benchmark: str = "",
        seed: int = 0,
    ) -> None:
        params = config.parameters
        r = result.results if result else {}

        self.conn.execute(
            """INSERT INTO experiments
               (campaign_id, experiment_id, trial_index, phase,
                input_json, output_json,
                sampling_interval_ms, duration_ms, sensor_type,
                number_of_samples, deadline_ms,
                execution_status, oracle_outcome, robustness,
                actual_average_interval_ms, min_interval_ms, max_interval_ms,
                average_jitter_ms, total_samples, missed_deadlines,
                failed_reads, execution_time_ms,
                average_read_execution_time_ms, max_read_execution_time_ms,
                planner_type, benchmark, seed, timestamp)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                campaign_id,
                config.experiment_id,
                trial_index,
                phase,
                config.to_json(),
                result.to_json() if result else None,
                params.get("sampling_interval_ms"),
                params.get("duration_ms"),
                params.get("sensor_type"),
                params.get("number_of_samples"),
                params.get("deadline_ms"),
                result.status.value if result else None,
                verdict.outcome.value if verdict else None,
                verdict.robustness if verdict else None,
                r.get("actual_average_interval_ms"),
                r.get("min_interval_ms"),
                r.get("max_interval_ms"),
                r.get("average_jitter_ms"),
                r.get("total_samples"),
                r.get("missed_deadlines"),
                r.get("failed_reads"),
                r.get("execution_time_ms"),
                r.get("average_read_execution_time_ms"),
                r.get("max_read_execution_time_ms"),
                planner_type,
                benchmark,
                seed,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()

    def store_confirmation(
        self,
        campaign_id: str,
        original_experiment_id: int,
        replay_experiment_id: int,
        replay_index: int,
        verdict: OracleVerdict,
        result: ExecutionResult,
    ) -> None:
        r = result.results
        self.conn.execute(
            """INSERT INTO confirmations
               (campaign_id, original_experiment_id, replay_experiment_id,
                replay_index, oracle_outcome, robustness, execution_status,
                missed_deadlines, max_read_execution_time_ms, timestamp)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                campaign_id,
                original_experiment_id,
                replay_experiment_id,
                replay_index,
                verdict.outcome.value,
                verdict.robustness,
                result.status.value,
                r.get("missed_deadlines"),
                r.get("max_read_execution_time_ms"),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()

    def store_boundary(
        self,
        campaign_id: str,
        config: ExperimentConfig,
        verdict: OracleVerdict,
        trial_index: int,
    ) -> None:
        params = config.parameters
        self.conn.execute(
            """INSERT INTO boundary_results
               (campaign_id, experiment_id, trial_index,
                oracle_outcome, robustness, abs_robustness,
                input_json, sampling_interval_ms, sensor_type,
                number_of_samples, deadline_ms, timestamp)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                campaign_id,
                config.experiment_id,
                trial_index,
                verdict.outcome.value,
                verdict.robustness,
                abs(verdict.robustness) if verdict.robustness is not None else None,
                config.to_json(),
                params.get("sampling_interval_ms"),
                params.get("sensor_type"),
                params.get("number_of_samples"),
                params.get("deadline_ms"),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()

    def store_rejected_proposal(
        self,
        campaign_id: str,
        experiment_id: int,
        config: ExperimentConfig,
        reasons: list[str],
    ) -> None:
        self.conn.execute(
            """INSERT INTO rejected_proposals
               (campaign_id, experiment_id, input_json,
                rejection_reasons, timestamp)
               VALUES (?,?,?,?,?)""",
            (
                campaign_id,
                experiment_id,
                config.to_json(),
                json.dumps(reasons),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()

    def finish_campaign(self, campaign_id: str, status: str = "completed") -> None:
        self.conn.execute(
            "UPDATE campaigns SET status = ? WHERE campaign_id = ?",
            (status, campaign_id),
        )
        self.conn.commit()

    def get_campaign_experiments(self, campaign_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM experiments WHERE campaign_id = ? ORDER BY trial_index",
            (campaign_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_campaign_confirmations(self, campaign_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM confirmations WHERE campaign_id = ? ORDER BY replay_index",
            (campaign_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_campaign_boundary(self, campaign_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM boundary_results WHERE campaign_id = ? ORDER BY trial_index",
            (campaign_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_rejected_proposals(self, campaign_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM rejected_proposals WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_campaign(self, campaign_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM campaigns WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_campaigns(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM campaigns ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self.conn.close()

