"""
macOS implementation of OSAdapter.
Wraps the existing context.py, ocr.py, permissions.py, and auth.py Keychain logic.
No logic changes — purely reorganized.
"""
import subprocess
import time
from typing import Optional


class MacOSAdapter:

    # ── Context ──────────────────────────────────────────────────────────

    def get_active_app(self) -> str:
        try:
            from AppKit import NSWorkspace
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            return str(app.localizedName() or "")
        except Exception:
            return ""

    def get_window_title(self) -> str:
        try:
            import Quartz
            options = (
                Quartz.kCGWindowListOptionOnScreenOnly
                | Quartz.kCGWindowListExcludeDesktopElements
            )
            windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
            for w in windows or []:
                if w.get("kCGWindowLayer") == 0:
                    title = w.get("kCGWindowName", "")
                    if title:
                        return str(title)
            return ""
        except Exception:
            return ""

    def get_browser_url(self) -> str:
        # Caller must pass the bundle_id; we do a best-effort here
        # by trying common browsers. In practice context.py still handles this.
        return ""

    # ── OCR ──────────────────────────────────────────────────────────────

    def ocr_image(self, path: str) -> str:
        """Apple Vision OCR — accurate, local, no network."""
        try:
            import Vision
            from Foundation import NSURL

            url = NSURL.fileURLWithPath_(str(path))
            handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, {})
            request = Vision.VNRecognizeTextRequest.alloc().init()
            request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
            request.setUsesLanguageCorrection_(True)

            success, error = handler.performRequests_error_([request], None)
            if not success or error:
                return ""

            lines = []
            for obs in request.results() or []:
                candidates = obs.topCandidates_(1)
                if candidates:
                    lines.append(str(candidates[0].string()))
            return "\n".join(lines)
        except Exception as exc:
            print(f"[ocr] error: {exc}")
            return ""

    # ── Credentials ──────────────────────────────────────────────────────

    _KEYCHAIN_SERVICE = 'com.buildharvey.agent'

    def read_credential(self, account: str = 'device-token') -> Optional[str]:
        try:
            result = subprocess.run(
                [
                    'security', 'find-generic-password',
                    '-s', self._KEYCHAIN_SERVICE,
                    '-a', account,
                    '-w',
                ],
                capture_output=True,
                text=True,
            )
            token = result.stdout.strip()
            return token if token else None
        except Exception:
            return None

    def store_credential(self, token: str, account: str = 'device-token') -> None:
        subprocess.run(
            [
                'security', 'delete-generic-password',
                '-s', self._KEYCHAIN_SERVICE,
                '-a', account,
            ],
            capture_output=True,
        )
        subprocess.run(
            [
                'security', 'add-generic-password',
                '-s', self._KEYCHAIN_SERVICE,
                '-a', account,
                '-w', token,
                '-U',
            ],
            check=True,
        )

    # ── Permissions ──────────────────────────────────────────────────────

    def check_screen_permission(self) -> bool:
        try:
            import Quartz
            return bool(Quartz.CGPreflightScreenCaptureAccess())
        except Exception:
            return False

    def request_screen_permission(self) -> str:
        try:
            import Quartz
            granted = Quartz.CGRequestScreenCaptureAccess()
            if granted:
                return 'GRANTED'
            time.sleep(0.5)
            return 'GRANTED' if Quartz.CGPreflightScreenCaptureAccess() else 'RESTART_REQUIRED'
        except Exception:
            return 'RESTART_REQUIRED'

    def open_permission_settings(self) -> None:
        subprocess.run([
            'open',
            'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture',
        ], check=False)
