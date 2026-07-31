"""
Async background sync worker.
The main loop never waits for the server — SQLite is written first.
Syncs via /api/episodes/sync (device token auth) — no database credentials.
"""
import json
import queue
import sqlite3
import threading
import traceback
import urllib.request
import urllib.error

import auth
import config
import database

_queue: queue.Queue = queue.Queue()


def start() -> None:
    t = threading.Thread(target=_worker, name="sync-worker", daemon=True)
    t.start()
    print("[sync] worker started")


def enqueue_episode(episode_dict: dict) -> None:
    """Queue a finalized episode for server sync."""
    _queue.put(episode_dict)


def enqueue_cleanup(invalid_ids: list[str]) -> None:
    """Queue an is_reportable=false update to the server for known invalid episodes."""
    if invalid_ids:
        _queue.put({"_type": "cleanup", "ids": invalid_ids})


def _worker() -> None:
    conn = database.connect()
    token = auth.read_credential()
    if not token:
        print("[sync] no device credential — running offline")
    while True:
        task = _queue.get()
        try:
            if isinstance(task, dict) and task.get("_type") == "cleanup":
                _cleanup(token, task["ids"])
            else:
                _upsert(token, task, conn)
        except Exception:
            traceback.print_exc()
        finally:
            _queue.task_done()


def _post(path: str, body: dict, token: str) -> dict:
    url = f"{config.BASE_URL}{path}"
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _upsert(token: str | None, episode_dict: dict, conn: sqlite3.Connection) -> None:
    if not token:
        return
    try:
        _post('/api/episodes/sync', episode_dict, token)
        database.mark_synced(conn, episode_dict["id"])
        print(f"[sync] synced {episode_dict['id'][:8]}… '{episode_dict['case_name']}'")
    except Exception as exc:
        print(f"[sync] upsert failed: {exc}")


def _cleanup(token: str | None, invalid_ids: list[str]) -> None:
    if not token or not invalid_ids:
        return
    try:
        _post('/api/episodes/invalidate', {"ids": invalid_ids}, token)
        print(f"[sync] marked {len(invalid_ids)} invalid episode(s)")
    except Exception as exc:
        print(f"[sync] cleanup failed: {exc}")
