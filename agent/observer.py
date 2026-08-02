"""
Observer — captures the screen, extracts facts, produces Observations.

Screenshots are saved selectively — only when they contain meaningful new
information (app change, URL change, large visual shift, significant new
OCR content, or periodic coverage gap). This keeps screenshot count low
and signal quality high for Claude Vision at episode close.
"""
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import capture
import config
import context as ctx_module
import entities as entities_mod
import ocr

# Apps that must never generate Episodes.
# The agent itself and OS-level UIs are excluded to prevent "BuildHarvey" or
# "loginwindow" from appearing as case names in the Episode Engine.
_SYSTEM_APPS = frozenset({
    '', 'loginwindow', 'SystemPreferences', 'System Preferences',
    'System Settings', 'Spotlight', 'Dock', 'Finder',
    'SecurityAgent', 'UserNotificationCenter',
    'BuildHarvey',      # the agent itself (macOS)
    'Task Manager',     # Windows
    'Explorer',         # Windows File Explorer
})


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


# ── Module-level state for screenshot signal filtering ─────────────────────────
# Tracks the context of the last saved screenshot so we can detect
# meaningful changes without saving redundant frames.

_last_app: str = ""
_last_url_domain: str = ""
_last_ocr_len: int = 0
_last_saved_at: float = 0.0


def observe() -> Optional[Observation]:
    """
    Capture the current screen and return an Observation if something meaningful
    has changed since the previous frame.

    Returns None if the screen is static.
    Screenshots are saved only when they contain high-value new information.
    """
    capture.capture_screen(config.TEMP_FRAME_PATH)

    # Compute diff score once; used for both the "any change" gate and the
    # "large change" screenshot signal.
    diff = 0.0
    if config.PREV_FRAME_PATH.exists():
        diff = capture.diff_score(config.PREV_FRAME_PATH, config.TEMP_FRAME_PATH)
        if diff <= config.DIFF_THRESHOLD:
            return None  # screen is static — nothing to record

    ctx = ctx_module.get_context()
    text = ocr.extract_text(config.TEMP_FRAME_PATH)
    found_entities = entities_mod.extract(text, ctx.window_title, ctx.file_path)

    # Save screenshot only if this frame represents meaningful new information.
    screenshot_path = _save_screenshot(ctx, text, diff)

    # Update the diff baseline regardless of whether a screenshot was saved.
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


# ── Screenshot selection ───────────────────────────────────────────────────────

def _save_screenshot(ctx, text: str, diff: float) -> Optional[str]:
    """
    Save a screenshot only if this frame is high-value.

    High-value signals:
      - First screenshot (or long time since last one)
      - Application changed
      - Browser navigated to a different domain
      - Large visual change (new page, document, window)
      - Significant new OCR content appeared

    Returns the saved path on success, None if skipped or on error.
    """
    if not _is_high_value(ctx, text, diff):
        return None

    return _write_screenshot(ctx, text)


def _is_high_value(ctx, text: str, diff: float) -> bool:
    """Return True if this frame warrants a saved screenshot."""
    global _last_app, _last_url_domain, _last_ocr_len, _last_saved_at

    now = time.time()

    # Periodic coverage: always capture if enough time has passed.
    if now - _last_saved_at >= config.SCREENSHOT_MIN_INTERVAL:
        return True

    # Application switched — always a meaningful context change.
    if ctx.app_name != _last_app:
        return True

    # Browser navigated to a different domain.
    current_domain = _domain(ctx.browser_url)
    if current_domain and current_domain != _last_url_domain:
        return True

    # Large visual shift (new page, modal, document).
    if diff >= config.SCREENSHOT_LARGE_DIFF:
        return True

    # Significant OCR change: substantial new text appeared on screen.
    if _last_ocr_len > 0:
        change = abs(len(text) - _last_ocr_len) / _last_ocr_len
        if change >= 0.30:
            return True

    return False


def _write_screenshot(ctx, text: str) -> Optional[str]:
    """Resize and save the current frame; update module state. Returns path or None."""
    global _last_app, _last_url_domain, _last_ocr_len, _last_saved_at

    try:
        from PIL import Image

        ts = time.strftime("%Y%m%dT%H%M%S")
        dest = config.SCREENSHOTS_DIR / f"obs_{ts}.jpg"

        img = Image.open(config.TEMP_FRAME_PATH)
        img.thumbnail(config.SCREENSHOT_MAX_SIZE, Image.LANCZOS)
        img.save(str(dest), "JPEG", quality=85)

        # Update state only on success so a failed save doesn't advance the baseline.
        _last_app = ctx.app_name
        _last_url_domain = _domain(ctx.browser_url)
        _last_ocr_len = len(text)
        _last_saved_at = time.time()

        return str(dest)
    except Exception as e:
        print(f"[observer] screenshot save failed: {e}")
        return None


def _domain(url: str) -> str:
    if not url:
        return ""
    try:
        return urlparse(url).netloc
    except Exception:
        return ""


def is_user_work(obs: 'Observation') -> bool:
    """
    Returns True only if this observation represents real user work.

    System events, session lifecycle, and agent-internal activity
    never return True and therefore never enter the Episode Engine.
    This is the primary filter; the garbage name list in database.py
    is a secondary defensive filter.
    """
    if not obs:
        return False
    app = (obs.app or '').strip()
    if app in _SYSTEM_APPS:
        return False
    if not app and not obs.window_title:
        return False
    if 'buildharvey' in app.lower():
        return False
    return True


def reset() -> None:
    """
    Reset observer state after a capture exception (e.g. after system sleep/wake).
    capture.py creates a fresh mss context per call so no mss reset is needed;
    this clears the diff baseline so the next frame is always treated as changed.
    """
    global _last_app, _last_url_domain, _last_ocr_len, _last_saved_at
    _last_app = ""
    _last_url_domain = ""
    _last_ocr_len = 0
    _last_saved_at = 0.0
    print("[observer] state reset after error")
