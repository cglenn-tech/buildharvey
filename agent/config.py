import os
from pathlib import Path

# ── Directories ───────────────────────────────────────────────────────────────
BASE_DIR = Path.home() / ".buildharvey"
DB_PATH = BASE_DIR / "buildharvey.db"

# Two temp frame slots for diff comparison.
TEMP_FRAME_PATH = BASE_DIR / "_current.png"
PREV_FRAME_PATH = BASE_DIR / "_prev.png"

# Screenshots saved per observation for Claude Vision analysis.
# Deleted after episode finalization.
SCREENSHOTS_DIR = BASE_DIR / "screenshots"

BASE_DIR.mkdir(exist_ok=True)
SCREENSHOTS_DIR.mkdir(exist_ok=True)

# ── Capture ───────────────────────────────────────────────────────────────────
CAPTURE_INTERVAL_SECONDS = 5    # seconds between screen captures
DIFF_THRESHOLD = 0.02           # fraction of pixels that must change to be meaningful (2%)
DIFF_RESIZE = (320, 180)        # thumbnail size for cheap diff comparison

# ── Episode lifecycle ─────────────────────────────────────────────────────────
INACTIVITY_PAUSE_SECONDS = 300          # idle this long → pause timing (don't close episode)
INACTIVITY_TIMEOUT_SECONDS = 300        # alias for INACTIVITY_PAUSE_SECONDS (kept for test compat)
MAX_EPISODE_SECONDS = 28800             # close episode after 8 h regardless (safety net)
ADMIN_GRACE_SECONDS = 60                # no-case activity allowed before switching to Administrative
CASE_SWITCH_THRESHOLD = 3               # consecutive observations of the same new case required
                                        # before switching episodes — prevents spurious switches
                                        # from scrolling, ads, or transient OCR noise
MIN_EPISODE_DURATION_MINUTES = 0.5      # episodes shorter than this are discarded
MAX_KEY_OBSERVATIONS = 8               # max observations stored per episode

# Max screenshots preserved per episode (evenly subsampled for evidence storage).
MAX_VISION_SCREENSHOTS = 8

# ── Screenshot compression for server-side vision analysis ────────────────────
# Screenshots are resized and JPEG-compressed before being POSTed to the server.
VISION_JPEG_QUALITY = 85
VISION_ANALYSIS_SIZE = (1440, 900)          # max pixel dimensions sent to server
VISION_MAX_ENCODED_BYTES = 3 * 1024 * 1024  # 3 MB base64 limit per screenshot

# Max pixel dimensions for screenshots sent to the vision API.
# Reduces token cost while preserving enough resolution to read content.
SCREENSHOT_MAX_SIZE = (1440, 900)

# Pixel diff fraction above which a screenshot is treated as a significant
# visual change and saved regardless of other signals (e.g. new page loaded).
SCREENSHOT_LARGE_DIFF = 0.15

# Always save a screenshot at least this often (seconds) even if no other
# signal fires, so long sessions have periodic coverage.
SCREENSHOT_MIN_INTERVAL = 60.0

# ── API ───────────────────────────────────────────────────────────────────────
# Development: set BUILDHARVEY_BASE_URL=http://localhost:3000 in agent/.env
# Production app bundle uses the hardcoded default.
BASE_URL = os.environ.get("BUILDHARVEY_BASE_URL", "https://buildharvey.com")

# ── Version ───────────────────────────────────────────────────────────────────
# _version.py is generated at build time by the CI workflow (not checked in).
try:
    from _version import __version__ as APP_VERSION
except ImportError:
    APP_VERSION = 'unknown'
