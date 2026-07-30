"""SQLite persistence. Source of truth for finalized episodes."""
import json
import sqlite3
import time
from typing import Optional

import config
from episode import Episode, KeyObservation


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH))
    _migrate(conn)
    return conn


def save_episode(conn: sqlite3.Connection, episode: Episode) -> None:
    d = episode.to_dict()
    conn.execute("""
        INSERT INTO episodes
            (id, case_name, started_at, ended_at, duration_minutes, key_observations, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            case_name        = excluded.case_name,
            ended_at         = excluded.ended_at,
            duration_minutes = excluded.duration_minutes,
            key_observations = excluded.key_observations
    """, (
        d["id"], d["case_name"], d["started_at"], d["ended_at"],
        d["duration_minutes"], json.dumps(d["key_observations"]), d["created_at"],
    ))
    conn.commit()


def mark_synced(conn: sqlite3.Connection, episode_id: str) -> None:
    conn.execute(
        "UPDATE episodes SET synced_at = ? WHERE id = ?",
        (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), episode_id),
    )
    conn.commit()


# ── Schema management ─────────────────────────────────────────────────────────

def _migrate(conn: sqlite3.Connection) -> None:
    """Create or migrate the episodes table to the current schema."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(episodes)").fetchall()}

    # Recreate if table is missing, has old v1 schema, or has stale screenshots column
    needs_recreate = cols and ("case_name" not in cols or "screenshots" in cols)
    if needs_recreate:
        print("[db] migrating episodes table to current schema")
        conn.execute("DROP TABLE IF EXISTS episodes")
        cols = set()

    if not cols:
        conn.execute("""
            CREATE TABLE episodes (
                id               TEXT PRIMARY KEY,
                case_name        TEXT NOT NULL,
                started_at       TEXT NOT NULL,
                ended_at         TEXT,
                duration_minutes REAL,
                key_observations TEXT NOT NULL DEFAULT '[]',
                created_at       TEXT NOT NULL,
                synced_at        TEXT
            )
        """)
        conn.commit()
