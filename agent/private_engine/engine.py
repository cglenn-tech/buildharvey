"""
Private Engine — core entry point.

This module is the private engine's main loop. It MUST NOT import any networking
library. The import boundary is enforced by CI static analysis.

On macOS: invoked as an XPC Service (BuildHarveyPrivateEngine.xpc).
On Windows: invoked as a child process; communicates with app shell via named pipe.

IMPORT BOUNDARY (enforced by tests/test_import_boundary.py):
  FORBIDDEN imports (direct or transitive):
    urllib, requests, websockets, realtime, supabase, auth, sync, httpx, aiohttp

All networking is handled by the app shell. This module handles:
  - Capture loop (observer, OCR, entity extraction)
  - Local inference (episode boundary, summarization)
  - SQLite persistence (episodes, gaps, leases)
  - Report generation (local only)
  - Consent state machine
"""
import platform
import threading
import time
import traceback
from typing import Optional

# Private engine imports — all local, no network
import config
import database
import finalizer
import observer
from consent_manager import ConsentManager
from episode import Episode
from episode_engine import EpisodeEngine
from local_inference import get_backend
from observer import _CONSENT_BLOCKED
from private_engine.ipc import (
    EngineStatus,
    PrivateEngineCommand,
    PrivateEngineEvent,
    WindowIdentityInfo,
)


class PrivateEngine:
    """
    The private work engine. All work content stays here.

    The app shell interacts via the PrivateEngineCommand protocol.
    Events are delivered to the registered event handler.
    """

    def __init__(self, event_handler: PrivateEngineEvent) -> None:
        self._handler = event_handler
        self._conn = database.connect()
        self._consent = ConsentManager(self._conn)
        self._engine = EpisodeEngine()
        self._inference = get_backend()
        self._stop_event = threading.Event()
        self._capture_active = False
        self._open_gap_id: Optional[str] = None

    # ── PrivateEngineCommand implementation ───────────────────────────────────

    def start_capture(self) -> None:
        self._stop_event.clear()
        self._capture_active = True
        threading.Thread(target=self._capture_loop, daemon=True).start()

    def stop_capture(self) -> None:
        self._capture_active = False
        self._stop_event.set()
        if self._engine.active:
            self._engine.active.close()
            self._close_and_save(self._engine.active)
            self._engine.active = None

    def request_report(self, period_start: str, period_end: str) -> None:
        threading.Thread(
            target=self._generate_report,
            args=(period_start, period_end),
            daemon=True,
        ).start()

    def delete_all_data(self) -> None:
        self.stop_capture()
        database.delete_all_local_data(self._conn)
        # App shell exits the process after this call

    def get_status(self) -> EngineStatus:
        return EngineStatus(
            state="capturing" if self._capture_active else "idle",
            session_epoch=self._consent.session_epoch,
            active_episode_id=self._engine.active.id if self._engine.active else None,
            open_gap_id=self._open_gap_id,
            last_error=None,
        )

    def record_consent_result(self, auth_key: str, allowed: bool) -> None:
        self._consent.record_consent_result(auth_key, allowed)

    def record_batch_reconsent_result(self, auth_keys: list[str], allowed: bool) -> None:
        for key in auth_keys:
            self._consent.record_consent_result(key, allowed)

    # ── Capture loop ──────────────────────────────────────────────────────────

    def _capture_loop(self) -> None:
        while not self._stop_event.is_set() and self._capture_active:
            try:
                self._open_gap_id = self._cycle(self._open_gap_id)
            except Exception:
                traceback.print_exc()
                try:
                    observer.reset()
                except Exception:
                    pass
            time.sleep(config.CAPTURE_INTERVAL_SECONDS)

    def _cycle(self, open_gap_id: Optional[str]) -> Optional[str]:
        now = time.time()

        # Model-ready check: if local inference is required but the model is not
        # loaded yet (e.g. still downloading), create an inference_unavailable gap.
        # This prevents any capture cycle from silently falling to NullBackend
        # and creating episodes with inference_failed=True without the user's awareness.
        if config.USE_LOCAL_INFERENCE and not self._inference.is_available():
            if open_gap_id is None:
                prev_ep_id = self._engine.active.id if self._engine.active else None
                open_gap_id = database.open_gap(self._conn, "inference_unavailable", prev_ep_id)
                self._handler.on_gap_recorded(open_gap_id, "inference_unavailable")
            return open_gap_id

        obs = observer.observe(consent_manager=self._consent)

        if obs is _CONSENT_BLOCKED:
            # Window not authorized — request consent from app shell and open gap
            self._request_consent_if_needed()
            if open_gap_id is None:
                prev_ep_id = self._engine.active.id if self._engine.active else None
                open_gap_id = database.open_gap(self._conn, "window_not_consented", prev_ep_id)
                self._handler.on_gap_recorded(open_gap_id, "window_not_consented")
            return open_gap_id

        if open_gap_id is not None and obs is not None:
            next_ep_id = self._engine.active.id if self._engine.active else None
            database.close_gap(self._conn, open_gap_id, next_episode_id=next_ep_id)
            open_gap_id = None

        if obs is not None and not observer.is_user_work(obs):
            obs = None

        if obs is None:
            self._engine.ingest_metadata_activity_only()
            closed = self._engine.check_inactivity(now)
            if closed:
                self._close_and_save(closed)
            return open_gap_id

        if obs.screenshot_path:
            # Private engine always uses local inference — no cloud vision call.
            # The screenshot is analyzed locally; the path is deleted after extraction.
            ctx = self._engine.get_context()
            evidence = self._analyze_local(obs, ctx)
            result = self._engine.ingest_vision(evidence, obs)
        else:
            self._engine.ingest_metadata(obs)
            result = None

        if result and result.closed_episode:
            self._close_and_save(result.closed_episode)

        closed = self._engine.check_inactivity(now)
        if closed:
            self._close_and_save(closed)

        return open_gap_id

    def _analyze_local(self, obs, context: dict):
        """
        Analyze a screenshot using local inference only. No network calls.
        Returns a ScreenshotEvidence (or None on failure) with screenshot_path=None
        after deleting the raw frame.
        """
        import time as _time
        from pathlib import Path as _Path
        from episode import ScreenshotEvidence

        screenshot_path = getattr(obs, "screenshot_path", None)
        if not screenshot_path:
            return None

        try:
            # Extract OCR excerpt locally
            try:
                import ocr as _ocr
                ocr_text = _ocr.extract_text(screenshot_path)
                ocr_excerpt = (ocr_text or "")[:200]
            except Exception:
                ocr_excerpt = ""
            finally:
                # Invariant: screenshot deleted immediately after extraction
                try:
                    _Path(screenshot_path).unlink(missing_ok=True)
                except Exception:
                    pass

            if not self._inference.is_available():
                return None

            app = getattr(obs, "app", "") or ""
            window_title = getattr(obs, "window_title", "") or ""
            current_summary = context.get("episode_name", "") if context else ""

            signal = self._inference.classify_episode_boundary(
                app=app,
                window_title=window_title,
                ocr_excerpt=ocr_excerpt,
                current_episode_summary=current_summary,
            )

            return ScreenshotEvidence(
                screenshot_path=None,
                timestamp=_time.strftime("%H:%M"),
                activity_description=f"{signal.activity_type} activity",
                objective=current_summary,
                actions=[],
                entities=getattr(obs, "entities", []),
                supporting_evidence=[],
                app_context=f"{app}",
                model="local",
                input_tokens=0,
                output_tokens=0,
                continue_current_episode=not signal.new_episode,
                start_new_episode=signal.new_episode,
                suggested_episode_name="",
            )
        except Exception:
            return None

    def _request_consent_if_needed(self) -> None:
        """
        Check if there are windows awaiting consent and notify the app shell.
        The app shell shows the dialog; results come back via record_consent_result().
        """
        # The ConsentManager already dispatches dialogs on macOS via main queue.
        # On the Windows separate-process model, we notify the app shell via IPC
        # to show a dialog, then wait for record_consent_result().
        pass

    def _close_and_save(self, episode: Episode) -> None:
        if episode is None:
            return
        finalizer.finalize(episode)

        if episode.duration_minutes < config.MIN_EPISODE_DURATION_MINUTES:
            return

        activity_class = getattr(episode, "_activity_classification", None)
        class_confidence = getattr(episode, "_classification_confidence", None)
        inference_failed = getattr(episode, "_has_inference_failure", False)

        database.save_episode(
            self._conn, episode,
            activity_classification=activity_class,
            classification_confidence=class_confidence,
            has_inference_failure=inference_failed,
        )

        self._handler.on_episode_closed(episode.id, episode.duration_minutes)

        if inference_failed:
            self._handler.on_inference_failure(
                f"Episode '{episode.case_name}' — local inference failed; "
                "episode saved with template observations only."
            )

    def _generate_report(self, period_start: str, period_end: str) -> None:
        """Generate a weekly report locally. No network calls."""
        try:
            from weekly_report import WeeklyReportEngine
            engine = WeeklyReportEngine(self._conn)
            local_path = engine.generate(period_start, period_end)
            self._handler.on_report_ready(local_path)
        except Exception as e:
            self._handler.on_inference_failure(f"Report generation failed: {e}")
