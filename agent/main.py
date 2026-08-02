"""
BuildHarvey Desktop Agent.

Run:  python main.py
      (or launched automatically by app.py after credential and permissions are set up)

Loop:
  1. Check if browser is connected (WebSocket session gate).
  2. Capture screen → extract context → build Observation.
  3. If screenshot available and API key configured: analyze with Claude Vision.
     Engine decides: continue current episode, open new, or transition.
  4. If no screenshot or no API key: update metadata context only.
  5. On episode close: finalize → persist to SQLite → enqueue server sync.

Session gate:
  - Agent only records while at least one BuildHarvey browser tab is connected.
  - After the last tab closes, a 10-minute grace period allows brief interruptions.
  - After 10 minutes with no browser: active episode is finalized, agent idles.
  - Agent resumes on reconnect — no duplicate episodes.

Startup:
  - Mark locally invalid episodes (not deleted — just flagged).
  - Enqueue server cleanup for those IDs.

Degraded mode (no API key):
  - Vision analysis skipped; no Episodes opened.
  - Metadata tracked in memory only.
  - System keeps running; no garbage Episodes created.
"""
import threading
import time
import traceback
from typing import Callable, Optional

from dotenv import load_dotenv
load_dotenv()

import config
import database
import finalizer
import observer
import session_server
import sync
import vision
from episode import Episode
from episode_engine import EpisodeEngine


def main(
    state_callback: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> None:
    print("[agent] BuildHarvey starting")
    print(f"[agent] db {config.DB_PATH}")
    if not config.ANTHROPIC_API_KEY:
        print("[agent] WARNING: ANTHROPIC_API_KEY not set — running in degraded mode (no episodes)")

    session_server.start()

    conn = database.connect()

    # Mark known garbage and propagate to server
    invalid_ids = database.mark_invalid_episodes(conn)
    if invalid_ids:
        sync.enqueue_cleanup(invalid_ids)

    engine = EpisodeEngine()
    sync.start()

    while True:
        if stop_event is not None and stop_event.is_set():
            print("[agent] stop_event set — shutting down")
            if engine.active:
                engine.active.close()
                _close_and_save(conn, engine.active)
            break
        try:
            if session_server.is_browser_active():
                if state_callback:
                    state_callback('recording' if engine.active else 'waiting')
                try:
                    _cycle(conn, engine)
                except Exception:
                    traceback.print_exc()
                    try:
                        observer.reset()
                    except Exception:
                        pass
                time.sleep(config.CAPTURE_INTERVAL_SECONDS)
            else:
                # Browser has been absent for > 10 min — finalize and idle
                if engine.active:
                    engine.active.close()
                    _close_and_save(conn, engine.active)
                    engine.active = None
                if state_callback:
                    state_callback('idle')
                time.sleep(30)   # check every 30s while idle
        except KeyboardInterrupt:
            print("\n[agent] shutting down")
            if engine.active:
                engine.active.close()
                _close_and_save(conn, engine.active)
            break
        except Exception:
            traceback.print_exc()
            time.sleep(config.CAPTURE_INTERVAL_SECONDS)


def _cycle(conn, engine: EpisodeEngine) -> None:
    now = time.time()
    obs = observer.observe()

    # Filter out system/agent observations before they reach the Episode Engine
    if obs is not None and not observer.is_user_work(obs):
        obs = None

    if obs is None:
        # No screen change (or filtered) — update activity timestamp, check inactivity
        engine.ingest_metadata_activity_only()
        closed = engine.check_inactivity(now)
        if closed:
            _close_and_save(conn, closed)
        return

    if obs.screenshot_path and config.ANTHROPIC_API_KEY:
        # Vision path: Claude analyzes screenshot and drives all Episode decisions
        ctx = engine.get_context()
        evidence = vision.analyze(obs, ctx)
        result = engine.ingest_vision(evidence, obs)
    else:
        # Metadata path: track context only, never open/close episodes
        engine.ingest_metadata(obs)
        result = None

    if result and result.closed_episode:
        _close_and_save(conn, result.closed_episode)

    # Also check inactivity in case of long metadata-only stretches
    closed = engine.check_inactivity(now)
    if closed:
        _close_and_save(conn, closed)


def _close_and_save(conn, episode: Episode) -> None:
    """Finalize a closed episode, discard if too short, otherwise persist and sync."""
    if episode is None:
        return
    finalizer.finalize(episode)

    if episode.duration_minutes < config.MIN_EPISODE_DURATION_MINUTES:
        print(
            f"[agent] discarded '{episode.case_name}' "
            f"({episode.duration_minutes:.1f}min — below minimum)"
        )
        return

    database.save_episode(conn, episode)
    sync.enqueue_episode(episode.to_dict())
    print(
        f"[agent] saved '{episode.case_name}' "
        f"({episode.duration_minutes:.1f}min, {len(episode.key_observations)} observations)"
    )


if __name__ == "__main__":
    main()
