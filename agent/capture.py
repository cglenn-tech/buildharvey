"""
Screen capture and frame comparison.
Frames are temporary processing artifacts — never persisted.

capture_window(window_id, output_path) — per-window capture using platform APIs:
  macOS: CGWindowListCreateImage (by CGWindowID)
  Windows: PrintWindow with PW_RENDERFULLCONTENT (by HWND)
  Both APIs render ONLY the target window's compositor buffer. Adjacent windows,
  notifications, and desktop elements are structurally excluded — they are not
  composited into the result regardless of Z-order.

  Returns True on success. Returns False on any failure — caller must NOT fall
  back to full-monitor capture; it must create an ObservationGap instead.

capture_screen(output_path) — full primary monitor via mss. Used ONLY when
  ENABLE_CAPTURE_LEASES=false (consent leases disabled by configuration).
  Never called after consent has been checked for a specific window.

Capture API selection:
  macOS  → CGWindowListCreateImage (CGWindowID-scoped, DWM-equivalent isolation)
  Windows → PrintWindow + PW_RENDERFULLCONTENT (HWND-scoped, compositor-isolated)
  Other  → fail closed (False); caller creates ObservationGap
"""
import ctypes
import ctypes.wintypes
import platform
from pathlib import Path

from PIL import Image
import numpy as np

import config


def capture_window(window_id: int, output_path: Path) -> bool:
    """
    Capture a single window by its platform-native ID and write to output_path.

    macOS: window_id is a CGWindowID (integer from CGWindowListCopyWindowInfo).
    Windows: window_id is an HWND cast to int (from win32gui.GetForegroundWindow()).

    Returns True on success.
    Returns False on any failure — NEVER falls back to full-monitor capture.
    The caller must treat False as a consent-equivalent failure (ObservationGap).

    Privacy guarantee:
      macOS: CGWindowListCreateImage renders the window's own CGSurface. Pixel
             data from off-screen or neighboring windows is never included.
      Windows: PrintWindow with PW_RENDERFULLCONTENT asks the DWM compositor to
               render the window's own backing surface. The DWM surface is
               per-HWND; neighboring window content cannot appear in the result
               regardless of window overlap or Z-order.
    """
    if platform.system() == "Darwin":
        return _capture_window_macos(window_id, output_path)
    elif platform.system() == "Windows":
        return _capture_window_win32(window_id, output_path)
    else:
        # Unsupported platform — fail closed; caller creates ObservationGap
        return False


def _capture_window_macos(cg_window_id: int, output_path: Path) -> bool:
    """
    macOS implementation using CGWindowListCreateImage (CGWindowID-scoped).

    kCGWindowListOptionIncludingWindow renders only the target window's
    CGSurface. Neighboring windows are excluded by the OS compositor.
    """
    try:
        import Quartz

        image = Quartz.CGWindowListCreateImage(
            Quartz.CGRectNull,
            Quartz.kCGWindowListOptionIncludingWindow,
            cg_window_id,
            Quartz.kCGWindowImageBoundsIgnoreFraming,
        )
        if image is None:
            return False

        from Foundation import NSMutableData
        data = NSMutableData.data()
        dest = Quartz.CGImageDestinationCreateWithData(
            data,
            "public.png",
            1,
            None,
        )
        if dest is None:
            return False
        Quartz.CGImageDestinationAddImage(dest, image, None)
        Quartz.CGImageDestinationFinalize(dest)

        output_path.write_bytes(bytes(data))
        return True
    except Exception:
        return False


def _capture_window_win32(hwnd: int, output_path: Path) -> bool:
    """
    Windows implementation using PrintWindow + PW_RENDERFULLCONTENT.

    PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT) instructs the DWM compositor
    to render the window's own compositor surface into the provided DC. Because
    the DWM surface is per-HWND, neighboring application windows, notification
    banners, and desktop content are structurally absent from the result.

    PW_RENDERFULLCONTENT = 0x2 (required for modern apps using DirectX/DX12
    composition, including Chrome, Edge, Office, and WinUI apps).
    Fallback to PW_CLIENTONLY = 0x1 for legacy GDI applications.

    Returns True on success, False on any failure.
    Failure must be treated as ObservationGap by the caller — never falls back
    to full-monitor capture.
    """
    _PW_RENDERFULLCONTENT = 0x2
    _PW_CLIENTONLY = 0x1

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    # Get window client rect
    rect = ctypes.wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False

    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return False

    hwnd_dc = user32.GetWindowDC(hwnd)
    if not hwnd_dc:
        return False

    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    if not mem_dc:
        user32.ReleaseDC(hwnd, hwnd_dc)
        return False

    bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    if not bitmap:
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd, hwnd_dc)
        return False

    old_bmp = gdi32.SelectObject(mem_dc, bitmap)
    try:
        # Try PW_RENDERFULLCONTENT first (DWM compositor path — DX12/WinUI/Chrome)
        ok = user32.PrintWindow(hwnd, mem_dc, _PW_RENDERFULLCONTENT)
        if not ok:
            # Legacy GDI fallback
            ok = user32.PrintWindow(hwnd, mem_dc, _PW_CLIENTONLY)
        if not ok:
            return False

        # Extract BGRA pixel data via GetDIBits
        # BITMAPINFOHEADER
        class _BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize",          ctypes.c_uint32),
                ("biWidth",         ctypes.c_int32),
                ("biHeight",        ctypes.c_int32),
                ("biPlanes",        ctypes.c_uint16),
                ("biBitCount",      ctypes.c_uint16),
                ("biCompression",   ctypes.c_uint32),
                ("biSizeImage",     ctypes.c_uint32),
                ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32),
                ("biClrUsed",       ctypes.c_uint32),
                ("biClrImportant",  ctypes.c_uint32),
            ]

        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth = width
        bmi.biHeight = -height   # negative = top-down bitmap
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0    # BI_RGB

        buf_size = width * height * 4
        buf = (ctypes.c_byte * buf_size)()
        lines = gdi32.GetDIBits(mem_dc, bitmap, 0, height, buf, ctypes.byref(bmi), 0)
        if not lines:
            return False

        # Convert BGRA → RGB using Pillow
        img = Image.frombuffer("RGBA", (width, height), bytes(buf), "raw", "BGRA", 0, 1)
        img = img.convert("RGB")
        img.save(str(output_path), "PNG")
        return True

    except Exception:
        return False
    finally:
        gdi32.SelectObject(mem_dc, old_bmp)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd, hwnd_dc)


def capture_screen(output_path: Path) -> None:
    """
    Capture the primary monitor and write to output_path as PNG.

    ONLY called when ENABLE_CAPTURE_LEASES=false. Never called after a
    per-window consent check — that path always uses capture_window().
    """
    import mss
    import mss.tools
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
