"""
BuildHarvey Desktop Agent.

Run:  python main.py

Loop:
  1. Capture screen → extract context → build Observation (image discarded).
  2. Engine decides: continue current episode or close and open a new one.
  3. On close: finalize → persist to SQLite → enqueue Supabase sync.
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
from episode import Episode
from episode_engine import EpisodeEngine


def main() -> None:
    print("[agent] BuildHarvey starting")
    print(f"[agent] db {config.DB_PATH}")

    conn = database.connect()
    engine = EpisodeEngine()
    sync.start()

    while True:
        try:
            _cycle(conn, engine)
        except KeyboardInterrupt:
            print("\n[agent] shutting down")
            _close_and_save(conn, engine.active)
            break
        except Exception:
            traceback.print_exc()
        time.sleep(config.CAPTURE_INTERVAL_SECONDS)


def _cycle(conn, engine: EpisodeEngine) -> None:
    now = time.time()
    obs = observer.observe()

    if obs is None:
        closed = engine.check_inactivity(now)
        if closed:
            _close_and_save(conn, closed)
        return

    print(f"[agent] {obs.app!r} | {obs.window_title!r} | entities={obs.entities}")

    result = engine.ingest(obs, now)
    result.active_episode.add_observation(obs)

    if result.closed_episode:
        _close_and_save(conn, result.closed_episode)


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
