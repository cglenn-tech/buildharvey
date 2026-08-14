import os
from pathlib import Path

# ── Build-time production lock ────────────────────────────────────────────────
# When PRODUCTION_BUILD=True (set by build pipeline), privacy flags are forced
# to their production values and cannot be weakened at runtime.
try:
    from _build_config import PRODUCTION_BUILD
except ImportError:
    PRODUCTION_BUILD = False

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

# ── Privacy mode (master switch) ─────────────────────────────────────────────
# PRIVATE_MODE=true is the production default. CI and development set it to
# false explicitly to allow cloud paths and disable encryption.
# When true: capture leases required, local inference required, SQLite encrypted,
# sync disabled, cloud vision/finalizer fallback disabled.
#
# PRODUCTION_BUILD=True: env var override is ignored — PRIVATE_MODE is always True.
if PRODUCTION_BUILD:
    PRIVATE_MODE = True
else:
    PRIVATE_MODE = os.environ.get("BUILDHARVEY_PRIVATE_MODE", "true").lower() == "true"

# ── Privacy / Capture Lease Model (Phase 1) ───────────────────────────────────
# Per-window consent before any observation is recorded.
# Default TRUE in Private Mode (production). Override with ENABLE_CAPTURE_LEASES=false
# in development/CI.
# PRODUCTION_BUILD: always True, cannot be weakened.
if PRODUCTION_BUILD:
    ENABLE_CAPTURE_LEASES = True
else:
    _capture_leases_default = "true" if PRIVATE_MODE else "false"
    ENABLE_CAPTURE_LEASES = os.environ.get("ENABLE_CAPTURE_LEASES", _capture_leases_default).lower() == "true"

# Individual consent dialog timeout (seconds). Privacy fails closed on timeout.
CONSENT_DIALOG_TIMEOUT_SECONDS = int(os.environ.get("CONSENT_DIALOG_TIMEOUT_SECONDS", "30"))

# Batch re-consent UI timeout after device unlock (seconds). Fails closed on timeout.
BATCH_RECONSENT_TIMEOUT_SECONDS = int(os.environ.get("BATCH_RECONSENT_TIMEOUT_SECONDS", "120"))

# ── Privacy / AppleScript metadata (Phase 2) ─────────────────────────────────
# Set TRUE to enable AppleScript browser URL and document path extraction.
# Requires Automation permissions for each targeted app.
# Default FALSE (opt-in regardless of PRIVATE_MODE — Automation dialogs are
# never shown without explicit user opt-in).
ENABLE_APPLESCRIPT_METADATA = os.environ.get("ENABLE_APPLESCRIPT_METADATA", "false").lower() == "true"

# ── Privacy / Screenshot retention ────────────────────────────────────────────
# At startup, delete temp frames older than this many hours (crash safety net).
SCREENSHOT_RETENTION_HOURS = int(os.environ.get("SCREENSHOT_RETENTION_HOURS", "1"))

# ── Privacy / Local Inference (Phase 3+) ─────────────────────────────────────
# Use on-device model for episode boundary classification and summarization.
# Default TRUE in Private Mode (production). Override with USE_LOCAL_INFERENCE=false
# in development/CI.
# PRODUCTION_BUILD: always True, cannot be weakened.
if PRODUCTION_BUILD:
    USE_LOCAL_INFERENCE = True
else:
    _local_inference_default = "true" if PRIVATE_MODE else "false"
    USE_LOCAL_INFERENCE = os.environ.get("USE_LOCAL_INFERENCE", _local_inference_default).lower() == "true"

# Local model storage directory (never bundled in installer — downloaded on first run).
LOCAL_MODELS_DIR = Path.home() / "Library" / "Application Support" / "BuildHarvey" / "models"
