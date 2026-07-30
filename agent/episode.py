"""
Episode data model.

An Episode represents exactly one case (work subject).
case_name is the primary identifier.

Lifecycle:
  1. Episode opens when a case name is first detected.
  2. Observations accumulate in a raw buffer (in memory only).
  3. Episode closes when the case name changes or inactivity fires.
  4. The finalizer processes the buffer → key_observations.
  5. The finalized Episode is persisted and synced.

Episodes are structured memory for the report generator.
They are not reports. They are not displayed to users as-is.
"""
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── Raw observation (in-memory buffer, never persisted) ───────────────────────

@dataclass
class RawObservation:
    """Lightweight context snapshot accumulated while an episode is open."""
    timestamp: str      # HH:MM
    app: str
    window_title: str
    browser_url: str
    file_path: str
    entities: list[str]


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

    # Finalized — set by finalizer.finalize() after close()
    key_observations: list[KeyObservation] = field(default_factory=list)

    # In-memory buffer — cleared after finalization
    _raw_observations: list[RawObservation] = field(default_factory=list)

    # Runtime — not persisted
    last_activity_at: float = field(default_factory=time.time)
    entity_counts: dict[str, int] = field(default_factory=dict)

    @property
    def duration_minutes(self) -> float:
        end_str = self.ended_at or _iso_now()
        try:
            start = time.mktime(time.strptime(self.started_at, "%Y-%m-%dT%H:%M:%SZ"))
            end = time.mktime(time.strptime(end_str, "%Y-%m-%dT%H:%M:%SZ"))
            return round((end - start) / 60, 2)
        except Exception:
            return 0.0

    def add_observation(self, obs) -> None:
        """
        Buffer one Observation for later finalization.
        Updates entity tracking and last-activity time.
        Only the primary entity (entities[0]) is counted — tracking all entities
        caused background tabs to contaminate entity_counts and prevent episode closes.
        """
        if obs.entities:
            primary = obs.entities[0]
            self.entity_counts[primary] = self.entity_counts.get(primary, 0) + 1

        self._raw_observations.append(RawObservation(
            timestamp=time.strftime("%H:%M"),
            app=obs.app,
            window_title=obs.window_title,
            browser_url=obs.browser_url,
            file_path=obs.file_path,
            entities=list(obs.entities or []),
        ))
        self.last_activity_at = time.time()

    def close(self) -> None:
        self.ended_at = _iso_now()

    def to_dict(self) -> dict:
        """
        Canonical representation sent to Supabase and consumed by the report generator.
        Contains only finalized key observations — no raw data, no images.
        """
        return {
            "id": self.id,
            "case_name": self.case_name,
            "started_at": self.started_at,
            "ended_at": self.ended_at or _iso_now(),
            "duration_minutes": self.duration_minutes,
            "key_observations": [o.to_dict() for o in self.key_observations],
            "created_at": self.created_at,
        }


# ── Factory ───────────────────────────────────────────────────────────────────

def new_episode(case_name: str) -> Episode:
    return Episode(
        id=str(uuid.uuid4()),
        case_name=case_name or "Administrative",
        started_at=_iso_now(),
        ended_at=None,
    )
