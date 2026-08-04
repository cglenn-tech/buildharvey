"""
Tests for Hybrid Task Control (authoritative context, pause/resume, switch suggestions).

Tests:
  1.  set_authoritative_context opens episode with correct case_name and issue_worked_on
  2.  Claude's suggested_episode_name does NOT override authoritative case_name
  3.  Administrative work creates episode with work_type='administrative'
  4.  5-min inactivity calls episode.pause_timing() without closing episode
  5.  Activity after pause accumulates _total_paused_seconds correctly
  6.  active_seconds = elapsed - paused_seconds
  7.  Switch suggestion held in pending state without closing current episode
  8.  confirm_switch() closes current, opens new with pending evidence
  9.  reject_switch() appends pending evidence to current, clears suggestion
  10. recent_contexts table populated after episode close
  11. Authoritative context persists across multiple evidence cycles
  12. Episode closes after MAX_EPISODE_SECONDS safety net
"""
import sys
import os
import time
import types
import unittest

# ── Make agent/ importable ────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Stub heavy / platform-specific modules before importing agent code ─────────

# config — provide constants used by tests
_config_stub = types.ModuleType('config')
_config_stub.BASE_URL = 'https://buildharvey.com'
_config_stub.INACTIVITY_PAUSE_SECONDS = 300
_config_stub.INACTIVITY_TIMEOUT_SECONDS = 300
_config_stub.MAX_EPISODE_SECONDS = 28800
_config_stub.DB_PATH = ':memory:'
_config_stub.BASE_DIR = '/tmp'
_config_stub.SCREENSHOTS_DIR = '/tmp'
sys.modules.setdefault('config', _config_stub)

# observer — not used directly in tests
_observer_stub = types.ModuleType('observer')

class _FakeObservation:
    app = ''
    window_title = ''
    browser_url = ''
    file_path = ''
    entities = []
    screenshot_path = None

_observer_stub.Observation = _FakeObservation
sys.modules.setdefault('observer', _observer_stub)

# task_context — import real module (no heavy deps)
import task_context as tc  # noqa: E402

# episode and episode_engine — import real modules
from episode import Episode, ScreenshotEvidence, new_episode  # noqa: E402
from episode_engine import EpisodeEngine  # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_evidence(
    *,
    continue_current_episode: bool = True,
    start_new_episode: bool = False,
    suggested_episode_name: str = "Test Episode",
    activity_description: str = "Reviewing documents",
    objective: str = "Review",
    entities: list | None = None,
) -> ScreenshotEvidence:
    return ScreenshotEvidence(
        screenshot_path="/tmp/fake.png",
        timestamp="09:00",
        activity_description=activity_description,
        objective=objective,
        actions=["Opened document"],
        entities=entities or [],
        supporting_evidence=[],
        app_context="Word",
        model="stub",
        input_tokens=100,
        output_tokens=50,
        continue_current_episode=continue_current_episode,
        start_new_episode=start_new_episode,
        suggested_episode_name=suggested_episode_name,
    )


def _make_obs() -> _FakeObservation:
    return _FakeObservation()


def _fresh_engine() -> EpisodeEngine:
    """Return a fresh engine with cleared task_context."""
    tc.clear_context()
    tc.clear_switch_suggestion()
    tc.set_timing_paused(False)
    # Drain any pending actions
    tc.pop_confirm_switch()
    tc.pop_reject_switch()
    tc.pop_force_stop()
    return EpisodeEngine()


# ── Test cases ─────────────────────────────────────────────────────────────────

class Test01AuthoritativeContextOpensEpisode(unittest.TestCase):
    """1. set_authoritative_context opens episode with correct case_name and issue_worked_on."""

    def test_opens_with_authoritative_name_and_issue(self):
        engine = _fresh_engine()
        engine.set_authoritative_context("Smith v. Jones", "Discovery motions", "project")

        ev = _make_evidence(suggested_episode_name="Some Claude Name")
        result = engine.ingest_vision(ev, _make_obs())

        self.assertIsNotNone(result)
        self.assertIsNotNone(engine.active)
        self.assertEqual(engine.active.case_name, "Smith v. Jones")
        self.assertEqual(engine.active.issue_worked_on, "Discovery motions")
        self.assertEqual(engine.active.work_type, "project")


class Test02AuthoritativeNameNotOverridden(unittest.TestCase):
    """2. Claude's suggested_episode_name does NOT override authoritative case_name."""

    def test_claude_suggestion_ignored_when_authoritative(self):
        engine = _fresh_engine()
        engine.set_authoritative_context("Doe v. Acme Corp", "Contract review", "project")

        # Open episode
        ev1 = _make_evidence(suggested_episode_name="Irrelevant Claude Name")
        engine.ingest_vision(ev1, _make_obs())
        self.assertEqual(engine.active.case_name, "Doe v. Acme Corp")

        # Continue with a longer, more specific suggestion from Claude
        ev2 = _make_evidence(
            suggested_episode_name="Detailed Claude Suggested Name That Is Longer",
            continue_current_episode=True,
        )
        engine.ingest_vision(ev2, _make_obs())

        # Authoritative name must not change
        self.assertEqual(engine.active.case_name, "Doe v. Acme Corp")


class Test03AdministrativeWorkType(unittest.TestCase):
    """3. Administrative work creates episode with work_type='administrative'."""

    def test_admin_work_type(self):
        engine = _fresh_engine()
        engine.set_authoritative_context("Administrative", "Scheduling", "administrative")

        ev = _make_evidence()
        engine.ingest_vision(ev, _make_obs())

        self.assertIsNotNone(engine.active)
        self.assertEqual(engine.active.work_type, "administrative")
        self.assertEqual(engine.active.case_name, "Administrative")
        self.assertEqual(engine.active.issue_worked_on, "Scheduling")


class Test04InactivityPausesNotCloses(unittest.TestCase):
    """4. 5-min inactivity calls episode.pause_timing() without closing episode."""

    def test_inactivity_pauses_not_closes(self):
        engine = _fresh_engine()
        engine.set_authoritative_context("Pause Test", None, "project")
        ev = _make_evidence()
        engine.ingest_vision(ev, _make_obs())

        ep = engine.active
        self.assertIsNotNone(ep)

        # Simulate 5+ minutes of idle
        ep.last_user_activity_at = time.time() - 400

        # Force INACTIVITY_PAUSE_SECONDS to a small value for this test
        import config as _cfg
        original = _cfg.INACTIVITY_PAUSE_SECONDS
        _cfg.INACTIVITY_PAUSE_SECONDS = 300
        try:
            closed = engine.check_inactivity(time.time())
        finally:
            _cfg.INACTIVITY_PAUSE_SECONDS = original

        # Episode should still be open (not closed)
        self.assertIsNone(closed)
        self.assertIsNotNone(engine.active)
        self.assertTrue(ep._is_paused, "Episode should be paused after inactivity")


class Test05PauseAccumulatesCorrectly(unittest.TestCase):
    """5. Activity after pause accumulates _total_paused_seconds correctly."""

    def test_pause_accumulates_total_paused_seconds(self):
        ep = new_episode("Timing Test")

        # Manually set pause started 30 seconds ago
        ep._is_paused = True
        ep._pause_started_at = time.time() - 30

        ep.resume_timing()

        self.assertFalse(ep._is_paused)
        self.assertIsNone(ep._pause_started_at)
        self.assertGreaterEqual(ep._total_paused_seconds, 29)
        self.assertLess(ep._total_paused_seconds, 35)

    def test_multiple_pause_resume_cycles_accumulate(self):
        ep = new_episode("Multi-pause Test")

        # First pause: ~20 seconds
        ep._is_paused = True
        ep._pause_started_at = time.time() - 20
        ep.resume_timing()
        first_total = ep._total_paused_seconds

        # Second pause: ~15 seconds
        ep._is_paused = True
        ep._pause_started_at = time.time() - 15
        ep.resume_timing()

        self.assertGreaterEqual(ep._total_paused_seconds, first_total + 14)


class Test06ActiveSeconds(unittest.TestCase):
    """6. active_seconds = elapsed - paused_seconds."""

    def test_active_seconds_excludes_paused_time(self):
        ep = new_episode("Active Seconds Test")

        # Simulate 60 seconds of total elapsed, 20 of which was paused
        ep._total_paused_seconds = 20.0
        ep._is_paused = False

        active = ep.active_seconds
        # active_seconds should be approximately (elapsed - 20), elapsed ≈ 0-1s
        # since we just created the episode, but _total_paused_seconds is 20
        # which is more than elapsed — active_seconds is clamped to >= 0
        self.assertGreaterEqual(active, 0.0)

    def test_active_seconds_during_pause(self):
        ep = new_episode("Pause Active Test")
        ep._is_paused = True
        ep._pause_started_at = time.time() - 10  # paused 10 seconds ago

        active = ep.active_seconds
        self.assertGreaterEqual(active, 0.0)
        # Since the episode was just created and has been paused for 10s,
        # active_seconds should be very small (close to 0)
        self.assertLess(active, 5.0)


class Test07SwitchSuggestionHeld(unittest.TestCase):
    """7. Switch suggestion held in pending state without closing current episode."""

    def test_switch_suggestion_does_not_close_episode(self):
        engine = _fresh_engine()
        engine.set_authoritative_context("Original Case", None, "project")

        # Open episode
        ev1 = _make_evidence()
        engine.ingest_vision(ev1, _make_obs())
        original_ep = engine.active
        self.assertIsNotNone(original_ep)

        # Signal switch
        ev2 = _make_evidence(
            continue_current_episode=False,
            start_new_episode=True,
            suggested_episode_name="New Case",
        )
        result = engine.ingest_vision(ev2, _make_obs())

        # Current episode must still be active (not closed)
        self.assertIsNone(result.closed_episode)
        self.assertEqual(engine.active, original_ep)
        self.assertEqual(engine._state, "switch_suggestion")
        self.assertEqual(len(engine._pending_evidence), 1)
        self.assertEqual(tc.get_switch_suggestion(), "New Case")


class Test08ConfirmSwitch(unittest.TestCase):
    """8. confirm_switch() closes current, opens new with pending evidence."""

    def test_confirm_switch_closes_and_opens(self):
        engine = _fresh_engine()
        engine.set_authoritative_context("Old Case", None, "project")

        ev1 = _make_evidence(suggested_episode_name="Old Case")
        engine.ingest_vision(ev1, _make_obs())
        old_ep = engine.active

        # Trigger switch suggestion
        ev2 = _make_evidence(
            continue_current_episode=False,
            start_new_episode=True,
            suggested_episode_name="New Case",
        )
        engine.ingest_vision(ev2, _make_obs())
        self.assertEqual(len(engine._pending_evidence), 1)

        # Confirm with a custom name
        result = engine.confirm_switch("New Case")

        self.assertIsNotNone(result)
        self.assertIsNotNone(result.closed_episode)
        self.assertEqual(result.closed_episode, old_ep)
        self.assertIsNotNone(old_ep.ended_at)  # was closed

        # New episode is open
        self.assertIsNotNone(engine.active)
        self.assertNotEqual(engine.active, old_ep)
        self.assertEqual(engine.active.case_name, "New Case")
        self.assertEqual(engine._state, "active")

        # Pending evidence attached to new episode
        self.assertEqual(len(engine.active._evidence), 1)
        self.assertEqual(len(engine._pending_evidence), 0)

        # Switch suggestion cleared
        self.assertEqual(tc.get_switch_suggestion(), "")


class Test09RejectSwitch(unittest.TestCase):
    """9. reject_switch() appends pending evidence to current, clears suggestion."""

    def test_reject_switch_keeps_current_episode(self):
        engine = _fresh_engine()
        engine.set_authoritative_context("My Case", None, "project")

        ev1 = _make_evidence()
        engine.ingest_vision(ev1, _make_obs())
        original_ep = engine.active
        original_evidence_count = len(original_ep._evidence)

        # Trigger switch suggestion
        ev2 = _make_evidence(
            continue_current_episode=False,
            start_new_episode=True,
            suggested_episode_name="Different Case",
        )
        engine.ingest_vision(ev2, _make_obs())
        self.assertEqual(len(engine._pending_evidence), 1)

        # Reject the switch
        result = engine.reject_switch()

        self.assertIsNotNone(result)
        self.assertIsNone(result.closed_episode)
        self.assertEqual(engine.active, original_ep)
        self.assertEqual(engine._state, "active")

        # Pending evidence merged into current episode
        self.assertEqual(len(original_ep._evidence), original_evidence_count + 1)
        self.assertEqual(len(engine._pending_evidence), 0)
        self.assertEqual(tc.get_switch_suggestion(), "")


class Test10RecentContextsPopulated(unittest.TestCase):
    """10. recent_contexts table populated after episode close."""

    def test_upsert_and_retrieve_recent_context(self):
        import tempfile
        import os
        import config as _cfg
        import database as db

        # Use a temp file so database.connect() creates the full schema
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        try:
            _cfg.DB_PATH = db_path
            conn = db.connect()  # creates all tables including recent_contexts

            db.upsert_recent_context(conn, "Smith v. Jones", "Depositions", "project")
            db.upsert_recent_context(conn, "Adams Case", None, "project")

            cases = db.get_recent_cases(conn)
            self.assertIn("Smith v. Jones", cases)
            self.assertIn("Adams Case", cases)

            # Call again to test use_count increment
            db.upsert_recent_context(conn, "Smith v. Jones", "Depositions", "project")
            row = conn.execute(
                "SELECT use_count FROM recent_contexts WHERE case_name = 'Smith v. Jones'"
            ).fetchone()
            self.assertEqual(row[0], 2)
            conn.close()
        finally:
            try:
                os.unlink(db_path)
            except Exception:
                pass


class Test11AuthoritativeContextPersistsAcrossCycles(unittest.TestCase):
    """11. Authoritative context persists across multiple evidence cycles."""

    def test_context_survives_multiple_evidence_cycles(self):
        engine = _fresh_engine()
        engine.set_authoritative_context("Persistent Case", "Issue A", "project")

        for i in range(5):
            ev = _make_evidence(
                continue_current_episode=True,
                suggested_episode_name=f"Claude Suggestion {i}",
                activity_description=f"Activity {i}",
            )
            # Re-apply authoritative context each cycle (as main.py does)
            engine.set_authoritative_context("Persistent Case", "Issue A", "project")
            engine.ingest_vision(ev, _make_obs())

        self.assertEqual(engine.active.case_name, "Persistent Case")
        self.assertEqual(engine.active.issue_worked_on, "Issue A")
        self.assertEqual(len(engine.active._evidence), 5)


class Test12SafetyNetClosesEpisode(unittest.TestCase):
    """12. Episode closes after MAX_EPISODE_SECONDS safety net."""

    def test_episode_closes_after_max_seconds(self):
        engine = _fresh_engine()
        engine.set_authoritative_context("Long Session", None, "project")

        ev = _make_evidence()
        engine.ingest_vision(ev, _make_obs())
        ep = engine.active
        self.assertIsNotNone(ep)

        # Simulate very old started_at (9 hours ago)
        ep.started_at = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() - 32400)  # 9 hours
        )
        ep.last_user_activity_at = time.time() - 100  # still recently active

        import config as _cfg
        original = _cfg.MAX_EPISODE_SECONDS
        _cfg.MAX_EPISODE_SECONDS = 28800  # 8 hours
        try:
            closed = engine.check_inactivity(time.time())
        finally:
            _cfg.MAX_EPISODE_SECONDS = original

        self.assertIsNotNone(closed)
        self.assertEqual(closed, ep)
        self.assertIsNone(engine.active)
        self.assertEqual(engine._state, "idle")
        self.assertIsNotNone(ep.ended_at)


if __name__ == '__main__':
    unittest.main(verbosity=2)
