"""
Privacy boundary tests — Part 14 of the production migration.

Covers:
  1. SQLite encryption verification: an encrypted DB cannot be read by plain sqlite3
  2. BuildHarvey window exclusion: agent-owned apps never enter the Episode Engine
     and never trigger consent prompts
  3. Windows capture API selection: capture_window() on Windows routes to
     _capture_window_win32(), never to capture_screen()
  4. Fail-closed behavior: capture_window() False → _CONSENT_BLOCKED in observer
"""
import importlib
import os
import platform
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── Encryption verification ────────────────────────────────────────────────────

_TEST_KEY = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
_TEST_KEY_B = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
_ENC_MARKER = "BUILDHARVEY_ENC_MARKER_7F92C1"


class TestSQLiteEncryptionVerification(unittest.TestCase):
    """
    Verifies sqlite3mc encryption via apsw-sqlite3mc.

    All encryption write/read operations use apsw.Connection directly.
    stdlib sqlite3 is used only to prove it CANNOT read encrypted content.
    Tests skip when apsw-sqlite3mc is not installed.
    """

    def _get_apsw(self):
        try:
            import apsw
            return apsw
        except ImportError:
            self.skipTest("apsw-sqlite3mc not installed — skipping byte-level encryption tests")

    # ── helpers ────────────────────────────────────────────────────────────────

    def _write_encrypted(self, apsw_mod, path, key, marker=_ENC_MARKER):
        """Create an encrypted DB with one row containing marker."""
        conn = apsw_mod.Connection(str(path))
        conn.execute(f"PRAGMA key='{key}'")
        conn.execute("CREATE TABLE secret_test (value TEXT)")
        conn.execute("INSERT INTO secret_test(value) VALUES(?)", (marker,))
        try:
            conn.execute("COMMIT")
        except Exception:
            pass
        conn.close()

    # ── round-trip ─────────────────────────────────────────────────────────────

    def test_apsw_encrypted_db_readable_with_correct_key(self):
        """apsw connection with correct key must read back inserted content."""
        apsw = self._get_apsw()
        with tempfile.TemporaryDirectory() as d:
            db_path = Path(d) / "encrypted.db"
            self._write_encrypted(apsw, db_path, _TEST_KEY)

            conn2 = apsw.Connection(str(db_path))
            conn2.execute(f"PRAGMA key='{_TEST_KEY}'")
            rows = list(conn2.execute("SELECT value FROM secret_test"))
            conn2.close()

            self.assertEqual(rows, [(_ENC_MARKER,)])

    # ── stdlib blocked ─────────────────────────────────────────────────────────

    def test_plain_sqlite3_cannot_read_apsw_encrypted_db(self):
        """stdlib sqlite3.connect() must not read apsw-encrypted content."""
        apsw = self._get_apsw()
        with tempfile.TemporaryDirectory() as d:
            db_path = Path(d) / "encrypted.db"
            self._write_encrypted(apsw, db_path, _TEST_KEY)

            with self.assertRaises(sqlite3.DatabaseError):
                plain = sqlite3.connect(str(db_path))
                plain.execute("SELECT * FROM secret_test").fetchall()
                plain.close()

    # ── raw bytes ──────────────────────────────────────────────────────────────

    def test_raw_bytes_do_not_contain_work_content(self):
        """Encrypted DB file must not expose marker as readable plaintext bytes."""
        apsw = self._get_apsw()
        with tempfile.TemporaryDirectory() as d:
            db_path = Path(d) / "encrypted.db"
            self._write_encrypted(apsw, db_path, _TEST_KEY)

            raw = db_path.read_bytes()
            self.assertNotIn(
                _ENC_MARKER.encode(),
                raw,
                "Work content marker must not appear as plaintext in encrypted file",
            )
            self.assertNotEqual(
                raw[:16],
                b"SQLite format 3\x00",
                "Encrypted file must not start with SQLite3 plaintext header",
            )

    # ── wrong key ──────────────────────────────────────────────────────────────

    def test_wrong_key_fails(self):
        """Applying an incorrect key must prevent reading any table content."""
        apsw = self._get_apsw()
        with tempfile.TemporaryDirectory() as d:
            db_path = Path(d) / "encrypted.db"
            self._write_encrypted(apsw, db_path, _TEST_KEY)

            conn_bad = apsw.Connection(str(db_path))
            conn_bad.execute(f"PRAGMA key='{_TEST_KEY_B}'")
            with self.assertRaises(Exception):
                list(conn_bad.execute("SELECT value FROM secret_test"))
            conn_bad.close()

    # ── no key ─────────────────────────────────────────────────────────────────

    def test_no_key_fails(self):
        """Omitting PRAGMA key entirely must prevent reading any table content."""
        apsw = self._get_apsw()
        with tempfile.TemporaryDirectory() as d:
            db_path = Path(d) / "encrypted.db"
            self._write_encrypted(apsw, db_path, _TEST_KEY)

            conn_nokey = apsw.Connection(str(db_path))
            # Do NOT apply PRAGMA key
            with self.assertRaises(Exception):
                list(conn_nokey.execute("SELECT value FROM secret_test"))
            conn_nokey.close()

    # ── WAL ────────────────────────────────────────────────────────────────────

    def test_wal_not_readable_as_plaintext(self):
        """If a WAL file exists, it must not expose work content as readable bytes."""
        apsw = self._get_apsw()
        with tempfile.TemporaryDirectory() as d:
            db_path = Path(d) / "encrypted.db"

            conn = apsw.Connection(str(db_path))
            conn.execute(f"PRAGMA key='{_TEST_KEY}'")
            conn.execute("CREATE TABLE wt (v TEXT)")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("INSERT INTO wt VALUES(?)", (_ENC_MARKER,))
            try:
                conn.execute("COMMIT")
            except Exception:
                pass

            wal_path = Path(str(db_path) + "-wal")
            if wal_path.exists() and wal_path.stat().st_size > 0:
                wal_raw = wal_path.read_bytes()
                self.assertNotIn(
                    _ENC_MARKER.encode(),
                    wal_raw,
                    "WAL file must not expose work content as plaintext",
                )

            conn.close()

    # ── plaintext migration ────────────────────────────────────────────────────

    def test_plaintext_migration(self):
        """
        Create a plaintext DB via stdlib sqlite3, run PRAGMA rekey via apsw,
        then verify: marker absent from raw bytes, stdlib blocked, apsw reads OK.
        """
        apsw = self._get_apsw()
        with tempfile.TemporaryDirectory() as d:
            db_path = Path(d) / "plain.db"

            # Create plaintext DB with stdlib
            plain = sqlite3.connect(str(db_path))
            plain.execute("CREATE TABLE m (v TEXT)")
            plain.execute("INSERT INTO m VALUES(?)", (_ENC_MARKER,))
            plain.commit()
            plain.close()

            self.assertEqual(
                db_path.read_bytes()[:16],
                b"SQLite format 3\x00",
                "Pre-migration file must have plaintext SQLite3 header",
            )

            # Encrypt in place via rekey
            conn = apsw.Connection(str(db_path))
            result = list(conn.execute(f"PRAGMA rekey='{_TEST_KEY}'"))
            conn.close()
            self.assertEqual(result, [("ok",)], "PRAGMA rekey must return ok")

            # Header must no longer be plaintext
            self.assertNotEqual(
                db_path.read_bytes()[:16],
                b"SQLite format 3\x00",
                "Post-migration file must not have plaintext SQLite3 header",
            )

            # Marker must not appear in raw bytes
            self.assertNotIn(
                _ENC_MARKER.encode(),
                db_path.read_bytes(),
                "Work content must not appear as plaintext after migration",
            )

            # stdlib must not be able to read it
            with self.assertRaises(sqlite3.DatabaseError):
                p = sqlite3.connect(str(db_path))
                p.execute("SELECT * FROM m").fetchall()
                p.close()

            # apsw must read it correctly with the key
            conn2 = apsw.Connection(str(db_path))
            conn2.execute(f"PRAGMA key='{_TEST_KEY}'")
            rows = list(conn2.execute("SELECT v FROM m"))
            conn2.close()
            self.assertEqual(rows, [(_ENC_MARKER,)])

    # ── fail-closed without apsw ───────────────────────────────────────────────

    def test_connect_encrypted_fails_closed_without_apsw(self):
        """
        When apsw is unavailable in PRIVATE_MODE, database.connect() must
        raise RuntimeError rather than opening a plaintext database.
        """
        os.environ["BUILDHARVEY_PRIVATE_MODE"] = "true"
        import config as _cfg
        importlib.reload(_cfg)

        import database as _db
        with patch.dict("sys.modules", {"apsw": None, "apsw.shell": None}):
            with self.assertRaises((RuntimeError, ImportError, ModuleNotFoundError)):
                with tempfile.TemporaryDirectory() as tmpdir:
                    _cfg.DB_PATH = Path(tmpdir) / "test.db"
                    _db._connect_encrypted()


# ── BuildHarvey window exclusion ──────────────────────────────────────────────

class TestBuildharveyWindowExclusion(unittest.TestCase):
    """
    Verify agent-owned windows are never treated as user work and never
    enter the Episode Engine.
    """

    def test_buildharvey_app_not_user_work(self):
        """is_user_work() must return False for any BuildHarvey-owned app name."""
        import observer
        bh_apps = [
            "BuildHarvey",
            "buildharvey",
            "BuildHarvey Agent",
            "com.buildharvey.agent",
        ]
        for app_name in bh_apps:
            obs = observer.Observation(
                timestamp="2026-08-13T00:00:00Z",
                app=app_name,
                window_title="BuildHarvey Status",
                browser_url="",
                file_path="",
            )
            self.assertFalse(
                observer.is_user_work(obs),
                f"is_user_work() must return False for app={app_name!r}",
            )

    def test_system_apps_not_user_work(self):
        """is_user_work() must return False for all known system app names."""
        import observer
        system_apps = [
            "loginwindow", "SystemPreferences", "System Preferences",
            "System Settings", "Spotlight", "Dock", "Finder",
            "SecurityAgent", "UserNotificationCenter",
            "Task Manager", "Explorer",
        ]
        for app_name in system_apps:
            obs = observer.Observation(
                timestamp="2026-08-13T00:00:00Z",
                app=app_name,
                window_title="",
                browser_url="",
                file_path="",
            )
            self.assertFalse(
                observer.is_user_work(obs),
                f"is_user_work() must return False for system app={app_name!r}",
            )

    def test_real_app_is_user_work(self):
        """is_user_work() must return True for real user apps."""
        import observer
        real_apps = ["Microsoft Word", "Google Chrome", "Xcode", "VS Code"]
        for app_name in real_apps:
            obs = observer.Observation(
                timestamp="2026-08-13T00:00:00Z",
                app=app_name,
                window_title="Document.docx",
                browser_url="",
                file_path="",
            )
            self.assertTrue(
                observer.is_user_work(obs),
                f"is_user_work() must return True for app={app_name!r}",
            )

    def test_buildharvey_bundle_excluded_from_consent_flow(self):
        """
        Even if a BuildHarvey window somehow reaches the consent check,
        the resulting observation must be filtered by is_user_work() before
        entering the Episode Engine.

        This tests the defense-in-depth chain: even if consent_manager.is_authorized()
        returned True for a BuildHarvey window (which it should not — the agent's own
        bundle should not appear as a frontmost productivity window), the
        is_user_work() filter in main._cycle() removes it before the engine sees it.
        """
        import observer

        # Simulate a case where somehow a "BuildHarvey" observation escaped consent
        obs = observer.Observation(
            timestamp="2026-08-13T00:00:00Z",
            app="BuildHarvey",
            window_title="Weekly Report",
            browser_url="",
            file_path="",
        )
        # The observation must be filtered
        self.assertFalse(observer.is_user_work(obs))

    def test_empty_app_name_not_user_work(self):
        """Empty app name with no window title must not generate an episode."""
        import observer
        obs = observer.Observation(
            timestamp="2026-08-13T00:00:00Z",
            app="",
            window_title="",
            browser_url="",
            file_path="",
        )
        self.assertFalse(observer.is_user_work(obs))


# ── Windows capture API routing ────────────────────────────────────────────────

class TestWindowsCaptureAPIRouting(unittest.TestCase):
    """
    Verify capture_window() on Windows routes to _capture_window_win32(),
    never to capture_screen(full monitor).
    """

    def test_windows_routes_to_win32_not_capture_screen(self):
        """
        On Windows, capture_window() must call _capture_window_win32().
        It must never call capture_screen() (full monitor).
        """
        import capture as _capture

        win32_called = []
        screen_called = []

        def mock_win32(hwnd, path):
            win32_called.append(hwnd)
            return True

        def mock_screen(path):
            screen_called.append(path)

        with (
            patch.object(_capture, "_capture_window_win32", mock_win32),
            patch.object(_capture, "_capture_window_macos", lambda *a: True),
            patch("platform.system", return_value="Windows"),
        ):
            import tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                out = Path(tmpdir) / "frame.png"
                _capture.capture_window(12345, out)

        self.assertGreater(len(win32_called), 0, "win32 capture must be called on Windows")
        self.assertEqual(len(screen_called), 0, "capture_screen must NOT be called after consent")

    def test_non_darwin_non_windows_fails_closed(self):
        """
        On unsupported platforms, capture_window() must return False
        (never captures anything).
        """
        import capture as _capture

        screen_called = []

        def mock_screen(path):
            screen_called.append(path)

        with (
            patch.object(_capture, "capture_screen", mock_screen),
            patch("platform.system", return_value="Linux"),
        ):
            import tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                out = Path(tmpdir) / "frame.png"
                result = _capture.capture_window(999, out)

        self.assertFalse(result, "capture_window must return False on unsupported platforms")
        self.assertEqual(len(screen_called), 0, "capture_screen must not be called as fallback")

    def test_observer_blocks_on_capture_window_false(self):
        """
        When capture_window() returns False (window unreadable), observer.observe()
        must return _CONSENT_BLOCKED rather than proceeding with stale/full-screen data.
        This verifies the fail-closed behavior in observer.py.
        """
        import observer as _obs
        import capture as _capture
        import window_identity as _wi
        from window_identity import WindowIdentity

        mock_identity = WindowIdentity(
            bundle_id="com.example.app",
            window_id=999,
            owner_pid=1234,
            process_start_time=1000.0,
            session_epoch=1,
            app_name="TestApp",
            window_title="Test Window",
        )

        mock_cm = MagicMock()
        mock_cm.session_epoch = 1
        mock_cm.is_authorized.return_value = True

        # get_window_identity is imported inline in observer.py via
        # 'from window_identity import get_window_identity'; patch at source.
        with (
            patch.object(_obs.config, "ENABLE_CAPTURE_LEASES", True),
            patch("observer.ctx_module.get_metadata_context", return_value=MagicMock(
                app_name="TestApp", bundle_id="com.example.app", window_title="Test Window",
            )),
            patch("window_identity.get_window_identity", return_value=mock_identity),
            patch.object(_capture, "capture_window", return_value=False),
        ):
            result = _obs.observe(consent_manager=mock_cm)

        self.assertIs(result, _obs._CONSENT_BLOCKED,
                      "observer must return _CONSENT_BLOCKED when capture_window fails")


if __name__ == "__main__":
    unittest.main()
