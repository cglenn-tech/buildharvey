"""
Observer — captures the screen, extracts facts, produces Observations.

The screen image is a temporary processing artifact.
It is captured, OCR'd, and discarded.
It is never stored, uploaded, or referenced after this module returns.
"""
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import capture
import config
import context as ctx_module
import entities as entities_mod
import ocr


@dataclass
class Observation:
    """Structured facts extracted from one screen capture."""
    timestamp: str          # ISO 8601 UTC
    app: str                # active application, e.g. "Microsoft Excel"
    window_title: str       # frontmost window title
    browser_url: str        # active URL if a browser is frontmost, else ""
    file_path: str          # open document path if available, else ""
    entities: list[str] = field(default_factory=list)  # case names, identifiers


def observe() -> Optional[Observation]:
    """
    Capture the current screen and return an Observation if something meaningful
    has changed since the previous frame.

    Returns None if the screen is static.
    The captured image is discarded after OCR and entity extraction.
    """
    capture.capture_screen(config.TEMP_FRAME_PATH)

    # Compare against the previous baseline frame
    if config.PREV_FRAME_PATH.exists():
        if not capture.image_changed(config.PREV_FRAME_PATH, config.TEMP_FRAME_PATH):
            return None

    ctx = ctx_module.get_context()
    text = ocr.extract_text(config.TEMP_FRAME_PATH)
    found_entities = entities_mod.extract(text, ctx.window_title, ctx.file_path)

    # Save current frame as the new baseline (the only copy we keep)
    shutil.copy2(config.TEMP_FRAME_PATH, config.PREV_FRAME_PATH)

    return Observation(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        app=ctx.app_name,
        window_title=ctx.window_title,
        browser_url=ctx.browser_url,
        file_path=ctx.file_path,
        entities=found_entities,
    )
