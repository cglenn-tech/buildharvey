"""
BuildHarvey Desktop Agent.

Run:  python main.py
      (or launched automatically by app.py after credential and permissions are set up)

Loop:
  1. Capture screen → extract context → build Observation.
  2. If screenshot available and API key configured: analyze with Claude Vision.
     Engine decides: continue current episode, open new, or transition.
  3. If no screenshot or no API key: update metadata context only.
  4. On episode close: finalize → persist to SQLite → enqueue server sync.

Startup:
  - Mark locally invalid episodes (not deleted — just flagged).
  - Enqueue server cleanup for those IDs.

Degraded mode (no API key):
  - Vision analysis skipped; no Episodes opened.
  - Metadata tracked in memory only.
  - System keeps running; no garbage Episodes created.
"""
import time
import traceback

from dotenv import load_dotenv
load_dotenv()

import config
import database
import finalizer
import observer
import sync
import vision
from episode import Episode
from episode_engine import EpisodeEngine


def main() -> None:
    print("[agent] BuildHarvey starting")
    print(f"[agent] db {config.DB_PATH}")
    if not config.ANTHROPIC_API_KEY:
        print("[agent] WARNING: ANTHROPIC_API_KEY not set — running in degraded mode (no episodes)")

    conn = database.connect()

    # Mark known garbage and propagate to server
    invalid_ids = database.mark_invalid_episodes(conn)
    if invalid_ids:
        sync.enqueue_cleanup(invalid_ids)

    engine = EpisodeEngine()
    sync.start()

    while True:
        try:
            _cycle(conn, engine)
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

    if obs is None:
        # No screen change — update activity timestamp, check inactivity
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
