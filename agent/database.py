"""SQLite persistence. Source of truth for finalized episodes."""
import json
import sqlite3
import time
from typing import Optional

import config
from episode import Episode, KeyObservation


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH))
    # WAL mode: allows concurrent reads while writing, survives crashes cleanly.
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    _migrate(conn)
    return conn


def save_episode(conn: sqlite3.Connection, episode: Episode) -> None:
    d = episode.to_dict()
    conn.execute("""
        INSERT INTO episodes
            (id, case_name, issue_worked_on, work_type, started_at, ended_at,
             duration_minutes, active_seconds, key_observations, created_at, is_reportable)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(id) DO UPDATE SET
            case_name        = excluded.case_name,
            issue_worked_on  = excluded.issue_worked_on,
            work_type        = excluded.work_type,
            ended_at         = excluded.ended_at,
            duration_minutes = excluded.duration_minutes,
            active_seconds   = excluded.active_seconds,
            key_observations = excluded.key_observations
    """, (
        d["id"], d["case_name"], d.get("issue_worked_on"), d.get("work_type", "project"),
        d["started_at"], d["ended_at"],
        d["duration_minutes"], d.get("active_seconds"),
        json.dumps(d["key_observations"]), d["created_at"],
    ))
    conn.commit()

    # Update recent contexts for autocomplete
    if d.get("case_name"):
        upsert_recent_context(conn, d["case_name"], d.get("issue_worked_on"), d.get("work_type", "project"))


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


# ── Recent contexts (for UI autocomplete) ─────────────────────────────────────

def get_recent_cases(conn: sqlite3.Connection) -> list[str]:
    """Return case names ordered by most recently used."""
    rows = conn.execute(
        "SELECT case_name FROM recent_contexts ORDER BY last_used DESC LIMIT 50"
    ).fetchall()
    return [r[0] for r in rows]


def get_recent_issues(conn: sqlite3.Connection, case_name: str) -> list[str]:
    """Return issue names for a given case, ordered by most recently used."""
    rows = conn.execute(
        "SELECT issue FROM recent_contexts WHERE case_name = ? AND issue != '' "
        "ORDER BY last_used DESC LIMIT 20",
        (case_name,),
    ).fetchall()
    return [r[0] for r in rows]


def upsert_recent_context(
    conn: sqlite3.Connection,
    case_name: str,
    issue: Optional[str],
    work_type: str,
) -> None:
    """Insert or update a recent context record for autocomplete."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # Use empty string as sentinel for NULL issue so the UNIQUE(case_name, issue) works.
    issue_key = issue or ""
    conn.execute("""
        INSERT INTO recent_contexts (case_name, issue, work_type, last_used, use_count)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(case_name, issue) DO UPDATE SET
            last_used = excluded.last_used,
            use_count = use_count + 1
    """, (case_name, issue_key, work_type, now))
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
                issue_worked_on  TEXT,
                work_type        TEXT NOT NULL DEFAULT 'project',
                started_at       TEXT NOT NULL,
                ended_at         TEXT,
                duration_minutes REAL,
                active_seconds   REAL,
                key_observations TEXT NOT NULL DEFAULT '[]',
                created_at       TEXT NOT NULL,
                synced_at        TEXT,
                is_reportable    INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.commit()
    else:
        # Add missing columns to existing installations
        if "is_reportable" not in cols:
            print("[db] adding is_reportable column")
            conn.execute("ALTER TABLE episodes ADD COLUMN is_reportable INTEGER NOT NULL DEFAULT 1")
        if "issue_worked_on" not in cols:
            print("[db] adding issue_worked_on column")
            conn.execute("ALTER TABLE episodes ADD COLUMN issue_worked_on TEXT")
        if "work_type" not in cols:
            print("[db] adding work_type column")
            conn.execute("ALTER TABLE episodes ADD COLUMN work_type TEXT NOT NULL DEFAULT 'project'")
        if "active_seconds" not in cols:
            print("[db] adding active_seconds column")
            conn.execute("ALTER TABLE episodes ADD COLUMN active_seconds REAL")
        conn.commit()

    # Create recent_contexts table for UI autocomplete.
    # issue uses '' as sentinel for "no issue" so UNIQUE(case_name, issue) works
    # across all SQLite versions (COALESCE in UNIQUE is only in SQLite 3.38+).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recent_contexts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            case_name TEXT NOT NULL,
            issue     TEXT NOT NULL DEFAULT '',
            work_type TEXT NOT NULL DEFAULT 'project',
            last_used TEXT NOT NULL,
            use_count INTEGER NOT NULL DEFAULT 1,
            UNIQUE(case_name, issue)
        )
    """)
    conn.commit()
