"""
Weekly Report Engine — Phase 6 of the privacy architecture.

Generates weekly work reports entirely on-device using the local inference backend.
No work content leaves the device. Reports are stored in a local SQLite table
and can be exported by the user as PDF or text.

Status: SCAFFOLD — Phase 6 implementation deferred until Phase 5 (local episode
finalization) is confirmed stable on all target hardware.

Prerequisites:
  - Phase 5 stable: local episode finalization working on all platforms
  - local_inference benchmark results confirm Tier 2 model meets quality thresholds

When fully implemented this module will:
  1. Query episodes from the specified date range from SQLite
  2. Group episodes by matter/case
  3. Generate daily summaries using LocalInferenceBackend.summarize_episode()
  4. Compose a weekly narrative using the Tier 2 model
  5. Store the report in the weekly_reports SQLite table
  6. Return the local file path for the user to open/export

Network endpoints removed in Phase 6: /api/report
"""
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

import config
from bh_logging import get_logger

log = get_logger("weekly_report")


class WeeklyReportEngine:
    """
    Generates weekly work reports locally from SQLite episode data.

    Reports are stored in ~/.buildharvey/weekly_reports/ as JSON + plain text.
    No network calls are made during report generation.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._reports_dir = config.BASE_DIR / "weekly_reports"
        self._reports_dir.mkdir(exist_ok=True)

    def generate(self, period_start: str, period_end: str) -> str:
        """
        Generate a weekly report for the given ISO 8601 date range.

        Pipeline:
          1. Query reportable episodes for the period
          2. Group by case_name (matter)
          3. For each matter: chunk into ≤4 episode groups, summarize each chunk,
             merge if >1 chunk into a final matter summary
          4. Compose weekly narrative from all matter summaries
          5. Append time totals (computed by Python — never by LLM)
          6. Store in weekly_reports SQLite table with source_episode_ids
          7. Write plain text file to weekly_reports/ directory

        Returns the local file path of the generated report.
        """
        from local_inference import get_backend
        backend = get_backend()

        episodes = self._query_episodes(period_start, period_end)
        if not episodes:
            log.info("weekly_report.no_episodes", period_start=period_start, period_end=period_end)

        report_id = str(uuid.uuid4())
        source_ids = [e["id"] for e in episodes]

        # Group episodes by matter (case_name)
        matter_groups: dict[str, list[dict]] = {}
        for ep in episodes:
            matter = ep["case_name"] or "Administrative"
            matter_groups.setdefault(matter, []).append(ep)

        matter_summaries: list[dict] = []
        for matter, matter_episodes in matter_groups.items():
            summary = self._summarize_matter(backend, matter, matter_episodes)
            total_minutes = sum(e["duration_minutes"] or 0.0 for e in matter_episodes)
            matter_summaries.append({
                "matter": matter,
                "summary": summary,
                "duration_minutes": total_minutes,
                "episode_count": len(matter_episodes),
            })

        narrative = self._compose_narrative(backend, matter_summaries, period_start, period_end)
        totals = self._format_totals(matter_summaries)

        content = _assemble_report(
            period_start=period_start,
            period_end=period_end,
            narrative=narrative,
            totals=totals,
            matter_summaries=matter_summaries,
        )

        return self._save_report(report_id, period_start, period_end, content, source_ids)

    def _summarize_matter(self, backend, matter: str, episodes: list[dict]) -> str:
        """
        Summarize all episodes for one matter using hierarchical chunking.

        Chunks episodes into groups of ≤4, summarizes each chunk, then merges
        chunk summaries into a final matter summary when >1 chunk.
        """
        _CHUNK_SIZE = 4

        if not episodes:
            return ""

        if not backend.is_available():
            # Fallback: concatenate key observations as plain text
            lines = []
            for ep in episodes:
                for ko in ep.get("key_observations", []):
                    text = ko.get("text", "") if isinstance(ko, dict) else str(ko)
                    if text:
                        lines.append(f"- {text}")
            return "\n".join(lines) if lines else f"Work on {matter}"

        # Chunk into groups of ≤4
        chunks = [episodes[i:i + _CHUNK_SIZE] for i in range(0, len(episodes), _CHUNK_SIZE)]
        chunk_summaries: list[str] = []
        for chunk in chunks:
            summary = backend.summarize_episode_group(matter, chunk)
            if summary:
                chunk_summaries.append(summary)

        if not chunk_summaries:
            return f"Work on {matter}"

        if len(chunk_summaries) == 1:
            return chunk_summaries[0]

        # Merge chunk summaries into a single matter summary
        merged_episodes = [{"case_name": matter, "key_observations": [{"text": s}]} for s in chunk_summaries]
        return backend.summarize_episode_group(matter, merged_episodes) or "\n\n".join(chunk_summaries)

    def _compose_narrative(
        self, backend, matter_summaries: list[dict], period_start: str, period_end: str
    ) -> str:
        """Compose the weekly narrative from all matter summaries."""
        if not matter_summaries:
            return "No billable work recorded for this period."

        if not backend.is_available():
            # Fallback: concatenate matter summaries
            parts = []
            for ms in matter_summaries:
                parts.append(f"**{ms['matter']}**\n{ms['summary']}")
            return "\n\n".join(parts)

        return backend.compose_weekly_narrative(matter_summaries, period_start, period_end) or \
               "\n\n".join(
                   f"**{ms['matter']}**\n{ms['summary']}" for ms in matter_summaries if ms["summary"]
               )

    def _format_totals(self, matter_summaries: list[dict]) -> str:
        """
        Format time totals. All arithmetic is done in Python — LLM never
        generates time numbers. This is a hard invariant.
        """
        if not matter_summaries:
            return "Total: 0.0 hours"

        lines = ["Time by matter:"]
        grand_total = 0.0
        for ms in sorted(matter_summaries, key=lambda x: x["duration_minutes"], reverse=True):
            hours = ms["duration_minutes"] / 60.0
            grand_total += hours
            lines.append(f"  {ms['matter']}: {hours:.2f} h ({ms['episode_count']} session(s))")
        lines.append(f"Total: {grand_total:.2f} h")
        return "\n".join(lines)

    def _query_episodes(self, period_start: str, period_end: str) -> list[dict]:
        """
        Query episodes from the date range.
        Only returns reportable episodes (is_reportable=1).
        """
        rows = self._conn.execute(
            """
            SELECT id, case_name, issue_worked_on, work_type, started_at, ended_at,
                   duration_minutes, active_seconds, key_observations,
                   activity_classification, classification_confidence
            FROM episodes
            WHERE is_reportable = 1
              AND started_at >= ?
              AND started_at <= ?
            ORDER BY started_at ASC
            """,
            (period_start, period_end),
        ).fetchall()

        episodes = []
        for r in rows:
            obs = json.loads(r[8]) if r[8] else []
            episodes.append({
                "id": r[0],
                "case_name": r[1],
                "issue_worked_on": r[2],
                "work_type": r[3],
                "started_at": r[4],
                "ended_at": r[5],
                "duration_minutes": r[6],
                "active_seconds": r[7],
                "key_observations": obs,
                "activity_classification": r[9],
                "classification_confidence": r[10],
            })
        return episodes

    def _save_report(
        self,
        report_id: str,
        period_start: str,
        period_end: str,
        content: str,
        source_episode_ids: list[str],
    ) -> str:
        """
        Save a generated report to disk and record in SQLite.
        Returns the local file path.
        """
        # Ensure weekly_reports table exists
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS weekly_reports (
                id                 TEXT PRIMARY KEY,
                period_start       TEXT NOT NULL,
                period_end         TEXT NOT NULL,
                generated_at       TEXT NOT NULL,
                content            TEXT NOT NULL,
                source_episode_ids TEXT NOT NULL DEFAULT '[]',
                export_path        TEXT
            )
        """)

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        file_path = self._reports_dir / f"report_{period_start[:10]}_{period_end[:10]}.txt"
        file_path.write_text(content, encoding="utf-8")

        self._conn.execute(
            """
            INSERT INTO weekly_reports
                (id, period_start, period_end, generated_at, content, source_episode_ids, export_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id, period_start, period_end, now,
                content, json.dumps(source_episode_ids), str(file_path),
            ),
        )
        self._conn.commit()
        log.info("weekly_report.saved", report_id=report_id, path=str(file_path))
        return str(file_path)


# ── Module-level helpers ───────────────────────────────────────────────────────

def _assemble_report(
    period_start: str,
    period_end: str,
    narrative: str,
    totals: str,
    matter_summaries: list[dict],
) -> str:
    """
    Assemble the final plain-text report from its components.

    Structure:
      Header (period)
      Narrative (LLM-generated prose, no time numbers)
      Time totals (Python-computed — never LLM-generated)
    """
    lines = [
        f"BuildHarvey Weekly Report",
        f"Period: {period_start[:10]} to {period_end[:10]}",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
        "",
        "─" * 60,
        "",
    ]
    if narrative:
        lines.append(narrative)
        lines.append("")
    lines.append("─" * 60)
    lines.append("")
    lines.append(totals)
    return "\n".join(lines)
