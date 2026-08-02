"""
Async background sync worker.
The main loop never waits for the server — SQLite is written first.
Syncs via /api/episodes/sync (device token auth) — no database credentials.
Screenshots are uploaded after each episode sync using signed upload URLs.
"""
import json
import os
import queue
import sqlite3
import threading
import time as _time
import traceback
import urllib.request
import urllib.error
from pathlib import Path

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


def _get(path: str, token: str) -> dict:
    url = f"{config.BASE_URL}{path}"
    req = urllib.request.Request(
        url,
        headers={'Authorization': f'Bearer {token}'},
        method='GET',
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _upsert(token: str | None, episode_dict: dict, conn: sqlite3.Connection) -> None:
    if not token:
        return
    episode_id = episode_dict["id"]
    evidence_paths = episode_dict.pop("evidence_paths", [])

    for attempt in range(5):
        try:
            _post('/api/episodes/sync', episode_dict, token)
            database.mark_synced(conn, episode_id)
            print(f"[sync] synced {episode_id[:8]}… '{episode_dict['case_name']}'")
            break
        except Exception as exc:
            print(f"[sync] attempt {attempt + 1} failed: {exc}")
            _time.sleep(2 ** attempt)
    else:
        print(f"[sync] gave up on {episode_id[:8]} — will retry on restart")
        return  # Don't upload screenshots if episode sync failed

    # Upload evidence screenshots after successful episode sync
    if evidence_paths and token:
        _upload_screenshots(token, episode_id, evidence_paths)


def _upload_screenshots(token: str, episode_id: str, paths: list[str]) -> None:
    """Upload each evidence screenshot using signed upload URLs."""
    for path in paths:
        p = Path(path)
        if not p.exists():
            print(f"[sync] screenshot missing, skipping: {path}")
            continue

        filename = p.name
        for attempt in range(5):
            try:
                # 1. Get signed upload URL
                url_data = _get(
                    f'/api/screenshots/upload-url?episode_id={episode_id}&filename={filename}',
                    token,
                )
                upload_url = url_data['upload_url']
                storage_path = url_data['path']

                # 2. PUT image to signed URL (no auth header)
                img_data = p.read_bytes()
                put_req = urllib.request.Request(
                    upload_url,
                    data=img_data,
                    headers={'Content-Type': 'image/jpeg'},
                    method='PUT',
                )
                with urllib.request.urlopen(put_req, timeout=30):
                    pass

                # 3. Confirm upload
                _post('/api/screenshots/confirm', {
                    'episode_id': episode_id,
                    'path': storage_path,
                }, token)

                print(f"[sync] uploaded screenshot {filename} for {episode_id[:8]}")
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 409:
                    # Already uploaded — idempotent
                    break
                print(f"[sync] screenshot upload attempt {attempt + 1} failed: {exc}")
                _time.sleep(2 ** attempt)
            except Exception as exc:
                print(f"[sync] screenshot upload attempt {attempt + 1} failed: {exc}")
                _time.sleep(2 ** attempt)


def _cleanup(token: str | None, invalid_ids: list[str]) -> None:
    if not token or not invalid_ids:
        return
    try:
        _post('/api/episodes/invalidate', {"ids": invalid_ids}, token)
        print(f"[sync] marked {len(invalid_ids)} invalid episode(s)")
    except Exception as exc:
        print(f"[sync] cleanup failed: {exc}")
