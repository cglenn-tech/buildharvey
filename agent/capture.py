"""
Screen capture and frame comparison.
Frames are temporary processing artifacts — never persisted.
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
        monitor = sct.monitors[1]   # 0 = all monitors combined; 1 = primary
        frame = sct.grab(monitor)
        mss.tools.to_png(frame.rgb, frame.size, output=str(output_path))


def image_changed(path_a: Path, path_b: Path) -> bool:
    """Return True if the two frames differ meaningfully."""
    return diff_score(path_a, path_b) > config.DIFF_THRESHOLD


def diff_score(path_a: Path, path_b: Path) -> float:
    """
    Return the fraction of pixels that differ between two frames (0–1).
    Uses grayscale thumbnail comparison — cheap, ~1ms.
    Returns 1.0 on error (treat as changed).
    """
    try:
        a = np.array(Image.open(path_a).convert("L").resize(config.DIFF_RESIZE)).astype(int)
        b = np.array(Image.open(path_b).convert("L").resize(config.DIFF_RESIZE)).astype(int)
        return float((np.abs(a - b) > 30).sum() / a.size)
    except Exception:
        return 1.0
