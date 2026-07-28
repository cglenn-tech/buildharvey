"""
Episode data model.

This file contains only dataclasses and the canonical to_dict() representation.
No SQLite. No scoring. No sync logic.

Every layer of the system — agent, database, sync worker, web app —
uses the same Episode structure.
"""
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from observer import Observation


@dataclass
class StorylineEntry:
    timestamp: str  # HH:MM
    text: str

    def to_dict(self) -> dict:
        return {"timestamp": self.timestamp, "text": self.text}


@dataclass
class Screenshot:
    id: str
    timestamp: str      # HH:MM
    path: str           # local file path (set immediately)
    storage_url: str    # Supabase Storage URL (filled in by background sync worker)
    extracted_text: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "path": self.path,
            "storageUrl": self.storage_url,
            "extractedText": self.extracted_text,
        }


@dataclass
class Episode:
    id: str
    title: str
    started_at: str
    ended_at: Optional[str]
    summary: str
    storyline: list[StorylineEntry] = field(default_factory=list)
    screenshots: list[Screenshot] = field(default_factory=list)
    created_at: str = field(default_factory=_iso_now)

    # ── Runtime tracking (not persisted to Supabase) ──────────────────────────
    last_activity_at: float = field(default_factory=time.time)
    dominant_app: str = ""
    recent_window_titles: list[str] = field(default_factory=list)
    recent_ocr_texts: list[str] = field(default_factory=list)

    # ── Public interface ──────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """
        Canonical Episode representation.
        Identical shape across agent, SQLite, Supabase, and web app.
        """
        return {
            "id": self.id,
            "title": self.title,
            "started_at": self.started_at,
            "ended_at": self.ended_at or _iso_now(),
            "summary": self.summary,
            "storyline": [e.to_dict() for e in self.storyline],
            "screenshots": [s.to_dict() for s in self.screenshots],
            "created_at": self.created_at,
        }

    def record_observation(self, screenshot_id: str, path: Path, obs: Observation) -> Screenshot:
        """
        Attach one Observation to this episode.
        Creates both a Screenshot record and a Storyline entry.
        storage_url starts empty — the sync worker fills it in after upload.
        """
        ts = time.strftime("%H:%M")

        screenshot = Screenshot(
            id=screenshot_id,
            timestamp=ts,
            path=str(path),
            storage_url="",
            extracted_text=obs.extracted_text,
        )
        self.screenshots.append(screenshot)
        self.storyline.append(StorylineEntry(timestamp=ts, text=_describe(obs)))

        # Update runtime context so the engine can score future observations
        self.last_activity_at = time.time()
        self.dominant_app = obs.app
        if obs.window_title:
            self.recent_window_titles.append(obs.window_title)
        if obs.extracted_text:
            self.recent_ocr_texts.append(obs.extracted_text[:500])

        return screenshot

    def close(self) -> None:
        self.ended_at = _iso_now()
        self.summary = _build_summary(self)


# ── Factory ────────────────────────────────────────────────────────────────────

def new_episode(title: str, app_name: str, window_title: str) -> Episode:
    ep = Episode(
        id=str(uuid.uuid4()),
        title=title,
        started_at=_iso_now(),
        ended_at=None,
        summary="",
        dominant_app=app_name,
    )
    if window_title:
        ep.recent_window_titles.append(window_title)
    return ep


# ── Private helpers ────────────────────────────────────────────────────────────

def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _describe(obs: Observation) -> str:
    """One-line storyline description from the richest available context signal."""
    if obs.browser_url:
        try:
            from urllib.parse import urlparse
            domain = urlparse(obs.browser_url).netloc.removeprefix("www.")
            return f"{obs.app} — {domain}" if domain else obs.app
        except Exception:
            pass
    if obs.file_path:
        filename = Path(obs.file_path).name
        return f"{obs.app} — {filename}" if filename else obs.app
    if obs.window_title and obs.app:
        return f"{obs.app} — {obs.window_title}"
    if obs.window_title:
        return obs.window_title
    if obs.app:
        first_line = next(
            (ln.strip() for ln in obs.extracted_text.splitlines() if len(ln.strip()) > 10),
            "",
        )
        return f"{obs.app}: {first_line[:80]}" if first_line else obs.app
    return "Screen activity detected"


def _build_summary(episode: Episode) -> str:
    """Simple summary built at episode close from storyline entries."""
    seen_apps: list[str] = list(dict.fromkeys(
        e.text.split(" — ")[0].split(":")[0].strip()
        for e in episode.storyline
        if e.text and e.text != "Screen activity detected"
    ))

    try:
        start = time.strptime(episode.started_at, "%Y-%m-%dT%H:%M:%SZ")
        duration_min = round((time.time() - time.mktime(start)) / 60)
    except Exception:
        duration_min = 0

    if not seen_apps:
        return f"Session lasted {duration_min} min." if duration_min else ""

    app_list = ", ".join(seen_apps[:4])
    more = " and more" if len(seen_apps) > 4 else ""
    return f"Worked for {duration_min} min using {app_list}{more}."
