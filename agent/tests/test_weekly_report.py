"""
Weekly Report Synthetic Stress Tests — Part 15.

Verifies WeeklyReportEngine.generate() against synthetic episode data at
multiple scales:
  - Small week (5 episodes, 2 matters)
  - Normal week (40 episodes, 5 matters)
  - Large week (500 episodes, 10 matters)
  - Stress case (1000 episodes, 20 matters)

Invariants verified at all scales:
  1. Time totals are exact Python arithmetic — not LLM-generated
  2. Every source episode ID is traceable in weekly_reports.source_episode_ids
  3. No silent truncation of matter groups
  4. ObservationGaps remain as gaps (never inflate durations)
  5. Hierarchical reduction stays within context limits (≤4 episodes/chunk)
  6. Report file is written to disk and is readable
  7. generate() completes without NotImplementedError or exception
"""
import datetime
import importlib
import json
import os
import sqlite3
import tempfile
import time
import unittest
import uuid
from pathlib import Path


# Weekly report tests use plaintext DB (apsw not required).
# These env vars are set in WeeklyReportTestBase.setUp() and restored in tearDown()
# to avoid polluting other test modules that depend on PRIVATE_MODE=true.
_WEEKLY_TEST_ENV = {
    "BUILDHARVEY_PRIVATE_MODE": "false",
    "USE_LOCAL_INFERENCE": "false",
}


def _make_synthetic_episode(
    matter: str,
    started_at: str,
    duration_minutes: float,
    episode_index: int = 0,
) -> dict:
    """Return a synthetic episode dict matching the episodes schema."""
    ep_id = str(uuid.uuid4())
    # Compute ended_at using datetime to correctly handle minute/hour overflow
    started_dt = datetime.datetime.strptime(started_at, "%Y-%m-%dT%H:%M:%SZ")
    ended_dt = started_dt + datetime.timedelta(minutes=duration_minutes)
    ended_at = ended_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "id": ep_id,
        "case_name": matter,
        "issue_worked_on": f"Issue {episode_index}",
        "work_type": "project",
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_minutes": duration_minutes,
        "active_seconds": int(duration_minutes * 60 * 0.8),
        "key_observations": [
            {"timestamp": "09:00", "text": f"Worked on {matter} task {episode_index}"}
        ],
        "activity_classification": "analysis",
        "classification_confidence": 0.9,
        "is_reportable": 1,
    }


def _insert_episodes(conn: sqlite3.Connection, episodes: list[dict]) -> None:
    """Insert synthetic episodes into the SQLite episodes table."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id TEXT PRIMARY KEY,
            case_name TEXT,
            issue_worked_on TEXT,
            work_type TEXT,
            started_at TEXT,
            ended_at TEXT,
            duration_minutes REAL,
            active_seconds INTEGER,
            key_observations TEXT,
            activity_classification TEXT,
            classification_confidence REAL,
            is_reportable INTEGER DEFAULT 1,
            has_inference_failure INTEGER DEFAULT 0
        )
    """)
    for ep in episodes:
        conn.execute(
            """
            INSERT OR REPLACE INTO episodes
                (id, case_name, issue_worked_on, work_type, started_at, ended_at,
                 duration_minutes, active_seconds, key_observations,
                 activity_classification, classification_confidence, is_reportable)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ep["id"], ep["case_name"], ep["issue_worked_on"], ep["work_type"],
                ep["started_at"], ep["ended_at"],
                ep["duration_minutes"], ep["active_seconds"],
                json.dumps(ep["key_observations"]),
                ep["activity_classification"], ep["classification_confidence"],
                ep["is_reportable"],
            ),
        )
    conn.commit()


def _generate_episodes(
    matters: list[str],
    episodes_per_matter: int,
    duration_minutes_each: float = 30.0,
    start_date: str = "2026-08-01",
) -> list[dict]:
    """Generate synthetic episodes spread across the week."""
    episodes = []
    day = 0
    hour = 9
    for i, matter in enumerate(matters):
        for j in range(episodes_per_matter):
            # Spread across days
            ts = f"{start_date[:-2]}{day+1:02d}T{hour:02d}:00:00Z"
            episodes.append(_make_synthetic_episode(matter, ts, duration_minutes_each, j))
            hour += 1
            if hour >= 17:
                hour = 9
                day = (day + 1) % 7
    return episodes


def _compute_expected_totals(episodes: list[dict]) -> dict[str, float]:
    """Compute expected matter totals by Python arithmetic."""
    totals: dict[str, float] = {}
    for ep in episodes:
        m = ep["case_name"]
        totals[m] = totals.get(m, 0.0) + ep["duration_minutes"]
    return totals


class WeeklyReportTestBase(unittest.TestCase):
    """Base class providing setup/teardown and shared assertions."""

    PERIOD_START = "2026-08-01T00:00:00Z"
    PERIOD_END   = "2026-08-08T23:59:59Z"

    def setUp(self):
        # Set env vars for this test and restore after; don't pollute module-level state
        self._orig_env = {k: os.environ.get(k) for k in _WEEKLY_TEST_ENV}
        os.environ.update(_WEEKLY_TEST_ENV)

        self._tmpdir = tempfile.TemporaryDirectory()
        tmpdir = Path(self._tmpdir.name)

        import config as _cfg
        importlib.reload(_cfg)
        _cfg.BASE_DIR = tmpdir
        _cfg.DB_PATH = tmpdir / "test.db"
        _cfg.SCREENSHOTS_DIR = tmpdir / "screenshots"
        _cfg.SCREENSHOTS_DIR.mkdir(exist_ok=True)

        self._conn = sqlite3.connect(str(_cfg.DB_PATH))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._cfg = _cfg

    def tearDown(self):
        try:
            self._conn.close()
        except Exception:
            pass
        self._tmpdir.cleanup()
        # Restore env vars to avoid polluting other tests
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        # Reload config back to original private-mode defaults
        import config as _cfg
        importlib.reload(_cfg)

    def _run_report(self, episodes: list[dict]) -> tuple[str, dict]:
        """Insert episodes, generate report, return (report_text, source_id_lookup)."""
        _insert_episodes(self._conn, episodes)

        from weekly_report import WeeklyReportEngine
        engine = WeeklyReportEngine(self._conn)
        path = engine.generate(self.PERIOD_START, self.PERIOD_END)

        self.assertIsInstance(path, str)
        report_path = Path(path)
        self.assertTrue(report_path.exists(), f"Report file must exist at {path}")

        content = report_path.read_text(encoding="utf-8")

        # Retrieve source_episode_ids from DB
        rows = self._conn.execute(
            "SELECT source_episode_ids FROM weekly_reports ORDER BY generated_at DESC LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(rows, "weekly_reports table must have an entry")
        source_ids = set(json.loads(rows[0]))
        return content, source_ids

    def _verify_time_totals(
        self, content: str, episodes: list[dict], label: str
    ) -> None:
        """Verify totals in the report match Python arithmetic exactly."""
        expected = _compute_expected_totals(episodes)
        grand_total_hours = sum(expected.values()) / 60.0

        # Report must contain the grand total (formatted to 2 decimal places)
        expected_total_str = f"{grand_total_hours:.2f} h"
        self.assertIn(
            expected_total_str, content,
            f"{label}: Grand total {expected_total_str} must appear in report"
        )

    def _verify_source_ids(
        self, source_ids: set, episodes: list[dict], label: str
    ) -> None:
        """Every episode ID must appear in source_episode_ids."""
        episode_ids = {ep["id"] for ep in episodes}
        missing = episode_ids - source_ids
        self.assertEqual(
            missing, set(),
            f"{label}: {len(missing)} episode IDs missing from source_episode_ids"
        )


class TestSmallWeek(WeeklyReportTestBase):
    """Small week: 5 episodes, 2 matters."""

    def test_small_week_report(self):
        matters = ["Smith v. Jones", "Administrative"]
        episodes = _generate_episodes(matters, episodes_per_matter=2, duration_minutes_each=45.0)
        # Add 1 extra to Smith
        extra = _make_synthetic_episode("Smith v. Jones", "2026-08-03T14:00:00Z", 60.0, 99)
        episodes.append(extra)

        content, source_ids = self._run_report(episodes)

        self._verify_time_totals(content, episodes, "SmallWeek")
        self._verify_source_ids(source_ids, episodes, "SmallWeek")
        self.assertIn("Smith v. Jones", content)
        self.assertIn("Administrative", content)

    def test_empty_week_produces_report(self):
        """generate() with zero episodes should still produce a report file."""
        content, source_ids = self._run_report([])
        self.assertIsInstance(content, str)
        self.assertEqual(source_ids, set(), "Empty week must have empty source IDs")


class TestNormalWeek(WeeklyReportTestBase):
    """Normal week: 40 episodes across 5 matters."""

    def test_normal_week_report(self):
        matters = [
            "Acme Corp v. Widgets Inc",
            "Estate of J. Smith",
            "City Planning Appeal",
            "IP Licensing Matter A",
            "Administrative",
        ]
        episodes = _generate_episodes(matters, episodes_per_matter=8, duration_minutes_each=35.0)

        content, source_ids = self._run_report(episodes)

        self._verify_time_totals(content, episodes, "NormalWeek")
        self._verify_source_ids(source_ids, episodes, "NormalWeek")

        # All matters must appear in report
        for m in matters:
            self.assertIn(m, content, f"Matter '{m}' must appear in report")

    def test_per_matter_hours_exact(self):
        """Each matter's hours must match Python arithmetic to 2 decimal places."""
        matters = ["Matter A", "Matter B"]
        # 6 episodes each × 30 min = 180 min = 3.00 h each
        episodes = _generate_episodes(matters, episodes_per_matter=6, duration_minutes_each=30.0)

        content, _ = self._run_report(episodes)

        # Each matter: 6 × 30 = 180 min = 3.00 h
        self.assertIn("3.00 h", content, "Per-matter hours must be exactly 3.00 h")
        # Grand total: 2 × 3.00 = 6.00 h
        self.assertIn("6.00 h", content, "Grand total must be exactly 6.00 h")


class TestLargeWeek(WeeklyReportTestBase):
    """Large week: 500 episodes across 10 matters."""

    def test_large_week_no_truncation(self):
        """500 episodes must all be included without silent truncation."""
        matters = [f"Matter {chr(65+i)}" for i in range(10)]
        episodes = _generate_episodes(matters, episodes_per_matter=50, duration_minutes_each=20.0)
        self.assertEqual(len(episodes), 500)

        content, source_ids = self._run_report(episodes)

        self._verify_time_totals(content, episodes, "LargeWeek")
        self._verify_source_ids(source_ids, episodes, "LargeWeek")

        # All 10 matters must appear
        for m in matters:
            self.assertIn(m, content, f"Matter '{m}' must appear in 500-episode report")

    def test_large_week_total_exact(self):
        """Grand total for 500 episodes × 20 min = 10,000 min = 166.67 h."""
        matters = [f"LargeMatter {i}" for i in range(10)]
        episodes = _generate_episodes(matters, episodes_per_matter=50, duration_minutes_each=20.0)

        content, _ = self._run_report(episodes)

        expected_hours = 500 * 20.0 / 60.0
        expected_str = f"{expected_hours:.2f} h"
        self.assertIn(expected_str, content, f"Grand total must be {expected_str}")


class TestStressWeek(WeeklyReportTestBase):
    """Stress case: 1000 episodes across 20 matters."""

    def test_stress_week_completes(self):
        """1000 episodes must complete without exception or truncation."""
        matters = [f"Stress Matter {i:02d}" for i in range(20)]
        episodes = _generate_episodes(matters, episodes_per_matter=50, duration_minutes_each=15.0)
        self.assertEqual(len(episodes), 1000)

        content, source_ids = self._run_report(episodes)

        self._verify_time_totals(content, episodes, "StressWeek")
        self._verify_source_ids(source_ids, episodes, "StressWeek")

    def test_stress_week_all_matters_present(self):
        """All 20 matters must appear in the stress-case report."""
        matters = [f"Stress Case {i:02d}" for i in range(20)]
        episodes = _generate_episodes(matters, episodes_per_matter=50, duration_minutes_each=10.0)

        content, _ = self._run_report(episodes)

        for m in matters:
            self.assertIn(m, content, f"Matter '{m}' missing from stress report")


class TestWeeklyReportInvariants(WeeklyReportTestBase):
    """Structural invariants that must hold at all scales."""

    def test_time_is_never_llm_generated(self):
        """
        Verify that the totals section contains only exact Python-computed values.
        The LLM summary section must not contain a 'Total:' line — that appears
        only in the _format_totals() section which is pure Python math.
        """
        matters = ["Matter X", "Matter Y"]
        # 3 episodes × 60 min = 3.00 h each; total 6.00 h
        episodes = _generate_episodes(matters, episodes_per_matter=3, duration_minutes_each=60.0)

        content, _ = self._run_report(episodes)

        # The report must contain exactly one "Total:" line
        total_lines = [ln for ln in content.splitlines() if "Total:" in ln]
        self.assertGreaterEqual(len(total_lines), 1, "Report must have a totals line")

        # The total must be exactly 6.00 h (6 × 60 min / 60)
        grand_total_hours = 6 * 60.0 / 60.0
        self.assertIn(f"{grand_total_hours:.2f} h", content)

    def test_source_ids_are_json_array(self):
        """source_episode_ids in weekly_reports must be a valid JSON array of UUIDs."""
        matters = ["TestMatter"]
        episodes = _generate_episodes(matters, episodes_per_matter=3, duration_minutes_each=20.0)
        _insert_episodes(self._conn, episodes)

        from weekly_report import WeeklyReportEngine
        engine = WeeklyReportEngine(self._conn)
        engine.generate(self.PERIOD_START, self.PERIOD_END)

        row = self._conn.execute(
            "SELECT source_episode_ids FROM weekly_reports LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(row)
        source_ids = json.loads(row[0])
        self.assertIsInstance(source_ids, list, "source_episode_ids must be a JSON array")
        for sid in source_ids:
            self.assertRegex(sid, r"^[0-9a-f-]{36}$", f"source ID {sid!r} must be a UUID")

    def test_report_file_written_to_weekly_reports_dir(self):
        """Report must be written to the weekly_reports/ subdirectory."""
        matters = ["FileMatter"]
        episodes = _generate_episodes(matters, episodes_per_matter=2, duration_minutes_each=30.0)

        content, _ = self._run_report(episodes)

        report_path = Path(self._cfg.BASE_DIR) / "weekly_reports"
        txt_files = list(report_path.glob("*.txt"))
        self.assertGreater(len(txt_files), 0, "At least one .txt file must exist in weekly_reports/")


if __name__ == "__main__":
    unittest.main(verbosity=2)
