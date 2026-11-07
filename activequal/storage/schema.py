"""SQLite schema for the campaign database (HLD 08 §4).

Migrations are an ordered list of SQL scripts; ``user_version`` records how many have run.
The audit ``events`` table is append-only: triggers reject UPDATE and DELETE (HLD 08 §2).
Requested and measured values live in separate columns (HLD 01 principle 5).
"""

from __future__ import annotations

MIGRATIONS: list[str] = [
    """
    CREATE TABLE projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL
    );

    CREATE TABLE contract_versions (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        contract_key TEXT NOT NULL,              -- the logical contract; versions share it
        version INTEGER NOT NULL,
        canonical_json TEXT NOT NULL,
        contract_hash TEXT NOT NULL,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        approvals_required INTEGER NOT NULL CHECK (approvals_required >= 1),
        UNIQUE (contract_key, version),
        UNIQUE (project_id, contract_hash)
    );

    CREATE TABLE contract_approvals (
        contract_version_id TEXT NOT NULL REFERENCES contract_versions(id),
        reviewer TEXT NOT NULL,
        approved_at TEXT NOT NULL,
        PRIMARY KEY (contract_version_id, reviewer)
    );

    CREATE TABLE fixtures (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        revision TEXT NOT NULL,
        capabilities_json TEXT NOT NULL,
        current_calibration_id TEXT,
        token_sha256 TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE calibrations (
        id TEXT PRIMARY KEY,
        fixture_id TEXT NOT NULL REFERENCES fixtures(id),
        channels_json TEXT NOT NULL,
        meter_identity TEXT NOT NULL,
        operator TEXT NOT NULL,
        created_at TEXT NOT NULL,
        valid_until TEXT NOT NULL
    );

    CREATE TABLE campaigns (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        state TEXT NOT NULL,
        version INTEGER NOT NULL,                -- optimistic concurrency (HLD 03 §20)
        contract_version_id TEXT NOT NULL REFERENCES contract_versions(id),
        fixture_id TEXT NOT NULL REFERENCES fixtures(id),
        planner_method TEXT NOT NULL,
        planner_config_json TEXT NOT NULL,
        seed INTEGER NOT NULL,
        plan_json TEXT NOT NULL,
        discovery_budget INTEGER NOT NULL CHECK (discovery_budget >= 1),
        verification_budget INTEGER NOT NULL CHECK (verification_budget >= 0),
        software_version TEXT NOT NULL,
        armed_tuple_json TEXT,                   -- what was approved at arm time (HLD 03 §6.2)
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    -- At most one active campaign per fixture (HLD 03 §20).
    CREATE UNIQUE INDEX one_active_campaign_per_fixture ON campaigns(fixture_id)
        WHERE state IN ('ARMED', 'RUNNING', 'PAUSING', 'PAUSED', 'ABORTING', 'LOCKED_OUT');

    CREATE TABLE candidates (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES campaigns(id),
        planner_sequence INTEGER NOT NULL,
        body_sha256 TEXT NOT NULL,               -- idempotency: same key, different body is a conflict
        conditions_json TEXT NOT NULL,
        planner_reason TEXT NOT NULL,
        reason_code TEXT NOT NULL,
        role TEXT NOT NULL,
        linked_episode_id TEXT,
        repeat_reason TEXT,
        state TEXT NOT NULL,
        rejection_json TEXT,
        created_at TEXT NOT NULL,
        UNIQUE (campaign_id, planner_sequence)
    );

    CREATE TABLE episodes (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES campaigns(id),
        candidate_id TEXT NOT NULL UNIQUE REFERENCES candidates(id),   -- episode creation is keyed by candidate
        attempt INTEGER NOT NULL DEFAULT 1,
        state TEXT NOT NULL,
        outcome TEXT,
        role TEXT NOT NULL,
        linked_episode_id TEXT REFERENCES episodes(id),
        requested_json TEXT NOT NULL,
        contract_hash TEXT NOT NULL,
        fixture_id TEXT NOT NULL REFERENCES fixtures(id),
        created_at TEXT NOT NULL,
        finalized_at TEXT
    );
    CREATE INDEX episodes_by_campaign ON episodes(campaign_id, created_at);

    CREATE TABLE leases (
        id TEXT PRIMARY KEY,
        episode_id TEXT NOT NULL REFERENCES episodes(id),
        controller_instance_id TEXT NOT NULL,
        fixture_id TEXT NOT NULL REFERENCES fixtures(id),
        attempt INTEGER NOT NULL,
        contract_hash TEXT NOT NULL,
        issued_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        last_heartbeat_at TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'RELEASED', 'NEEDS_RECONCILIATION'))
    );
    -- One physical owner per fixture and one live lease per episode (HLD 03 §9.1, §20).
    CREATE UNIQUE INDEX one_active_lease_per_fixture ON leases(fixture_id) WHERE state IN ('ACTIVE', 'NEEDS_RECONCILIATION');
    CREATE UNIQUE INDEX one_active_lease_per_episode ON leases(episode_id) WHERE state IN ('ACTIVE', 'NEEDS_RECONCILIATION');

    CREATE TABLE observations (
        episode_id TEXT NOT NULL REFERENCES episodes(id),
        attempt INTEGER NOT NULL,
        metric TEXT NOT NULL,
        requested REAL,                          -- only for metrics that mirror a control
        measured REAL,                           -- NULL means attempted but unavailable
        uncertainty REAL,
        quality_json TEXT NOT NULL,
        PRIMARY KEY (episode_id, attempt, metric)
    );

    CREATE TABLE results (
        episode_id TEXT NOT NULL REFERENCES episodes(id),
        attempt INTEGER NOT NULL,
        manifest_hash TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        accepted_at TEXT NOT NULL,
        PRIMARY KEY (episode_id, attempt)
    );

    CREATE TABLE verdicts (
        episode_id TEXT PRIMARY KEY REFERENCES episodes(id),
        outcome TEXT NOT NULL,
        reason_code TEXT NOT NULL,
        reason TEXT NOT NULL,
        margins_json TEXT NOT NULL,
        robustness REAL,
        requirements_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity TEXT NOT NULL CHECK (entity IN ('campaign', 'candidate', 'episode', 'lease', 'fixture', 'contract')),
        campaign_id TEXT,
        episode_id TEXT,
        attempt INTEGER,
        previous_state TEXT,
        new_state TEXT NOT NULL,
        actor_type TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        reason_code TEXT NOT NULL,
        reason TEXT NOT NULL,
        backend_ts TEXT NOT NULL,
        controller_ts TEXT,
        contract_hash TEXT,
        fixture_id TEXT,
        detail_json TEXT
    );
    CREATE INDEX events_by_campaign ON events(campaign_id, id);
    CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
    CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

    CREATE TABLE traces (
        sha256 TEXT PRIMARY KEY,
        episode_id TEXT REFERENCES episodes(id),
        media_type TEXT NOT NULL,
        bytes INTEGER NOT NULL,
        capture_json TEXT NOT NULL,
        path TEXT NOT NULL
    );

    CREATE TABLE counterexamples (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES campaigns(id),
        original_episode_id TEXT NOT NULL REFERENCES episodes(id),
        minimized_json TEXT NOT NULL,
        intervals_json TEXT NOT NULL,
        reproductions INTEGER NOT NULL,
        attempts INTEGER NOT NULL,
        origin TEXT NOT NULL CHECK (origin IN ('seeded', 'natural', 'unknown')),
        created_at TEXT NOT NULL
    );
    """,
]
