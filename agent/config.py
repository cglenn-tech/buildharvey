import os
from pathlib import Path

# ── Directories ───────────────────────────────────────────────────────────────
BASE_DIR = Path.home() / ".buildharvey"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
DB_PATH = BASE_DIR / "buildharvey.db"
TEMP_FRAME_PATH = BASE_DIR / "_current.png"  # overwritten every capture cycle

BASE_DIR.mkdir(exist_ok=True)
SCREENSHOTS_DIR.mkdir(exist_ok=True)

# ── Capture ───────────────────────────────────────────────────────────────────
CAPTURE_INTERVAL_SECONDS = 5    # how often to capture
DIFF_THRESHOLD = 0.02           # fraction of pixels that must change (2%)
DIFF_RESIZE = (320, 180)        # thumbnail size for cheap diff comparison

# ── Episode lifecycle ─────────────────────────────────────────────────────────
INACTIVITY_TIMEOUT_SECONDS = 600    # 10 min idle → close episode
CONTEXT_SHIFT_THRESHOLD = 0.6       # combined signal score → new episode

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")   # service role key
STORAGE_BUCKET = "screenshots"
