"""
Async background sync worker.
The main loop never waits for Supabase — SQLite is written first.
"""
import queue
import sqlite3
import threading
import traceback

import config
import database

_queue: queue.Queue = queue.Queue()


def start() -> None:
    t = threading.Thread(target=_worker, name="sync-worker", daemon=True)
    t.start()
    print("[sync] worker started")


def enqueue_episode(episode_dict: dict) -> None:
    """Queue a finalized episode for Supabase upsert."""
    _queue.put(episode_dict)


def _worker() -> None:
    conn = database.connect()
    client = _make_client()
    while True:
        task = _queue.get()
        try:
            _upsert(client, task, conn)
        except Exception:
            traceback.print_exc()
        finally:
            _queue.task_done()


def _upsert(client, episode_dict: dict, conn: sqlite3.Connection) -> None:
    if not client:
        return
    try:
        client.table("episodes").upsert(episode_dict).execute()
        database.mark_synced(conn, episode_dict["id"])
        print(f"[sync] synced {episode_dict['id'][:8]}… '{episode_dict['case_name']}'")
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
