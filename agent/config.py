import os
from pathlib import Path

# ── Directories ───────────────────────────────────────────────────────────────
BASE_DIR = Path.home() / ".buildharvey"
DB_PATH = BASE_DIR / "buildharvey.db"

# Two temp frame slots for diff comparison.
# Frames are never kept permanently — images are processing artifacts only.
TEMP_FRAME_PATH = BASE_DIR / "_current.png"
PREV_FRAME_PATH = BASE_DIR / "_prev.png"

BASE_DIR.mkdir(exist_ok=True)

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

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")   # service role key
