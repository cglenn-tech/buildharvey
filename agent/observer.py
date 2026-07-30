"""
Observer — captures the screen, extracts facts, produces Observations.

Screenshots are saved per observation so the finalizer can use Claude Vision
to understand what work was actually occurring. Screenshots are deleted after
episode finalization.
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
    screenshot_path: Optional[str] = None  # saved screenshot for vision analysis


def observe() -> Optional[Observation]:
    """
    Capture the current screen and return an Observation if something meaningful
    has changed since the previous frame.

    Returns None if the screen is static.
    The screenshot is saved for vision analysis and deleted after episode finalization.
    """
    capture.capture_screen(config.TEMP_FRAME_PATH)

    # Compare against the previous baseline frame
    if config.PREV_FRAME_PATH.exists():
        if not capture.image_changed(config.PREV_FRAME_PATH, config.TEMP_FRAME_PATH):
            return None

    ctx = ctx_module.get_context()
    text = ocr.extract_text(config.TEMP_FRAME_PATH)
    found_entities = entities_mod.extract(text, ctx.window_title, ctx.file_path)

    # Save screenshot for vision analysis at episode close.
    # Resized to reduce token cost while preserving readable text.
    screenshot_path = _save_screenshot()

    # Save current frame as the new baseline
    shutil.copy2(config.TEMP_FRAME_PATH, config.PREV_FRAME_PATH)

    return Observation(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        app=ctx.app_name,
        window_title=ctx.window_title,
        browser_url=ctx.browser_url,
        file_path=ctx.file_path,
        entities=found_entities,
        screenshot_path=screenshot_path,
    )


def _save_screenshot() -> Optional[str]:
    """
    Save a resized copy of the current frame to SCREENSHOTS_DIR.
    Returns the path on success, None on any failure.
    """
    try:
        from PIL import Image

        ts = time.strftime("%Y%m%dT%H%M%S")
        dest = config.SCREENSHOTS_DIR / f"obs_{ts}.jpg"

        img = Image.open(config.TEMP_FRAME_PATH)
        img.thumbnail(config.SCREENSHOT_MAX_SIZE, Image.LANCZOS)
        img.save(str(dest), "JPEG", quality=85)

        return str(dest)
    except Exception as e:
        # Screenshot saving is best-effort; observation still proceeds without it.
        print(f"[observer] screenshot save failed: {e}")
        return None
