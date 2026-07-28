"""
BuildHarvey Desktop Agent — main loop.

Run:  python main.py
"""
import shutil
import time
import traceback
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import config
import capture
import database
import observer
import sync
from episode import Episode
from episode_engine import EpisodeEngine


def main() -> None:
    print("[agent] BuildHarvey starting")
    print(f"[agent] db          {config.DB_PATH}")
    print(f"[agent] screenshots {config.SCREENSHOTS_DIR}")

    conn = database.connect()
    engine = EpisodeEngine()
    sync.start()

    prev_frame: Optional[Path] = None

    while True:
        try:
            prev_frame = _cycle(conn, engine, prev_frame)
        except KeyboardInterrupt:
            print("\n[agent] shutting down")
            closed = engine.check_inactivity(time.time() - config.INACTIVITY_TIMEOUT_SECONDS - 1)
            if closed:
                database.save_episode(conn, closed)
                sync.enqueue_episode(closed.to_dict())
            break
        except Exception:
            traceback.print_exc()

        time.sleep(config.CAPTURE_INTERVAL_SECONDS)


def _cycle(conn, engine: EpisodeEngine, prev_frame: Optional[Path]) -> Optional[Path]:
    now = time.time()

    # ── Observe ───────────────────────────────────────────────────────────────
    obs = observer.observe(prev_frame, config.TEMP_FRAME_PATH)

    if obs is None:
        # No change — only check inactivity
        closed = engine.check_inactivity(now)
        if closed:
            database.save_episode(conn, closed)
            sync.enqueue_episode(closed.to_dict())
        return prev_frame

    print(f"[agent] {obs.app!r} | {obs.window_title!r}")

    # ── Engine decides episode boundary ───────────────────────────────────────
    result = engine.ingest(obs, now)

    # ── Copy frame to permanent location (episode_id now known) ──────────────
    screenshot_id = str(uuid.uuid4())
    dest = capture.screenshot_path(result.active_episode.id, screenshot_id)
    shutil.copy2(config.TEMP_FRAME_PATH, dest)

    # ── Attach observation to episode ─────────────────────────────────────────
    result.active_episode.record_observation(screenshot_id, dest, obs)

    # ── SQLite first, always ──────────────────────────────────────────────────
    database.save_episode(conn, result.active_episode)
    if result.closed_episode:
        database.save_episode(conn, result.closed_episode)

    # ── Enqueue async sync (never blocks) ────────────────────────────────────
    sync.enqueue_screenshot(result.active_episode.id, screenshot_id, dest)
    if result.closed_episode:
        sync.enqueue_episode(result.closed_episode.to_dict())

    return dest


if __name__ == "__main__":
    main()
