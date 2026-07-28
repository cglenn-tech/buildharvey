"""
Screen capture and frame comparison.
No episode logic. No OCR. Just pixels.
"""
from pathlib import Path

import mss
import mss.tools
from PIL import Image
import numpy as np

import config


def capture_screen(output_path: Path) -> None:
    """Capture the primary monitor and write to output_path as PNG."""
    with mss.mss() as sct:
        monitor = sct.monitors[1]  # index 0 = all monitors combined; 1 = primary
        frame = sct.grab(monitor)
        mss.tools.to_png(frame.rgb, frame.size, output=str(output_path))


def image_changed(path_a: Path, path_b: Path) -> bool:
    """
    Return True if the two frames differ meaningfully.
    Uses grayscale thumbnail diff — cheap, ~1ms per comparison.
    """
    try:
        a = np.array(Image.open(path_a).convert("L").resize(config.DIFF_RESIZE)).astype(int)
        b = np.array(Image.open(path_b).convert("L").resize(config.DIFF_RESIZE)).astype(int)
        changed_pixels = (np.abs(a - b) > 30).sum() / a.size
        return changed_pixels > config.DIFF_THRESHOLD
    except Exception:
        return True  # on any error, treat as changed to avoid silently dropping frames


def screenshot_path(episode_id: str, screenshot_id: str) -> Path:
    """
    Permanent storage path for a screenshot.
    The screenshot_id matches what is used in Supabase Storage,
    so local path and remote path always refer to the same capture.
    """
    dest = config.SCREENSHOTS_DIR / episode_id
    dest.mkdir(parents=True, exist_ok=True)
    return dest / f"{screenshot_id}.png"
