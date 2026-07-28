"""
Observer — collects facts about the screen, produces Observation objects.

Responsibilities:
  - Capture screenshots
  - Detect meaningful screen changes
  - OCR the frame
  - Read active application, window title, browser URL, file path
  - Timestamp everything

The Observer NEVER decides episode boundaries.
It only reports what it saw.
"""
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import capture
import context as ctx_module
import entities as entities_mod
import ocr


@dataclass
class Observation:
    """A single moment of observed screen activity."""
    timestamp: str          # ISO 8601
    screenshot_path: Path   # path to the captured frame (temp location)
    extracted_text: str     # full OCR output
    app: str                # active application name  e.g. "Microsoft Excel"
    window_title: str       # frontmost window title   e.g. "Johnson Holdings Q4.xlsx"
    browser_url: str        # active URL if a browser is frontmost, else ""
    file_path: str          # open document path if available, else ""
    entities: list[str] = None  # named entities and structured IDs extracted from this frame


def observe(prev_frame_path: Optional[Path], temp_path: Path) -> Optional[Observation]:
    """
    Capture the current screen and return an Observation if something meaningful
    has changed since the previous frame.

    Returns None if the screen is static (below diff threshold).
    The caller is responsible for copying the frame from temp_path to a
    permanent location once the target episode is known.
    """
    capture.capture_screen(temp_path)

    if prev_frame_path and not capture.image_changed(prev_frame_path, temp_path):
        return None

    ctx = ctx_module.get_context()
    text = ocr.extract_text(temp_path)
    found_entities = entities_mod.extract(text, ctx.window_title, ctx.file_path)

    return Observation(
        timestamp=_iso_now(),
        screenshot_path=temp_path,
        extracted_text=text,
        app=ctx.app_name,
        window_title=ctx.window_title,
        browser_url=ctx.browser_url,
        file_path=ctx.file_path,
        entities=found_entities,
    )


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
