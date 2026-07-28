"""
Episode Engine — all episode reasoning lives here.
Consumes Observations. Decides boundaries. Produces Episodes.
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
    closed_episode: Optional[Episode] = None  # set when a context shift occurred


class EpisodeEngine:
    def __init__(self) -> None:
        self.active: Optional[Episode] = None

    def ingest(self, obs: Observation, now: float) -> EngineResult:
        """
        Process one Observation. Decide whether to continue the current episode
        or close it and open a new one.
        Returns the episode the observation should be attached to,
        and the episode that was closed (if any).
        """
        if self.active is None:
            self.active = new_episode(
                title=_derive_title(obs),
                app_name=obs.app,
                window_title=obs.window_title,
            )
            print(f"[engine] opened  '{self.active.title}'")
            return EngineResult(active_episode=self.active)

        if self._should_close(obs, now):
            closed = self.active
            closed.close()
            self.active = new_episode(
                title=_derive_title(obs),
                app_name=obs.app,
                window_title=obs.window_title,
            )
            print(f"[engine] closed  '{closed.title}'")
            print(f"[engine] opened  '{self.active.title}'")
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
            print(f"[engine] idle {idle:.0f}s → closed '{ep.title}'")
            return ep
        return None

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _should_close(self, obs: Observation, now: float) -> bool:
        ep = self.active
        score = 0.0

        # Hard rule: inactivity (belt-and-suspenders; check_inactivity runs separately)
        if now - ep.last_activity_at > config.INACTIVITY_TIMEOUT_SECONDS:
            return True

        ep_entities = set(ep.entity_counts.keys())
        obs_entities = set(obs.entities or [])

        # Signal 1 — entity continuity (primary, weight 0.50)
        # If both frames have named entities, entity overlap is decisive.
        if ep_entities and obs_entities:
            if ep_entities & obs_entities:
                # Same work entity detected → keep episode alive regardless of app/window
                return False
            else:
                # Entities present but no overlap → strong context shift signal
                score += 0.50

        # Signal 2 — application changed (weight 0.30)
        if ep.dominant_app and obs.app and obs.app != ep.dominant_app:
            score += 0.30

        # Signal 3 — window title dissimilar (weight 0.20)
        if obs.window_title and ep.recent_window_titles:
            recent = _word_set(" ".join(ep.recent_window_titles[-5:]))
            current = _word_set(obs.window_title)
            if _jaccard(recent, current) < 0.15:
                score += 0.20

        # Signal 4 — OCR content dissimilar (weight 0.10)
        if obs.extracted_text and ep.recent_ocr_texts:
            recent = _word_set(" ".join(ep.recent_ocr_texts[-3:]))
            current = _word_set(obs.extracted_text)
            if _jaccard(recent, current) < 0.10:
                score += 0.10

        if score >= config.CONTEXT_SHIFT_THRESHOLD:
            print(f"[engine] context shift score={score:.2f} ep_ents={len(ep_entities)} obs_ents={len(obs_entities)}")
            return True

        return False


# ── Helpers ────────────────────────────────────────────────────────────────────

_STRIP_SUFFIXES = [
    " - Microsoft Excel", " - Microsoft Word", " - Microsoft PowerPoint",
    " — Safari", " - Google Chrome", " — Chrome", " - Firefox",
    " - Preview", " - TextEdit", " - Pages", " - Numbers", " - Keynote",
]

_STRIP_EXTENSIONS = [".xlsx", ".xls", ".docx", ".doc", ".pdf", ".pptx",
                     ".pages", ".numbers", ".txt", ".md"]


def _derive_title(obs: Observation) -> str:
    """Derive a human-readable episode title from observation context."""
    # Entities — most specific signal (regex IDs > NER names)
    if obs.entities:
        return obs.entities[0]

    # File path → filename without extension
    if obs.file_path:
        from pathlib import Path
        stem = Path(obs.file_path).stem
        if len(stem) > 2:
            return stem

    # Window title cleaned
    title = obs.window_title
    for suffix in _STRIP_SUFFIXES:
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
            break
    for ext in _STRIP_EXTENSIONS:
        if title.lower().endswith(ext):
            title = title[: -len(ext)].strip()
            break
    if len(title) > 2:
        return title

    # Browser domain
    if obs.browser_url:
        try:
            from urllib.parse import urlparse
            domain = urlparse(obs.browser_url).netloc.removeprefix("www.")
            if domain:
                return domain
        except Exception:
            pass

    # App name + timestamp
    ts = time.strftime("%b %d, %I:%M %p")
    return f"{obs.app} – {ts}" if obs.app else f"Session – {ts}"


def _word_set(text: str) -> set[str]:
    return {w.lower() for w in text.split() if len(w) >= 4}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
