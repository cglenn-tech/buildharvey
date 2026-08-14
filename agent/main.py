"""
BuildHarvey Desktop Agent — headless background daemon.

Run:  python main.py
      (or launched automatically by app.py after credential and permissions are set up)

Loop:
  1. Check if a work session is active (user clicked Start on buildharvey.com).
  2. Each cycle: capture screen → extract context → build Observation.
  3. If screenshot available: POST to /api/agent/vision for Claude analysis
     (or invoke LocalInferenceBackend when USE_LOCAL_INFERENCE=true).
     Engine passively groups into episodes using 2-signal hysteresis.
  4. If no screenshot or server returns None: update metadata context only.
  5. On episode close: finalize → persist to SQLite → enqueue server sync.
  6. On session end: broadcast daily_review so the web dashboard shows the modal.

Session gate:
  - Recording begins when the user clicks Start on buildharvey.com (Realtime).
  - A browser refresh or closure does NOT stop recording.
  - Active episode is finalized on Stop.

Phase 1 (ENABLE_CAPTURE_LEASES=true):
  - Per-window consent required before any observation is recorded.
  - Unauthorized windows generate ObservationGaps.
  - Security boundary crossings (lock/logout/restart) invalidate all leases.

Startup:
  - Purge stale temp frames (crash safety: delete frames >1h old).
  - Mark locally invalid episodes (not deleted — just flagged).
  - Enqueue server cleanup for those IDs.
  - Increment session epoch (detects crash recovery).

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
import vision
from episode import Episode
from episode_engine import EpisodeEngine
from observer import _CONSENT_BLOCKED


def main(
    state_callback: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> None:
    print("[agent] BuildHarvey starting")
    print(f"[agent] db {config.DB_PATH}")

    # Phase 2: purge stale temp frames on startup (crash safety net)
    try:
        database.purge_stale_temp_frames()
    except Exception:
        pass

    # Phase 3+: first-run model download when local inference is required
    if config.USE_LOCAL_INFERENCE:
        from local_inference import ModelManager
        mm = ModelManager()
        if mm.needs_download():
            print("[agent] local AI models required — downloading in background...")
            mm.download_all_in_background(
                progress_cb=lambda name, dl, total: print(
                    f"[agent] model {name}: {dl // (1024*1024)}MB"
                    + (f"/{total // (1024*1024)}MB" if total else "")
                )
            )

    realtime_client.start()

    conn = database.connect()

    # Crash safety: check for dirty shutdown BEFORE marking current startup dirty.
    # Order matters: read the previous value first, then overwrite with dirty.
    _prev_crashed = database.check_dirty_shutdown(conn)
    database.mark_dirty_shutdown(conn)

    # Mark known garbage and propagate to server
    invalid_ids = database.mark_invalid_episodes(conn)
    if invalid_ids:
        sync.enqueue_cleanup(invalid_ids)

    # Phase 1: initialize ConsentManager (noop when ENABLE_CAPTURE_LEASES=false)
    consent_manager = None
    crashed = _prev_crashed
    if config.ENABLE_CAPTURE_LEASES:
        from consent_manager import ConsentManager
        consent_manager = ConsentManager(conn)
        print(f"[agent] capture leases enabled — session epoch {consent_manager.session_epoch}")

        # If previous session crashed, invalidate all leases so users are re-prompted
        if crashed:
            consent_manager.invalidate_all("app_crashed")

        # Show batch re-consent for any leases invalidated before this startup
        invalidated = consent_manager.get_invalidated_leases()
        if invalidated:
            consent_manager.begin_batch_reconsent(invalidated)

    engine = EpisodeEngine()
    sync.start()

    _ws_state = 'idle'                  # tracks last state broadcast to realtime_client
    _open_gap_id: Optional[str] = None  # current open ObservationGap (if any)

    while True:
        if stop_event is not None and stop_event.is_set():
            print("[agent] stop_event set — shutting down")
            if engine.active:
                engine.active.close()
                _close_and_save(conn, engine.active)
            if _open_gap_id:
                database.close_gap(conn, _open_gap_id)
            database.mark_clean_shutdown(conn)
            break
        try:
            if realtime_client.is_recording_active():
                if _ws_state != 'recording':
                    realtime_client.set_status('recording')
                    _ws_state = 'recording'
                try:
                    _open_gap_id = _cycle(conn, engine, consent_manager, _open_gap_id)
                except Exception:
                    traceback.print_exc()
                    try:
                        observer.reset()
                    except Exception:
                        pass
                if state_callback:
                    state_callback('recording' if engine.active else 'waiting')
                time.sleep(config.CAPTURE_INTERVAL_SECONDS)
            else:
                # No active work session — finalize and idle
                if engine.active:
                    engine.active.close()
                    _close_and_save(conn, engine.active)
                    engine.active = None
                    realtime_client.broadcast_daily_review()   # notify web to show review modal
                if _open_gap_id:
                    database.close_gap(conn, _open_gap_id)
                    _open_gap_id = None
                if _ws_state != 'idle':
                    realtime_client.set_status('idle')
                    _ws_state = 'idle'
                if state_callback:
                    state_callback('idle')
                time.sleep(30)   # check every 30s while idle
        except KeyboardInterrupt:
            print("\n[agent] shutting down")
            if engine.active:
                engine.active.close()
                _close_and_save(conn, engine.active)
            if _open_gap_id:
                database.close_gap(conn, _open_gap_id)
            database.mark_clean_shutdown(conn)
            break
        except Exception:
            traceback.print_exc()
            time.sleep(config.CAPTURE_INTERVAL_SECONDS)


def _cycle(
    conn,
    engine: EpisodeEngine,
    consent_manager,
    open_gap_id: Optional[str],
) -> Optional[str]:
    """
    Run one capture cycle. Returns the current open_gap_id (possibly new or
    None if a previously open gap was just closed).
    """
    now = time.time()
    obs = observer.observe(consent_manager=consent_manager)

    # ── Consent-blocked sentinel (Phase 1) ────────────────────────────────────
    if obs is _CONSENT_BLOCKED:
        # Window not authorized — open or extend an ObservationGap
        if open_gap_id is None:
            prev_ep_id = engine.active.id if engine.active else None
            open_gap_id = database.open_gap(conn, "window_not_consented", prev_ep_id)
        return open_gap_id

    # ── Close any open gap when capture resumes ───────────────────────────────
    if open_gap_id is not None and obs is not None:
        next_ep_id = engine.active.id if engine.active else None
        database.close_gap(conn, open_gap_id, next_episode_id=next_ep_id)
        open_gap_id = None

    # Filter out system/agent observations before they reach the Episode Engine
    if obs is not None and not observer.is_user_work(obs):
        obs = None

    if obs is None:
        # No screen change (or filtered) — update activity timestamp, check inactivity
        engine.ingest_metadata_activity_only()
        closed = engine.check_inactivity(now)
        if closed:
            _close_and_save(conn, closed)
        return open_gap_id

    if obs.screenshot_path:
        # Deterministic boundary check — avoids model call when signal is clear
        deterministic = engine.check_deterministic_boundary(obs, engine.active)
        if deterministic is True:
            # Definitive new episode — close current and let vision open new one
            ctx = engine.get_context()
            evidence = vision.analyze(obs, ctx)
            result = engine.ingest_vision(evidence, obs)
        elif deterministic is False and engine.active:
            # Definitive continue — no model call needed; update metadata only
            engine.ingest_metadata(obs)
            result = None
        else:
            # Ambiguous — invoke local model for classification
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

    return open_gap_id


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

    # Read classification metadata set by finalizer
    activity_class = getattr(episode, "_activity_classification", None)
    class_confidence = getattr(episode, "_classification_confidence", None)
    inference_failed = getattr(episode, "_has_inference_failure", False)

    database.save_episode(
        conn, episode,
        activity_classification=activity_class,
        classification_confidence=class_confidence,
        has_inference_failure=inference_failed,
    )
    sync.enqueue_episode(episode.to_dict())
    print(
        f"[agent] saved '{episode.case_name}' "
        f"({episode.duration_minutes:.1f}min, {len(episode.key_observations)} observations)"
    )


if __name__ == "__main__":
    main()
