"""
Async background sync worker.
The main loop never waits for Supabase.
SQLite is written first. This worker catches up asynchronously.
"""
import queue
import sqlite3
import threading
import traceback
from pathlib import Path
from typing import Optional

import config
import database
import storage

_queue: queue.Queue = queue.Queue()


def start() -> None:
    """Start the background sync worker thread (daemon — exits with main process)."""
    t = threading.Thread(target=_worker, name="sync-worker", daemon=True)
    t.start()
    print("[sync] worker started")


def enqueue_screenshot(episode_id: str, screenshot_id: str, local_path: Path) -> None:
    """Queue a screenshot for upload and episode sync."""
    _queue.put({"type": "screenshot", "episode_id": episode_id,
                "screenshot_id": screenshot_id, "local_path": local_path})


def enqueue_episode(episode_dict: dict) -> None:
    """Queue a closed or updated episode for Supabase upsert."""
    _queue.put({"type": "episode", "data": episode_dict})


# ── Worker ─────────────────────────────────────────────────────────────────────

def _worker() -> None:
    conn = database.connect()
    client = _make_client()

    while True:
        task = _queue.get()
        try:
            _process(task, conn, client)
        except Exception:
            traceback.print_exc()
        finally:
            _queue.task_done()


def _process(task: dict, conn: sqlite3.Connection, client) -> None:
    if task["type"] == "screenshot":
        ep_id = task["episode_id"]
        ss_id = task["screenshot_id"]
        local_path = task["local_path"]

        url = storage.upload(local_path, ep_id, ss_id)
        if url:
            database.update_screenshot_url(conn, ep_id, ss_id, url)
            print(f"[sync] uploaded  {ss_id[:8]}…")

        # Upsert the episode with whatever storageUrl we have now
        ep_dict = database.get_episode_dict(conn, ep_id)
        if ep_dict:
            _upsert(client, ep_dict, conn)

    elif task["type"] == "episode":
        _upsert(client, task["data"], conn)


def _upsert(client, episode_dict: dict, conn: sqlite3.Connection) -> None:
    if not client:
        return
    try:
        client.table("episodes").upsert(episode_dict).execute()
        database.mark_synced(conn, episode_dict["id"])
        print(f"[sync] synced    {episode_dict['id'][:8]}…")
    except Exception as exc:
        print(f"[sync] upsert failed: {exc}")


def _make_client():
    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        print("[sync] Supabase not configured — running offline")
        return None
    try:
        from supabase import create_client
        return create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    except Exception as exc:
        print(f"[sync] could not create client: {exc}")
        return None
