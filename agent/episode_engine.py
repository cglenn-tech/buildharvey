"""
Episode Engine — Claude-first state machine.

State machine:
  IDLE → ACTIVE → TRANSITIONING → ACTIVE (or IDLE on inactivity)

Rules:
  - Only Claude can open or close an Episode (via ingest_vision).
  - ingest_metadata() tracks context only — never changes Episode state.
  - Hysteresis: two consecutive start_new_episode signals required (or strong
    entity shift) before closing — prevents tab switches from splitting episodes.
  - Inactivity > 10 min closes any active episode.
"""
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
        self._pending_transition_count: int = 0   # consecutive start_new signals
        self._pending_new_name: str = ""           # candidate new Episode name
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
            # API failure or non-meaningful/personal — no state change
            return None

        if self._state == "idle":
            return self._open_episode(evidence.suggested_episode_name, evidence)

        # active or transitioning
        if evidence.continue_current_episode:
            if self._state == "transitioning":
                # Hysteresis: revert to active — single start_new was a blip
                self._state = "active"
                self._pending_transition_count = 0
                self._pending_new_name = ""
                print(f"[engine] transition cancelled — continuing: {self.active.case_name}")
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
        """Close and return the active episode if idle too long."""
        if not self.active:
            return None
        idle = now - self.active.last_user_activity_at
        if idle > config.INACTIVITY_TIMEOUT_SECONDS:
            ep = self.active
            ep.close()
            self.active = None
            self._state = "idle"
            self._pending_transition_count = 0
            self._pending_new_name = ""
            print(
                f"[engine] episode finalized: '{ep.case_name}' "
                f"({ep.duration_minutes:.0f}min, {len(ep._evidence)} evidence items) "
                f"[idle {idle:.0f}s]"
            )
            return ep
        return None

    # ── Private helpers ────────────────────────────────────────────────────────

    def _open_episode(
        self, name: str, evidence: ScreenshotEvidence
    ) -> EngineResult:
        ep = new_episode(name)
        ep._objective = evidence.objective
        ep._evidence.append(evidence)
        ep.last_meaningful_evidence_at = time.time()
        self.active = ep
        self._state = "active"
        self._pending_transition_count = 0
        self._pending_new_name = ""
        print(f"[engine] episode opened: {ep.case_name}")
        return EngineResult(active_episode=ep)

    def _continue_episode(self, evidence: ScreenshotEvidence) -> EngineResult:
        ep = self.active
        ep._evidence.append(evidence)
        ep.last_user_activity_at = time.time()
        ep.last_meaningful_evidence_at = time.time()

        # Update name/objective if Claude provides something more specific
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
        self._pending_transition_count += 1
        self._pending_new_name = evidence.suggested_episode_name
        print(
            f"[engine] transition pending ({self._pending_transition_count}/2): "
            f"{self._pending_new_name}"
        )

        if self._pending_transition_count >= 2:
            return self._finalize_and_open(evidence)

        # Check for strong entity shift — immediately transition on unmistakable change
        if _has_strong_entity_shift(evidence, self.active):
            print(f"[engine] strong entity shift detected — transitioning immediately")
            return self._finalize_and_open(evidence)

        self._state = "transitioning"
        return EngineResult(active_episode=self.active)

    def _finalize_and_open(self, evidence: ScreenshotEvidence) -> EngineResult:
        closed = self.active
        closed.close()
        print(
            f"[engine] episode finalized: '{closed.case_name}' "
            f"({closed.duration_minutes:.0f}min, {len(closed._evidence)} evidence items)"
        )

        ep = new_episode(evidence.suggested_episode_name)
        ep._objective = evidence.objective
        ep._evidence.append(evidence)
        ep.last_meaningful_evidence_at = time.time()
        self.active = ep
        self._state = "active"
        self._pending_transition_count = 0
        self._pending_new_name = ""
        print(f"[engine] episode opened: {ep.case_name}")
        return EngineResult(active_episode=ep, closed_episode=closed)


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
