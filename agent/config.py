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
INACTIVITY_TIMEOUT_SECONDS = 600        # idle this long → close episode (10 min)
ADMIN_GRACE_SECONDS = 60                # no-case activity allowed before switching to Administrative
CASE_SWITCH_THRESHOLD = 3               # consecutive observations of the same new case required
                                        # before switching episodes — prevents spurious switches
                                        # from scrolling, ads, or transient OCR noise
MIN_EPISODE_DURATION_MINUTES = 0.5      # episodes shorter than this are discarded
MAX_KEY_OBSERVATIONS = 8               # max observations stored per episode

# ── Anthropic ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OBSERVATION_MODEL = "claude-haiku-4-5"   # fast model for per-episode finalization

# Max screenshots passed to Claude Vision per episode.
# Screenshots are subsampled evenly if more were captured.
MAX_VISION_SCREENSHOTS = 8

# Max pixel dimensions for screenshots sent to the vision API.
# Reduces token cost while preserving enough resolution to read content.
SCREENSHOT_MAX_SIZE = (1440, 900)

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")   # service role key
