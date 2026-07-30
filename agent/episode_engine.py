"""
Episode Engine — case-name driven boundaries.

Rule: one Episode = one Case.

An episode closes when:
  1. A new case name appears that is unrelated to the current episode, OR
  2. No case name has been detected for ADMIN_GRACE_SECONDS (→ switch to Administrative), OR
  3. The inactivity timeout fires.
"""
import time
from dataclasses import dataclass
from typing import Optional

import config
from episode import Episode, new_episode
from observer import Observation


@dataclass
class EngineResult:
    active_episode: Episode
    closed_episode: Optional[Episode] = None


class EpisodeEngine:
    def __init__(self) -> None:
        self.active: Optional[Episode] = None
        self._no_entity_streak: int = 0   # consecutive observations with no case entity
        self._pending_case: str = ""      # candidate new case name
        self._pending_streak: int = 0     # how many consecutive times we've seen it

    def ingest(self, obs: Observation, now: float) -> EngineResult:
        case_name = _extract_case_name(obs)

        if case_name:
            self._no_entity_streak = 0
        else:
            self._no_entity_streak += 1

        if self.active is None:
            self._pending_case = ""
            self._pending_streak = 0
            self.active = new_episode(case_name or "Administrative")
            print(f"[engine] opened  '{self.active.case_name}'")
            return EngineResult(active_episode=self.active)

        if self._should_close(obs, now, case_name):
            closed = self.active
            closed.close()
            self._no_entity_streak = 0
            self._pending_case = ""
            self._pending_streak = 0
            self.active = new_episode(case_name or "Administrative")
            print(f"[engine] closed  '{closed.case_name}'")
            print(f"[engine] opened  '{self.active.case_name}'")
            return EngineResult(active_episode=self.active, closed_episode=closed)

        return EngineResult(active_episode=self.active)

    def check_inactivity(self, now: float) -> Optional[Episode]:
        """Close and return the active episode if idle too long."""
        if not self.active:
            return None
        idle = now - self.active.last_activity_at
        if idle > config.INACTIVITY_TIMEOUT_SECONDS:
            ep = self.active
            ep.close()
            self.active = None
            self._no_entity_streak = 0
            self._pending_case = ""
            self._pending_streak = 0
            print(f"[engine] idle {idle:.0f}s → closed '{ep.case_name}'")
            return ep
        return None

    def _should_close(self, obs: Observation, now: float, case_name: str) -> bool:
        ep = self.active

        # Hard rule: inactivity
        if now - ep.last_activity_at > config.INACTIVITY_TIMEOUT_SECONDS:
            return True

        # No case signal — grace period, then switch to Administrative
        if not case_name:
            admin_grace_obs = max(1, config.ADMIN_GRACE_SECONDS // config.CAPTURE_INTERVAL_SECONDS)
            if ep.case_name != "Administrative" and self._no_entity_streak > admin_grace_obs:
                return True
            return False

        # Same case as current episode — reset pending
        if case_name == ep.case_name:
            self._pending_case = ""
            self._pending_streak = 0
            return False

        # Different case — require CASE_SWITCH_THRESHOLD consecutive observations.
        # Brief glances (< threshold) won't close the episode; going back to the
        # current case resets the streak. entity_counts is intentionally not used
        # here — relying on streak alone avoids the "black hole" where every entity
        # ever seen gets absorbed into entity_counts and no close ever fires.
        if case_name == self._pending_case:
            self._pending_streak += 1
        else:
            self._pending_case = case_name
            self._pending_streak = 1

        if self._pending_streak >= config.CASE_SWITCH_THRESHOLD:
            return True

        return False  # not confident enough yet


def _extract_case_name(obs: Observation) -> str:
    """
    Return the primary case name from an observation.
    entities is ordered: structured identifiers first, file stem second, NER last.
    """
    return obs.entities[0] if obs.entities else ""
