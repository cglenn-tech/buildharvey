"""
Windows implementation of OSAdapter.
Uses win32gui, psutil, pytesseract, and keyring.
All imports are lazy so this file can be imported without triggering import errors
on systems where the Windows-specific packages aren't installed.

Browser URL extraction uses window title parsing only — pywinauto is not used
(it requires UIAutomation permissions and can trigger AV false positives).
"""
import os
from typing import Optional


class WindowsAdapter:

    # ── Context ──────────────────────────────────────────────────────────

    def get_active_app(self) -> str:
        try:
            import psutil
            import win32gui
            import win32process
            hwnd = win32gui.GetForegroundWindow()
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            name = psutil.Process(pid).name()
            return name.removesuffix('.exe')
        except Exception:
            return ''

    def get_window_title(self) -> str:
        try:
            import win32gui
            return win32gui.GetWindowText(win32gui.GetForegroundWindow())
        except Exception:
            return ''

    def get_browser_url(self) -> str:
        """
        Best-effort URL from the active window title.

        Chrome/Edge/Firefox encode the current URL or page title in the window
        title. Full URL extraction via accessibility APIs (pywinauto/UIAutomation)
        is omitted: it requires elevated permissions and trips AV scanners.
        """
        try:
            import win32gui
            title = win32gui.GetWindowText(win32gui.GetForegroundWindow())
            # Some browsers put the URL in the title when the omnibox is focused;
            # otherwise return empty string and let OCR/entity extraction handle it.
            if title.startswith("http://") or title.startswith("https://"):
                return title.strip()
        except Exception:
            pass
        return ''

    # ── OCR ──────────────────────────────────────────────────────────────

    def ocr_image(self, path: str) -> str:
        """
        Uses bundled Tesseract (TESSDATA_PREFIX and tesseract_cmd set at startup
        from sys._MEIPASS in app_windows.py before any OCR calls).
        """
        try:
            import pytesseract
            from PIL import Image
            return pytesseract.image_to_string(Image.open(path), lang='eng')
        except Exception:
            return ''

    # ── Credentials ──────────────────────────────────────────────────────

    def read_credential(self, account: str = 'device-token') -> Optional[str]:
        try:
            import keyring
            return keyring.get_password('com.buildharvey.agent', account) or None
        except Exception:
            return None

    def store_credential(self, token: str, account: str = 'device-token') -> None:
        import keyring
        keyring.set_password('com.buildharvey.agent', account, token)

    def delete_credential(self, account: str = 'device-token') -> None:
        try:
            import keyring
            keyring.delete_password('com.buildharvey.agent', account)
        except Exception:
            pass

    # ── Permissions (no-op on Windows) ───────────────────────────────────

    def check_screen_permission(self) -> bool:
        return True  # Windows has no screen recording TCC

    def request_screen_permission(self) -> str:
        return 'GRANTED'

    def open_permission_settings(self) -> None:
        pass
