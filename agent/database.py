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
            (id, case_name, started_at, ended_at, duration_minutes, key_observations,
             created_at, is_reportable)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
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


def mark_invalid_episodes(conn: sqlite3.Connection) -> list[str]:
    """
    Mark (not delete) episodes that fail validity checks.
    Logs each affected record before updating. Returns list of affected IDs.
    Administrative episodes are NOT marked invalid — they are valid when evidence exists.
    """
    invalid_conditions = """
        TRIM(case_name) = '' OR case_name IS NULL
        OR key_observations = '[]' OR key_observations IS NULL
        OR duration_minutes IS NULL
        OR (duration_minutes < 0.5 AND (key_observations = '[]' OR key_observations IS NULL))
        OR LOWER(TRIM(case_name)) IN (
            'optional','file edit','sql editor','new tab',
            'file path','matter of','case reset','case requests',
            'summarizing timeline','new yo','active session',
            '• instagram d','quenlin blackwell •'
        )
    """
    rows = conn.execute(
        f"SELECT id, case_name, duration_minutes FROM episodes WHERE {invalid_conditions}"
    ).fetchall()

    if not rows:
        return []

    ids = [r[0] for r in rows]
    for r in rows:
        dur = r[2] if r[2] is not None else 0
        print(f"[db] marking invalid: '{r[1]}' ({dur:.1f}min) id={r[0][:8]}")

    placeholders = ",".join("?" * len(ids))
    conn.execute(
        f"UPDATE episodes SET is_reportable = 0 WHERE id IN ({placeholders})",
        ids,
    )
    conn.commit()
    return ids


def get_invalid_ids(conn: sqlite3.Connection) -> list[str]:
    """Return IDs of all episodes marked is_reportable=0."""
    rows = conn.execute(
        "SELECT id FROM episodes WHERE is_reportable = 0"
    ).fetchall()
    return [r[0] for r in rows]


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
                synced_at        TEXT,
                is_reportable    INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.commit()
        return

    # Add is_reportable column if missing from an existing table
    if "is_reportable" not in cols:
        print("[db] adding is_reportable column")
        conn.execute("ALTER TABLE episodes ADD COLUMN is_reportable INTEGER NOT NULL DEFAULT 1")
        conn.commit()
