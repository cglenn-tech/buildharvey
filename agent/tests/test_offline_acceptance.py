"""
Offline Acceptance Test — Phase 12.

Verifies that no network calls are made during a complete
capture → episode → report sequence when PRIVATE_MODE=true.

Mocks urllib.request.urlopen and socket.create_connection at module level
and asserts zero calls to either throughout the full pipeline.
"""
import importlib
import os
import sqlite3
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Force Private Mode environment variables ───────────────────────────────────
# Set env vars before any agent module is imported, and reload config so that
# cached imports in prior tests don't carry stale values.
_PRIVATE_MODE_ENV = {
    "BUILDHARVEY_PRIVATE_MODE": "true",
    "ENABLE_CAPTURE_LEASES": "false",   # simplify: skip consent UI in test
    "USE_LOCAL_INFERENCE": "false",     # NullBackend — no model needed
    "BUILDHARVEY_BASE_URL": "http://should-never-be-called.invalid",
}
os.environ.update(_PRIVATE_MODE_ENV)

# Reload config (and any module that cached the old PRIVATE_MODE value)
# so the rest of this module sees fresh values from the env.
if "config" in sys.modules:
    importlib.reload(sys.modules["config"])
if "sync" in sys.modules:
    importlib.reload(sys.modules["sync"])
if "finalizer" in sys.modules:
    importlib.reload(sys.modules["finalizer"])
if "vision" in sys.modules:
    importlib.reload(sys.modules["vision"])


def _enforce_private_mode() -> None:
    """
    Ensure BUILDHARVEY_PRIVATE_MODE=true is in the environment and reload all
    modules that cache privacy config. Called in setUp so that test collection
    order cannot pollute the privacy state.
    """
    import importlib as _il
    import sys as _sys
    # Explicitly set env vars before any reload
    os.environ.update(_PRIVATE_MODE_ENV)
    for mod_name in ("config", "sync", "finalizer", "vision"):
        if mod_name in _sys.modules:
            _il.reload(_sys.modules[mod_name])


class TestOfflineAcceptance(unittest.TestCase):
    """
    End-to-end offline acceptance test.

    Patches all network sockets at the lowest level so even indirect callers
    (through urllib, requests, websockets, etc.) cannot reach the network.
    """

    def setUp(self):
        """Enforce private mode and set up temp directories for the test."""
        # Re-enforce private mode env vars and reload cached modules at the
        # start of every test to survive cross-test module cache pollution
        # (e.g. test_realtime_optionality installs a config stub without PRIVATE_MODE).
        _enforce_private_mode()
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmpdir.name) / "test.db"

    def _make_network_blocker(self, name: str):
        """Return a mock that raises if called, recording the attempt."""
        def _blocked(*args, **kwargs):
            self.fail(
                f"Network call attempted via {name} with args={args!r}, kwargs={kwargs!r}. "
                f"This violates the offline-only invariant in Private Mode."
            )
        return MagicMock(side_effect=_blocked)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def test_no_network_calls_in_private_mode(self):
        """
        Assert zero network calls during a complete private-mode session:
        startup, episode finalization, report generation, and data deletion.
        """
        urlopen_mock = self._make_network_blocker("urllib.request.urlopen")
        socket_mock = self._make_network_blocker("socket.create_connection")

        with (
            patch("urllib.request.urlopen", urlopen_mock),
            patch("socket.create_connection", socket_mock),
        ):
            self._run_full_pipeline()

    def _run_full_pipeline(self):
        """
        Run through the full agent pipeline in-process:
          1. Connect to database (encrypted path skipped via env flag)
          2. Check/set dirty shutdown
          3. Finalize a synthetic episode
          4. Enqueue episode (sync must be a no-op in Private Mode)
          5. Generate a weekly report
          6. Delete all local data
        """
        # ── Patch config to use temp paths ──────────────────────────────────
        import config as _config
        # setUp() already reloaded config with PRIVATE_MODE=true
        original_db_path = _config.DB_PATH
        original_screenshots_dir = _config.SCREENSHOTS_DIR
        original_temp_frame = _config.TEMP_FRAME_PATH
        original_prev_frame = _config.PREV_FRAME_PATH
        original_base_dir = _config.BASE_DIR

        tmpdir = Path(self._tmpdir.name)
        _config.DB_PATH = tmpdir / "test.db"
        _config.SCREENSHOTS_DIR = tmpdir / "screenshots"
        _config.TEMP_FRAME_PATH = tmpdir / "_current.png"
        _config.PREV_FRAME_PATH = tmpdir / "_prev.png"
        _config.BASE_DIR = tmpdir
        _config.SCREENSHOTS_DIR.mkdir(exist_ok=True)

        try:
            # ── Step 1: database connect (plaintext — apsw not required in test) ──
            import database
            # Override PRIVATE_MODE check to use plaintext in test (apsw not installed in CI)
            conn = sqlite3.connect(str(_config.DB_PATH))
            conn.execute("PRAGMA journal_mode=WAL")
            database._migrate(conn)

            # ── Step 2: crash safety ──────────────────────────────────────────
            database.mark_dirty_shutdown(conn)
            self.assertFalse(database.check_dirty_shutdown(conn) is None)
            database.mark_clean_shutdown(conn)
            self.assertFalse(database.check_dirty_shutdown(conn))

            # ── Step 3: finalize a synthetic episode ─────────────────────────
            from episode import Episode, new_episode
            ep = new_episode("Test Matter v. Defendant", issue_worked_on="Motion to Dismiss")
            time.sleep(0.01)
            ep.close()

            import finalizer
            finalizer.finalize(ep)

            if ep.duration_minutes >= _config.MIN_EPISODE_DURATION_MINUTES:
                database.save_episode(conn, ep)

            # ── Step 4: sync enqueue (must be no-op in Private Mode) ─────────
            import sync
            # sync.start() must not launch a worker in Private Mode
            sync.start()
            # If sync.start() did not raise, check nothing was queued to network
            sync.enqueue_episode({"id": "test-id", "case_name": "Test", "key_observations": []})
            # Give the (hypothetical, should-not-exist) worker a moment to fire
            time.sleep(0.05)

            # ── Step 5: weekly report generation ─────────────────────────────
            from weekly_report import WeeklyReportEngine
            engine = WeeklyReportEngine(conn)
            # Should not raise NotImplementedError anymore
            report_path = engine.generate("2026-08-01T00:00:00Z", "2026-08-08T23:59:59Z")
            self.assertIsInstance(report_path, str)
            self.assertTrue(Path(report_path).exists())

            # ── Step 6: delete all local data ─────────────────────────────────
            # Patch _delete_keychain_key to no-op (no actual keychain in test)
            with patch.object(database, "_delete_keychain_key", return_value=None):
                database.delete_all_local_data(conn)

        finally:
            # Restore config paths
            _config.DB_PATH = original_db_path
            _config.SCREENSHOTS_DIR = original_screenshots_dir
            _config.TEMP_FRAME_PATH = original_temp_frame
            _config.PREV_FRAME_PATH = original_prev_frame
            _config.BASE_DIR = original_base_dir

    def test_sync_start_is_noop_in_private_mode(self):
        """sync.start() must not launch a worker thread when PRIVATE_MODE=true."""
        import config as _config
        self.assertTrue(_config.PRIVATE_MODE, "PRIVATE_MODE must be true for this test")

        import sync
        threads_before = {t.name for t in threading.enumerate()}
        sync.start()
        time.sleep(0.05)
        threads_after = {t.name for t in threading.enumerate()}
        self.assertNotIn("sync-worker", threads_after - threads_before)

    def test_finalizer_does_not_call_server_in_private_mode(self):
        """finalizer._generate_observations() must not call _server_observations in Private Mode."""
        import config as _config
        self.assertTrue(_config.PRIVATE_MODE)

        urlopen_mock = self._make_network_blocker("urllib.request.urlopen")
        with patch("urllib.request.urlopen", urlopen_mock):
            from episode import new_episode
            import finalizer
            ep = new_episode("Test Episode", issue_worked_on=None)
            ep.close()
            finalizer.finalize(ep)
            # If we get here without the mock firing, the invariant holds

    def test_vision_does_not_call_server_in_private_mode(self):
        """vision.analyze() must return None without network calls in Private Mode."""
        import config as _config
        self.assertTrue(_config.PRIVATE_MODE)
        # USE_LOCAL_INFERENCE=false → NullBackend → _analyze_local returns None
        # PRIVATE_MODE=true → cloud path blocked
        urlopen_mock = self._make_network_blocker("urllib.request.urlopen")
        with patch("urllib.request.urlopen", urlopen_mock):
            import vision
            from observer import Observation

            class _FakeObs:
                screenshot_path = None
                app = "TestApp"
                window_title = "Test Window"
                browser_url = ""
                entities = []

            result = vision.analyze(_FakeObs(), {})
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
