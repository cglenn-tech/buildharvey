"""
Episode data model.

An Episode represents exactly one work subject.
case_name is authoritative when task_context.is_set; otherwise set by Claude.

Lifecycle:
  1. Episode opens when the user provides case context (authoritative) or
     Claude returns a valid suggested_episode_name (unattended mode).
  2. ScreenshotEvidence accumulates in _evidence (primary).
  3. RawObservations accumulate in _raw_observations (context tracking only).
  4. Episode pauses after 5 min of inactivity; resumes on new meaningful activity.
  5. Episode closes on user request, switch confirmation, or 8-h safety net.
  6. The finalizer synthesizes _evidence → key_observations.
  7. The finalized Episode is persisted and synced.

Episodes are structured memory for the report generator.
They are not reports. They are not displayed to users as-is.
"""
import calendar
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── Screenshot evidence (in-memory, per accepted screenshot) ──────────────────

@dataclass
class ScreenshotEvidence:
    """
    Result of a single screenshot analyzed by Claude Vision.
    This is the primary semantic evidence for Episode naming and report generation.
    Raw OCR / NER / titles never become ScreenshotEvidence.
    """
    screenshot_path: str
    timestamp: str                  # HH:MM
    activity_description: str
    objective: str
    actions: list[str]
    entities: list[dict]            # [{name, type, evidence_strength}]
    supporting_evidence: list[str]
    app_context: str                # "Safari | vercel.com"
    model: str
    input_tokens: int
    output_tokens: int
    # Episode boundary signals from Claude
    continue_current_episode: bool = True
    start_new_episode: bool = False
    suggested_episode_name: str = ""


# ── Raw observation (in-memory buffer, never persisted) ───────────────────────

@dataclass
class RawObservation:
    """
    Lightweight context snapshot — metadata only.
    Used only for finalizer fallback when no ScreenshotEvidence exists.
    Never used for Episode naming or boundary decisions.
    """
    timestamp: str      # HH:MM
    app: str
    window_title: str
    browser_url: str
    file_path: str
    entities: list[str]
    screenshot_path: Optional[str] = None


# ── Finalized observation (persisted and sent to LLM) ─────────────────────────

@dataclass
class KeyObservation:
    timestamp: str  # HH:MM
    text: str       # "Reviewed appraisal report"

    def to_dict(self) -> dict:
        return {"timestamp": self.timestamp, "text": self.text}


# ── Episode ───────────────────────────────────────────────────────────────────

@dataclass
class Episode:
    id: str
    case_name: str
    started_at: str
    ended_at: Optional[str]
    created_at: str = field(default_factory=_iso_now)

    # User-provided context (authoritative when set)
    issue_worked_on: Optional[str] = None
    work_type: str = 'project'

    # Finalized — set by finalizer.finalize() after close()
    key_observations: list[KeyObservation] = field(default_factory=list)

    # Primary semantic evidence — what the finalizer uses
    _evidence: list[ScreenshotEvidence] = field(default_factory=list)

    # Metadata context buffer — fallback only, no semantic weight
    _raw_observations: list[RawObservation] = field(default_factory=list)

    # Runtime tracking — not persisted
    last_user_activity_at: float = field(default_factory=time.time)
    last_meaningful_evidence_at: float = field(default_factory=time.time)
    _objective: str = ""

    # Evidence screenshot paths that survived finalization (to be uploaded)
    evidence_paths: list[str] = field(default_factory=list)

    # Legacy field kept for compatibility
    entity_counts: dict[str, int] = field(default_factory=dict)

    # Pause tracking — runtime only, not persisted
    _total_paused_seconds: float = 0.0
    _pause_started_at: Optional[float] = None
    _is_paused: bool = False

    @property
    def last_activity_at(self) -> float:
        """Alias for last_user_activity_at."""
        return self.last_user_activity_at

    @property
    def duration_minutes(self) -> float:
        end_str = self.ended_at or _iso_now()
        try:
            start = time.mktime(time.strptime(self.started_at, "%Y-%m-%dT%H:%M:%SZ"))
            end = time.mktime(time.strptime(end_str, "%Y-%m-%dT%H:%M:%SZ"))
            return round((end - start) / 60, 2)
        except Exception:
            return 0.0

    @property
    def active_seconds(self) -> float:
        """
        Elapsed wall-clock seconds minus any time spent paused.
        Always >= 0.
        """
        try:
            start = calendar.timegm(time.strptime(self.started_at, "%Y-%m-%dT%H:%M:%SZ"))
            end = (
                calendar.timegm(time.strptime(self.ended_at, "%Y-%m-%dT%H:%M:%SZ"))
                if self.ended_at else time.time()
            )
            elapsed = max(0.0, end - start)
            paused = self._total_paused_seconds
            if self._is_paused and self._pause_started_at is not None:
                paused += time.time() - self._pause_started_at
            return max(0.0, elapsed - paused)
        except Exception:
            return 0.0

    def pause_timing(self) -> None:
        """
        Record the start of a pause.
        Called when idle threshold is reached. No-op if already paused.
        """
        if not self._is_paused:
            self._pause_started_at = time.time()
            self._is_paused = True

    def resume_timing(self) -> None:
        """
        Accumulate the paused duration and mark as active.
        Called when new meaningful activity arrives after a pause.
        No-op if not currently paused.
        """
        if self._is_paused and self._pause_started_at is not None:
            self._total_paused_seconds += time.time() - self._pause_started_at
            self._pause_started_at = None
            self._is_paused = False

    def add_raw_observation(self, obs) -> None:
        """
        Buffer a raw metadata observation.
        Updates last_user_activity_at and adds to _raw_observations for fallback use.
        Never affects case_name, _objective, or _evidence.
        """
        self._raw_observations.append(RawObservation(
            timestamp=time.strftime("%H:%M"),
            app=obs.app,
            window_title=obs.window_title,
            browser_url=obs.browser_url,
            file_path=obs.file_path,
            entities=list(obs.entities or []),
            screenshot_path=getattr(obs, "screenshot_path", None),
        ))
        self.last_user_activity_at = time.time()

    def add_observation(self, obs) -> None:
        """Compatibility shim — delegates to add_raw_observation."""
        self.add_raw_observation(obs)

    def close(self) -> None:
        if self._is_paused:
            self.resume_timing()
        self.ended_at = _iso_now()

    def to_dict(self) -> dict:
        """
        Canonical representation sent to Supabase and consumed by the report generator.
        Contains only finalized key observations — no raw data, no images.
        evidence_paths is included for the sync worker to upload screenshots;
        it is not stored in Supabase episodes table.
        """
        return {
            "id": self.id,
            "case_name": self.case_name,
            "issue_worked_on": self.issue_worked_on,
            "work_type": self.work_type,
            "started_at": self.started_at,
            "ended_at": self.ended_at or _iso_now(),
            "duration_minutes": self.duration_minutes,
            "active_seconds": round(self.active_seconds, 1),
            "key_observations": [o.to_dict() for o in self.key_observations],
            "created_at": self.created_at,
            "evidence_paths": list(self.evidence_paths),
        }


# ── Factory ───────────────────────────────────────────────────────────────────

def new_episode(
    case_name: str,
    issue_worked_on: Optional[str] = None,
    work_type: str = 'project',
) -> Episode:
    """
    Create a new Episode.

    In authoritative mode (user provided case context), case_name and issue_worked_on
    come from task_context. In unattended mode, case_name comes from Claude's
    suggested_episode_name and issue_worked_on is None.
    """
    return Episode(
        id=str(uuid.uuid4()),
        case_name=case_name,
        issue_worked_on=issue_worked_on,
        work_type=work_type,
        started_at=_iso_now(),
        ended_at=None,
    )
