"""
macOS screen capture permission checks using Quartz / CoreGraphics.
"""
import subprocess
import time


def check() -> str:
    """Returns 'GRANTED' or 'REQUIRED'."""
    try:
        import Quartz
        return 'GRANTED' if Quartz.CGPreflightScreenCaptureAccess() else 'REQUIRED'
    except Exception:
        return 'REQUIRED'


def request() -> str:
    """
    Requests screen capture permission via the system TCC dialog.
    Returns 'GRANTED' or 'RESTART_REQUIRED'.

    Some macOS versions require an app restart for the permission
    to take effect after the user clicks Allow.
    """
    try:
        import Quartz
        granted = Quartz.CGRequestScreenCaptureAccess()
        if granted:
            return 'GRANTED'
        # Re-check after brief delay — user may have clicked Allow
        time.sleep(0.5)
        return 'GRANTED' if Quartz.CGPreflightScreenCaptureAccess() else 'RESTART_REQUIRED'
    except Exception:
        return 'RESTART_REQUIRED'


def open_system_prefs() -> None:
    """Open the Screen Recording section of System Settings."""
    subprocess.run([
        'open',
        'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture',
    ], check=False)
