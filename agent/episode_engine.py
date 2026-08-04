"""
Episode Engine — passive auto-grouping state machine.

State machine:
  IDLE → ACTIVE → TRANSITIONING → ACTIVE (or IDLE on safety net / force close)

Rules:
  - Claude's suggested_episode_name always drives episode naming.
  - Inactivity > 5 min → pause timing (episode stays open).
  - Inactivity > 8 h → close episode (safety net).
  - 2-signal hysteresis: first start_new_episode → transitioning state.
    Second consecutive start_new_episode → auto-close current and open new.
    Any continue_current_episode while transitioning → snap back to active.
"""
import calendar
import time
from dataclasses import dataclass, field
from typing import Literal, Optional

import config
from episode import Episode, ScreenshotEvidence, new_episode
from observer import Observation


@dataclass
class EngineResult:
    active_episode: Optional[Episode]
    closed_episode: Optional[Episode] = None


class EpisodeEngine:
    def __init__(self) -> None:
        self.active: Optional[Episode] = None
        self._state: Literal["idle", "active", "transitioning"] = "idle"

        # 2-signal hysteresis fields
        self._consecutive_new_episode: int = 0
        self._candidate_name: str = ""

        # In-memory metadata context (app/URL/window) — never persisted
        self._current_app: str = ""
        self._current_url: str = ""
        self._current_window: str = ""

    # ── Public API ─────────────────────────────────────────────────────────────

    def ingest_vision(
        self, evidence: Optional[ScreenshotEvidence], obs: Observation
    ) -> Optional[EngineResult]:
        """
        Process a Claude vision result.

        evidence=None means the API call failed or the screenshot was rejected —
        retain context, do not change episode state.

        Returns EngineResult (with optional closed_episode) or None.
        """
        if evidence is None:
            return None

        if self._state == "idle":
            return self._open_episode(evidence.suggested_episode_name, evidence)

        if self._state == "transitioning":
            if evidence.start_new_episode:
                # Second consecutive signal → confirmed switch
                return self._close_and_open(self._candidate_name, evidence)
            else:
                # continue_current_episode while transitioning → snap back
                self._state = "active"
                self._consecutive_new_episode = 0
                self._candidate_name = ""
                return self._continue_episode(evidence)

        # state == "active"
        if evidence.continue_current_episode:
            return self._continue_episode(evidence)

        if evidence.start_new_episode:
            return self._handle_transition(evidence)

        # Neither signal set (shouldn't happen after validation, but be safe)
        return self._continue_episode(evidence)

    def ingest_metadata(self, obs: Observation) -> None:
        """
        Process a metadata-only observation (no screenshot or no API key).

        Updates last_user_activity_at on the active episode and tracks current
        app/URL/window context. Never opens or closes an Episode.
        """
        self._current_app = obs.app or ""
        self._current_url = obs.browser_url or ""
        self._current_window = obs.window_title or ""

        if self.active:
            self.active.last_user_activity_at = time.time()
            self.active.add_raw_observation(obs)

    def ingest_metadata_activity_only(self) -> None:
        """Update last_user_activity_at when observe() returns None (no screen change)."""
        if self.active:
            self.active.last_user_activity_at = time.time()

    def get_context(self) -> dict:
        """Return current episode context for the vision prompt."""
        if not self.active:
            return {
                "current_episode_name": "",
                "current_objective": "",
                "episode_duration_minutes": 0,
                "recent_actions": [],
                "known_entities": [],
            }

        recent_actions = [e.actions for e in self.active._evidence[-3:]]
        known = []
        seen: set[str] = set()
        for ev in self.active._evidence:
            for ent in ev.entities:
                name = ent.get("name", "")
                if name and name not in seen:
                    seen.add(name)
                    known.append(name)

        return {
            "current_episode_name": self.active.case_name,
            "current_objective": self.active._objective,
            "episode_duration_minutes": self.active.duration_minutes,
            "recent_actions": recent_actions,
            "known_entities": known,
        }

    def check_inactivity(self, now: float) -> Optional[Episode]:
        """
        Pause timing after INACTIVITY_PAUSE_SECONDS idle.
        Close and return the active episode after MAX_EPISODE_SECONDS (safety net).
        Returns the closed episode or None.
        """
        if not self.active:
            return None

        idle = now - self.active.last_user_activity_at
        elapsed = now - calendar.timegm(
            time.strptime(self.active.started_at, "%Y-%m-%dT%H:%M:%SZ")
        )

        # Safety net: 8 h total elapsed → force close
        if elapsed > config.MAX_EPISODE_SECONDS:
            return self._force_close(reason=f"8-h safety net [{elapsed:.0f}s elapsed]")

        # Pause after 5 min idle (episode stays open)
        if idle > config.INACTIVITY_PAUSE_SECONDS and not self.active._is_paused:
            self.active.pause_timing()
            print(
                f"[engine] timing paused: '{self.active.case_name}' "
                f"[idle {idle:.0f}s]"
            )

        return None

    def force_close_active(self) -> Optional[Episode]:
        """
        Immediately close and return the active episode on explicit web Stop signal.
        """
        if not self.active:
            return None
        return self._force_close(reason="user stop")

    # ── Private helpers ────────────────────────────────────────────────────────

    def _open_episode(
        self, suggested_name: str, evidence: ScreenshotEvidence
    ) -> EngineResult:
        ep = new_episode(suggested_name, issue_worked_on=None, work_type="project")
        ep._objective = evidence.objective
        ep._evidence.append(evidence)
        ep.last_meaningful_evidence_at = time.time()

        # Resume timing in case this was opened after a pause
        ep.resume_timing()

        self.active = ep
        self._state = "active"
        self._consecutive_new_episode = 0
        self._candidate_name = ""
        print(f"[engine] episode opened: {ep.case_name}")
        return EngineResult(active_episode=ep)

    def _continue_episode(self, evidence: ScreenshotEvidence) -> EngineResult:
        ep = self.active
        ep._evidence.append(evidence)
        ep.last_user_activity_at = time.time()
        ep.last_meaningful_evidence_at = time.time()

        # Resume timing if we were paused
        if ep._is_paused:
            ep.resume_timing()
            print(f"[engine] timing resumed: {ep.case_name}")

        # Allow Claude to refine the name toward something more specific
        if (
            evidence.suggested_episode_name
            and evidence.suggested_episode_name != ep.case_name
            and len(evidence.suggested_episode_name) > len(ep.case_name)
        ):
            old_name = ep.case_name
            ep.case_name = evidence.suggested_episode_name
            ep._objective = evidence.objective
            print(f"[engine] episode name updated: '{old_name}' → '{ep.case_name}'")
        elif evidence.objective and not ep._objective:
            ep._objective = evidence.objective

        print(f"[engine] episode continued: {ep.case_name}")
        return EngineResult(active_episode=ep)

    def _handle_transition(self, evidence: ScreenshotEvidence) -> EngineResult:
        """
        First start_new_episode signal → move to transitioning state.
        Store the candidate name and wait for confirmation on the next cycle.
        """
        self._candidate_name = evidence.suggested_episode_name
        self._consecutive_new_episode = 1
        self._state = "transitioning"
        print(
            f"[engine] transitioning: candidate '{self._candidate_name}' "
            f"(current: '{self.active.case_name}')"
        )
        return EngineResult(active_episode=self.active)

    def _close_and_open(self, name: str, evidence: ScreenshotEvidence) -> EngineResult:
        """Auto-close current and open new episode (passive mode, 2-signal confirmed)."""
        closed = self.active
        closed.close()
        self._state = "idle"
        self.active = None
        self._consecutive_new_episode = 0
        self._candidate_name = ""
        result = self._open_episode(name, evidence)
        result.closed_episode = closed
        return result

    def _force_close(self, reason: str = "") -> Episode:
        ep = self.active
        ep.close()
        self.active = None
        self._state = "idle"
        self._consecutive_new_episode = 0
        self._candidate_name = ""
        print(
            f"[engine] episode finalized: '{ep.case_name}' "
            f"({ep.duration_minutes:.0f}min, {len(ep._evidence)} evidence items)"
            + (f" [{reason}]" if reason else "")
        )
        return ep


def _has_strong_entity_shift(evidence: ScreenshotEvidence, current: Optional[Episode]) -> bool:
    """
    Returns True if evidence contains a strong-confidence entity that is
    clearly different from all entities seen in the current episode.
    Only fires on evidence_strength='strong' — moderate/weak don't split episodes.
    """
    if not current or not current._evidence:
        return False

    strong_new = {
        e["name"].lower()
        for e in evidence.entities
        if e.get("evidence_strength") == "strong"
    }
    if not strong_new:
        return False

    known = {
        e["name"].lower()
        for ev in current._evidence
        for e in ev.entities
    }
    # Shift only if ALL strong new entities are absent from known entities
    return bool(strong_new) and strong_new.isdisjoint(known)
