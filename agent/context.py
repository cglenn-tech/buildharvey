"""
Active application context: app name, window title, browser URL, file path.
All values fall back to empty string on any error.
"""
import subprocess
from dataclasses import dataclass


@dataclass
class ScreenContext:
    app_name: str
    bundle_id: str
    window_title: str
    browser_url: str    # populated when a supported browser is frontmost
    file_path: str      # populated for supported document apps


# Browser bundle IDs → AppleScript to retrieve the active URL
_BROWSER_SCRIPTS: dict[str, str] = {
    "com.apple.Safari": 'tell application "Safari" to get URL of current tab of front window',
    "com.google.Chrome": 'tell application "Google Chrome" to get URL of active tab of front window',
    "company.thebrowser.Browser": 'tell application "Arc" to get URL of active tab of front window',
    "org.mozilla.firefox": "",  # Firefox has poor AppleScript support — skip
}

# App bundle IDs → AppleScript to retrieve the frontmost document path
_DOCUMENT_SCRIPTS: dict[str, str] = {
    "com.apple.TextEdit": 'tell application "TextEdit" to get path of front document',
    "com.apple.Pages": 'tell application "Pages" to get path of front document',
    "com.apple.Numbers": 'tell application "Numbers" to get path of front document',
    "com.microsoft.Word": 'tell application "Microsoft Word" to get full name of active document',
    "com.microsoft.Excel": 'tell application "Microsoft Excel" to get full name of active workbook',
}


def get_context() -> ScreenContext:
    app_name, bundle_id = _get_active_app()
    window_title = _get_window_title()
    browser_url = _get_browser_url(bundle_id)
    file_path = _get_file_path(bundle_id)

    return ScreenContext(
        app_name=app_name,
        bundle_id=bundle_id,
        window_title=window_title,
        browser_url=browser_url,
        file_path=file_path,
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _get_active_app() -> tuple[str, str]:
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return str(app.localizedName() or ""), str(app.bundleIdentifier() or "")
    except Exception:
        return "", ""


def _get_window_title() -> str:
    try:
        import Quartz
        options = (
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements
        )
        windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
        # The frontmost non-desktop window is typically first at layer 0
        for w in windows or []:
            if w.get("kCGWindowLayer") == 0:
                title = w.get("kCGWindowName", "")
                if title:
                    return str(title)
        return ""
    except Exception:
        return ""


def _get_browser_url(bundle_id: str) -> str:
    script = _BROWSER_SCRIPTS.get(bundle_id, "")
    if not script:
        return ""
    return _run_applescript(script)


def _get_file_path(bundle_id: str) -> str:
    script = _DOCUMENT_SCRIPTS.get(bundle_id, "")
    if not script:
        return ""
    return _run_applescript(script)


def _run_applescript(script: str) -> str:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""
