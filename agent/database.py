"""SQLite persistence. Source of truth."""
import json
import sqlite3
import time
from typing import Optional

import config
from episode import Episode


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            started_at  TEXT NOT NULL,
            ended_at    TEXT,
            summary     TEXT NOT NULL DEFAULT '',
            storyline   TEXT NOT NULL DEFAULT '[]',
            screenshots TEXT NOT NULL DEFAULT '[]',
            created_at  TEXT NOT NULL,
            synced_at   TEXT
        )
    """)
    conn.commit()
    return conn


def save_episode(conn: sqlite3.Connection, episode: Episode) -> None:
    d = episode.to_dict()
    conn.execute("""
        INSERT INTO episodes (id, title, started_at, ended_at, summary, storyline, screenshots, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title       = excluded.title,
            ended_at    = excluded.ended_at,
            summary     = excluded.summary,
            storyline   = excluded.storyline,
            screenshots = excluded.screenshots
    """, (
        d["id"], d["title"], d["started_at"], d["ended_at"], d["summary"],
        json.dumps(d["storyline"]), json.dumps(d["screenshots"]), d["created_at"],
    ))
    conn.commit()


def update_screenshot_url(conn: sqlite3.Connection, episode_id: str, screenshot_id: str, url: str) -> None:
    """Update storageUrl for a single screenshot inside the JSONB array."""
    row = conn.execute("SELECT screenshots FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    if not row:
        return
    screenshots = json.loads(row[0])
    for s in screenshots:
        if s["id"] == screenshot_id:
            s["storageUrl"] = url
            break
    conn.execute("UPDATE episodes SET screenshots = ? WHERE id = ?", (json.dumps(screenshots), episode_id))
    conn.commit()


def get_episode_dict(conn: sqlite3.Connection, episode_id: str) -> Optional[dict]:
    """Return the canonical episode dict from SQLite, or None if not found."""
    row = conn.execute(
        "SELECT id, title, started_at, ended_at, summary, storyline, screenshots, created_at "
        "FROM episodes WHERE id = ?",
        (episode_id,)
    ).fetchone()
    if not row:
        return None
    keys = ["id", "title", "started_at", "ended_at", "summary", "storyline", "screenshots", "created_at"]
    d = dict(zip(keys, row))
    d["storyline"] = json.loads(d["storyline"])
    d["screenshots"] = json.loads(d["screenshots"])
    return d


def mark_synced(conn: sqlite3.Connection, episode_id: str) -> None:
    conn.execute(
        "UPDATE episodes SET synced_at = ? WHERE id = ?",
        (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), episode_id),
    )
    conn.commit()
