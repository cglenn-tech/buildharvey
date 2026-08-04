"""
BuildHarvey Desktop Agent.

Run:  python main.py
      (or launched automatically by app.py after credential and permissions are set up)

Loop:
  1. Check if a work session is active (user clicked Start Task).
  2. Each cycle: apply authoritative context from task_context (if set).
  3. Capture screen → extract context → build Observation.
  4. If screenshot available: POST to /api/agent/vision for Claude analysis.
     Engine decides: continue current episode, open new, or suggest switch.
  5. If no screenshot or server returns None: update metadata context only.
  6. On episode close: finalize → persist to SQLite → enqueue server sync.
  7. Handle pending user actions: confirm/reject switch, force stop.

Session gate:
  - Recording begins when the user clicks Start Task in the desktop app.
  - Browser controls (via Realtime) are secondary and optional.
  - The desktop app can Start/Stop recording without a browser being open.
  - A browser refresh or closure does NOT stop recording.
  - Active episode is finalized on Stop.

Startup:
  - Mark locally invalid episodes (not deleted — just flagged).
  - Enqueue server cleanup for those IDs.

Degraded mode (no device token):
  - Vision analysis returns None; no Episodes opened.
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
import realtime_client
import sync
import task_context as tc
import vision
from episode import Episode
from episode_engine import EpisodeEngine


def main(
    state_callback: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> None:
    print("[agent] BuildHarvey starting")
    print(f"[agent] db {config.DB_PATH}")

    realtime_client.start()

    conn = database.connect()

    # Mark known garbage and propagate to server
    invalid_ids = database.mark_invalid_episodes(conn)
    if invalid_ids:
        sync.enqueue_cleanup(invalid_ids)

    engine = EpisodeEngine()
    sync.start()

    _ws_state = 'idle'        # tracks last state broadcast to realtime_client
    _last_paused = False      # tracks last known pause state for state_callback
    _last_suggestion = ""     # tracks last known switch suggestion
    _in_daily_review = False  # suppress 'idle' callback while showing daily review

    while True:
        if stop_event is not None and stop_event.is_set():
            print("[agent] stop_event set — shutting down")
            if engine.active:
                engine.active.close()
                _close_and_save(conn, engine.active)
            break
        try:
            if realtime_client.is_recording_active():
                if _ws_state != 'recording':
                    realtime_client.set_status('recording')
                    _ws_state = 'recording'

                # Apply authoritative context from UI each cycle
                ctx = tc.get_context()
                if ctx.is_set:
                    engine.set_authoritative_context(
                        ctx.case_name,
                        ctx.issue_worked_on or None,
                        ctx.work_type,
                    )

                # Handle pending user actions before running the capture cycle
                if tc.pop_force_stop():
                    closed = engine.force_close_active()
                    if closed:
                        _close_and_save(conn, closed)
                    _in_daily_review = True
                    if state_callback:
                        state_callback('daily_review')
                    realtime_client.broadcast_daily_review()
                    realtime_client.stop_local()
                    _ws_state = 'idle'
                    _last_paused = False
                    _last_suggestion = ""
                    time.sleep(30)
                    continue

                confirmed_name = tc.pop_confirm_switch()
                if confirmed_name is not None:
                    result = engine.confirm_switch(confirmed_name)
                    if result and result.closed_episode:
                        _close_and_save(conn, result.closed_episode)
                    _last_suggestion = ""

                if tc.pop_reject_switch():
                    engine.reject_switch()
                    _last_suggestion = ""

                try:
                    _cycle(conn, engine)
                except Exception:
                    traceback.print_exc()
                    try:
                        observer.reset()
                    except Exception:
                        pass

                # Update latest activity from most recent evidence
                if engine.active and engine.active._evidence:
                    last_ev = engine.active._evidence[-1]
                    tc.set_latest_activity(last_ev.activity_description or "")

                # Detect pause state change
                current_paused = tc.is_timing_paused()
                if current_paused != _last_paused:
                    _last_paused = current_paused
                    if state_callback:
                        state_callback('paused' if current_paused else 'recording')

                # Detect switch suggestion change
                current_suggestion = tc.get_switch_suggestion()
                if current_suggestion != _last_suggestion:
                    _last_suggestion = current_suggestion
                    if current_suggestion and state_callback:
                        state_callback(f'switch_suggestion:{current_suggestion}')

                if state_callback and not current_paused and not current_suggestion:
                    state_callback('recording' if engine.active else 'waiting')

                time.sleep(config.CAPTURE_INTERVAL_SECONDS)
            else:
                # No active work session — finalize and idle
                if engine.active:
                    engine.active.close()
                    _close_and_save(conn, engine.active)
                    engine.active = None
                if _ws_state != 'idle':
                    realtime_client.set_status('idle')
                    _ws_state = 'idle'
                _last_paused = False
                _last_suggestion = ""
                # Suppress 'idle' callback if we just triggered daily_review
                if not _in_daily_review and state_callback:
                    state_callback('idle')
                _in_daily_review = False
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

    if obs.screenshot_path:
        # Vision path: server analyzes screenshot and drives all Episode decisions
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
