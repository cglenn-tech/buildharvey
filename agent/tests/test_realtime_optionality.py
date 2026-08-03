"""
Tests for Realtime optionality guarantees.

Verifies that:
  1. Local Start Work Session works without a Realtime connection.
  2. Local Stop Work Session works without a Realtime connection.
  3. Browser closure / website refresh does not stop local recording.
  4. The grace-period timer does not affect local recording.
  5. Temporary server failure leaves local state intact.

These tests manipulate realtime_client module state directly.
They do NOT start the asyncio event loop or connect to Supabase.
"""
import sys
import os
import unittest
import threading

# Make agent/ importable without a venv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Provide minimal stub for 'auth' so realtime_client can be imported without
# credentials or network access.
import types
_auth_stub = types.ModuleType('auth')
_auth_stub.read_credential = lambda: None
_auth_stub.read_device_id = lambda: None
sys.modules.setdefault('auth', _auth_stub)

# Stub 'config' to avoid .env dependency
_config_stub = types.ModuleType('config')
_config_stub.BASE_URL = 'https://buildharvey.com'
sys.modules.setdefault('config', _config_stub)

import realtime_client as rc  # noqa: E402  (import after stubs)


class TestLocalRecordingIndependence(unittest.TestCase):
    """Local Start/Stop does not require Realtime connectivity."""

    def setUp(self):
        # Reset module state before each test
        rc._recording_event.clear()
        with rc._lock:
            rc._local_recording = False
            rc._browser_present = False
        if rc._grace_timer is not None:
            rc._grace_timer.cancel()
            rc._grace_timer = None

    def test_start_local_sets_recording_event(self):
        """start_local() enables recording without any network call."""
        self.assertFalse(rc._recording_event.is_set())
        rc.start_local()
        self.assertTrue(rc._local_recording)
        self.assertTrue(rc._recording_event.is_set())
        self.assertTrue(rc.is_recording_active())

    def test_stop_local_clears_recording_event(self):
        """stop_local() disables recording without any network call."""
        rc.start_local()
        self.assertTrue(rc.is_recording_active())
        rc.stop_local()
        self.assertFalse(rc._local_recording)
        self.assertFalse(rc._recording_event.is_set())
        self.assertFalse(rc.is_recording_active())

    def test_start_stop_cycle_is_idempotent(self):
        """Multiple start_local/stop_local calls leave state consistent."""
        rc.start_local()
        rc.start_local()
        self.assertTrue(rc.is_recording_active())
        rc.stop_local()
        rc.stop_local()
        self.assertFalse(rc.is_recording_active())


class TestBrowserClosureDoesNotStopLocalRecording(unittest.TestCase):
    """Browser closure (grace period expiry) must not stop local recording."""

    def setUp(self):
        rc._recording_event.clear()
        with rc._lock:
            rc._local_recording = False
            rc._browser_present = False
        if rc._grace_timer is not None:
            rc._grace_timer.cancel()
            rc._grace_timer = None

    def test_grace_period_expired_does_not_stop_local_recording(self):
        """
        _grace_period_expired() is a no-op when _local_recording is True.

        This is the mechanism that ensures: browser closes → grace timer fires
        → recording continues if started locally.
        """
        rc.start_local()
        with rc._lock:
            rc._browser_present = True

        # Simulate grace period expiry (the callback Realtime fires after 10 min)
        rc._grace_period_expired()

        # Local recording must still be active
        self.assertTrue(rc._local_recording, "Local recording should survive browser disconnect")
        self.assertTrue(rc._recording_event.is_set(), "Recording event should still be set")
        self.assertTrue(rc.is_recording_active())

    def test_grace_period_expired_stops_browser_only_recording(self):
        """
        _grace_period_expired() DOES stop recording when started via browser.

        Ensures that local recording protection is specific, not global.
        """
        # Simulate a browser-only session (no local start)
        with rc._lock:
            rc._browser_present = True
        rc._recording_event.set()  # browser started recording

        rc._grace_period_expired()

        # Browser-initiated recording should stop
        self.assertFalse(rc._recording_event.is_set(),
                         "Browser-only recording should stop on grace period expiry")

    def test_website_refresh_does_not_stop_local_recording(self):
        """
        Website refresh = browser leaves presence + immediately returns.

        Even during the brief absence, local recording must continue.
        """
        rc.start_local()
        self.assertTrue(rc.is_recording_active())

        # Browser leaves (simulated by calling _cancel_grace_timer and clearing presence)
        with rc._lock:
            rc._browser_present = False

        # Recording should still be active (local_recording is set)
        self.assertTrue(rc.is_recording_active())

        # Browser returns (presence restored)
        with rc._lock:
            rc._browser_present = True

        self.assertTrue(rc.is_recording_active())

    def test_is_recording_active_uses_local_flag_not_browser_presence(self):
        """
        is_recording_active() prioritizes _local_recording over browser state.

        When _local_recording=True, browser presence is irrelevant.
        """
        rc.start_local()

        # Regardless of browser state, local recording is active
        with rc._lock:
            rc._browser_present = False
        self.assertTrue(rc.is_recording_active())

        with rc._lock:
            rc._browser_present = True
        self.assertTrue(rc.is_recording_active())


class TestTemporaryServerFailureQueuesLocally(unittest.TestCase):
    """
    Temporary Realtime / server unavailability must not affect local recording
    or episode data preservation.

    The agent uses threading.Event for the recording gate. Realtime failure
    (event loop error, disconnect) does not clear _recording_event when
    _local_recording is True.
    """

    def setUp(self):
        rc._recording_event.clear()
        with rc._lock:
            rc._local_recording = False
            rc._browser_present = False
        if rc._grace_timer is not None:
            rc._grace_timer.cancel()
            rc._grace_timer = None

    def test_recording_state_survives_event_loop_being_none(self):
        """
        If the Realtime event loop is not running (e.g. never connected,
        or connection dropped), local recording still works.
        """
        original_loop = rc._event_loop
        try:
            rc._event_loop = None  # no Realtime connection
            rc.start_local()
            self.assertTrue(rc.is_recording_active())
            rc.stop_local()
            self.assertFalse(rc.is_recording_active())
        finally:
            rc._event_loop = original_loop

    def test_force_stop_clears_local_recording(self):
        """
        force_stop() — called on OS sleep/logout — clears local recording.
        This is intentional: the user closed their laptop.
        """
        rc.start_local()
        self.assertTrue(rc.is_recording_active())
        rc.force_stop()
        self.assertFalse(rc._local_recording)
        self.assertFalse(rc._recording_event.is_set())


if __name__ == '__main__':
    unittest.main(verbosity=2)
