"""
Episode Engine — hybrid task control state machine.

State machine:
  IDLE → ACTIVE → SWITCH_SUGGESTION → ACTIVE (or IDLE on safety net / force close)

Rules:
  - When user has set authoritative context: episode name/issue come from task_context,
    never from Claude's suggested_episode_name.
  - In unattended mode (no user context): Claude's suggested_episode_name is used.
  - Inactivity > 5 min → pause timing (episode stays open).
  - Inactivity > 8 h → close episode (safety net).
  - Switch suggestion: held as pending — user must confirm or reject.
  - confirm_switch(): close current, open new with pending evidence.
  - reject_switch(): append pending evidence to current, clear suggestion.
"""
import calendar
import time
from dataclasses import dataclass, field
from typing import Literal, Optional

import config
import task_context as tc
from episode import Episode, ScreenshotEvidence, new_episode
from observer import Observation


@dataclass
class EngineResult:
    active_episode: Optional[Episode]
    closed_episode: Optional[Episode] = None


class EpisodeEngine:
    def __init__(self) -> None:
        self.active: Optional[Episode] = None
        self._state: Literal["idle", "active", "switch_suggestion"] = "idle"

        # Authoritative context from the user (set via set_authoritative_context)
        self._authoritative_case: str = ""
        self._authoritative_issue: Optional[str] = None
        self._authoritative_work_type: str = "project"

        # Evidence held during a switch suggestion (never attached to wrong episode)
        self._pending_evidence: list[ScreenshotEvidence] = []
        self._pending_new_name: str = ""

        # In-memory metadata context (app/URL/window) — never persisted
        self._current_app: str = ""
        self._current_url: str = ""
        self._current_window: str = ""

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_authoritative_context(
        self,
        case_name: str,
        issue_worked_on: Optional[str],
        work_type: str,
    ) -> None:
        """
        Called by main.py each cycle when task_context.is_set is True.
        Sets the authoritative values used by _open_episode() and _continue_episode().
        Does NOT immediately change an active episode's name — that only happens
        on the next open or explicit update.
        """
        self._authoritative_case = case_name
        self._authoritative_issue = issue_worked_on
        self._authoritative_work_type = work_type

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

        if self._state == "switch_suggestion":
            # Hold all evidence pending user decision
            self._pending_evidence.append(evidence)
            print(
                f"[engine] holding evidence in pending "
                f"({len(self._pending_evidence)} items) — awaiting switch decision"
            )
            return EngineResult(active_episode=self.active)

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
            tc.set_timing_paused(True)
            print(
                f"[engine] timing paused: '{self.active.case_name}' "
                f"[idle {idle:.0f}s]"
            )

        return None

    def confirm_switch(self, new_name: str = "") -> Optional[EngineResult]:
        """
        User confirmed the switch suggestion.
        Closes the current episode, opens a new one with pending evidence attached.

        new_name="" → use the pending candidate name (or authoritative context).
        new_name="Smith v. Jones" → use that specific name.
        """
        if self._state != "switch_suggestion" or not self.active:
            return None

        # Determine the name for the new episode
        candidate = new_name or self._pending_new_name
        if self._authoritative_case:
            # If user has authoritative context, switch means a new authoritative context
            # (the app should have updated task_context before calling confirm_switch)
            ctx = tc.get_context()
            if ctx.is_set:
                open_name = ctx.case_name
                open_issue = ctx.issue_worked_on or None
                open_work_type = ctx.work_type
            else:
                open_name = candidate
                open_issue = None
                open_work_type = "project"
        else:
            open_name = candidate
            open_issue = None
            open_work_type = "project"

        # Close current episode
        closed = self.active
        closed.close()
        print(
            f"[engine] switch confirmed — closing: '{closed.case_name}' "
            f"({closed.duration_minutes:.0f}min)"
        )

        # Open new episode
        ep = new_episode(open_name, issue_worked_on=open_issue, work_type=open_work_type)
        ep._objective = ""

        # Attach pending evidence to the new episode
        for ev in self._pending_evidence:
            ep._evidence.append(ev)
            ep.last_meaningful_evidence_at = time.time()
        self._pending_evidence = []

        self.active = ep
        self._state = "active"
        self._pending_new_name = ""
        tc.clear_switch_suggestion()
        tc.set_timing_paused(False)
        print(f"[engine] episode opened: {ep.case_name}")
        return EngineResult(active_episode=ep, closed_episode=closed)

    def reject_switch(self) -> Optional[EngineResult]:
        """
        User rejected the switch suggestion.
        Appends pending evidence to the current episode and clears the suggestion.
        """
        if self._state != "switch_suggestion" or not self.active:
            return None

        ep = self.active
        for ev in self._pending_evidence:
            ep._evidence.append(ev)
            ep.last_user_activity_at = time.time()
            ep.last_meaningful_evidence_at = time.time()

        count = len(self._pending_evidence)
        self._pending_evidence = []
        self._state = "active"
        self._pending_new_name = ""
        tc.clear_switch_suggestion()
        print(
            f"[engine] switch rejected — continuing: '{ep.case_name}' "
            f"({count} pending evidence items merged)"
        )
        return EngineResult(active_episode=ep)

    def force_close_active(self) -> Optional[Episode]:
        """
        Immediately close and return the active episode on explicit user Stop.
        Pending evidence (if any) is merged into current episode before closing.
        """
        if not self.active:
            return None

        # Merge any pending evidence into current episode before closing
        for ev in self._pending_evidence:
            self.active._evidence.append(ev)
        self._pending_evidence = []

        return self._force_close(reason="user stop")

    # ── Private helpers ────────────────────────────────────────────────────────

    def _open_episode(
        self, suggested_name: str, evidence: ScreenshotEvidence
    ) -> EngineResult:
        # Use authoritative context when set; fall back to Claude's suggestion
        if self._authoritative_case:
            name = self._authoritative_case
            issue = self._authoritative_issue
            work_type = self._authoritative_work_type
        else:
            name = suggested_name
            issue = None
            work_type = "project"

        ep = new_episode(name, issue_worked_on=issue, work_type=work_type)
        ep._objective = evidence.objective
        ep._evidence.append(evidence)
        ep.last_meaningful_evidence_at = time.time()

        # Resume timing in case this was opened after a pause (e.g. new session)
        ep.resume_timing()
        tc.set_timing_paused(False)

        self.active = ep
        self._state = "active"
        self._pending_new_name = ""
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
            tc.set_timing_paused(False)
            print(f"[engine] timing resumed: {ep.case_name}")

        # Update name/objective only in unattended mode (no authoritative case)
        if not self._authoritative_case:
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
        else:
            # Authoritative mode: update objective only, never case_name
            if evidence.objective and not ep._objective:
                ep._objective = evidence.objective

        print(f"[engine] episode continued: {ep.case_name}")
        return EngineResult(active_episode=ep)

    def _handle_transition(self, evidence: ScreenshotEvidence) -> EngineResult:
        """
        Handle a start_new_episode signal.
        Instead of auto-closing (old behavior), set a switch suggestion and
        hold the evidence in _pending_evidence.
        """
        candidate = evidence.suggested_episode_name
        self._pending_new_name = candidate
        self._pending_evidence.append(evidence)
        self._state = "switch_suggestion"
        tc.set_switch_suggestion(candidate)
        print(
            f"[engine] switch suggestion: '{candidate}' "
            f"(current: '{self.active.case_name}')"
        )
        return EngineResult(active_episode=self.active)

    def _force_close(self, reason: str = "") -> Episode:
        ep = self.active
        ep.close()
        self.active = None
        self._state = "idle"
        self._pending_evidence = []
        self._pending_new_name = ""
        tc.clear_switch_suggestion()
        tc.set_timing_paused(False)
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
