"""
BuildHarvey Windows entry point — headless background daemon.

All user-facing UI lives on buildharvey.com. This module:
  1. Checks for a stored credential; if missing, opens the browser and polls.
  2. Launches the capture loop in a background thread.
  3. Monitors Windows session events (lock, logoff, sleep) and force-stops on them.

Bundled OCR paths are configured BEFORE any imports that use OCR,
so pytesseract finds tesseract.exe inside the PyInstaller bundle.
"""
import sys
import os

# Set up bundled OCR paths BEFORE any imports that use OCR
if getattr(sys, 'frozen', False):
    _base = sys._MEIPASS
    os.environ['TESSDATA_PREFIX'] = os.path.join(_base, 'vendor', 'tesseract', 'tessdata')
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = os.path.join(
        _base, 'vendor', 'tesseract', 'tesseract.exe'
    )

import threading
import time

from dotenv import load_dotenv
load_dotenv()

import auth
import realtime_client
import main


class WindowsApp:
    def __init__(self):
        self._stop = threading.Event()

    def run(self):
        # Register Windows session event monitor (lock, logoff, disconnect, shutdown)
        try:
            import session_monitor_windows
            session_monitor_windows.start(stop_callback=self._emergency_stop)
        except Exception as exc:
            print(f'[app_windows] session monitor unavailable: {exc}')

        if not auth.read_credential():
            import platform as _platform
            device_name = _platform.node() or 'My PC'
            print(f"[app] No credential — activating device '{device_name}'")
            token = auth.activate(device_name=device_name)
            if not token:
                print("[app] Activation failed or timed out")
                return
            auth.store_credential(token)

        threading.Thread(
            target=main.main,
            kwargs={"stop_event": self._stop},
            daemon=True,
        ).start()

        try:
            while not self._stop.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self._stop.set()

    def _emergency_stop(self):
        """Called immediately on lock/logout/sleep. Stops recording."""
        realtime_client.force_stop()
        self._stop.set()


def run_self_test() -> int:
    """
    Non-destructive self-test for the packaged application.
    Writes results to %TEMP%/buildharvey-self-test.log (no console in GUI app).
    Returns 0 on pass, 1 on any failure.
    """
    import tempfile as _tempfile
    import sqlite3 as _sqlite3

    log_path = os.path.join(_tempfile.gettempdir(), 'buildharvey-self-test.log')
    failures: list[str] = []
    lines: list[str] = []

    def _log(msg: str) -> None:
        lines.append(msg)

    _log('[self-test] BuildHarvey self-test starting')

    # 1. Core imports
    try:
        import mss, PIL, numpy, keyring, psutil, pytesseract  # noqa: F401
        _log('[self-test] core imports: PASS')
    except ImportError as exc:
        failures.append(f'core imports: {exc}')
        _log(f'[self-test] core imports: FAIL — {exc}')

    # 2. OCR with bundled Tesseract (paths already configured at startup)
    try:
        from PIL import Image, ImageDraw
        import pytesseract
        tmp = os.path.join(_tempfile.gettempdir(), '_bh_ocr_test.png')
        img = Image.new('RGB', (500, 80), color='white')
        draw = ImageDraw.Draw(img)
        draw.text((10, 25), 'BuildHarvey OCR Test', fill='black')
        img.save(tmp)
        result = pytesseract.image_to_string(Image.open(tmp), lang='eng')
        try:
            os.unlink(tmp)
        except Exception:
            pass
        if 'buildharvey' not in result.lower() and 'ocr' not in result.lower():
            raise RuntimeError(f'unexpected output: {repr(result.strip()[:80])}')
        _log('[self-test] OCR smoke test: PASS')
    except Exception as exc:
        failures.append(f'OCR: {exc}')
        _log(f'[self-test] OCR smoke test: FAIL — {exc}')

    # 3. SQLite
    try:
        db = os.path.join(_tempfile.gettempdir(), '_bh_db_test.db')
        conn = _sqlite3.connect(db)
        conn.execute('CREATE TABLE t (id TEXT PRIMARY KEY)')
        conn.close()
        try:
            os.unlink(db)
        except Exception:
            pass
        _log('[self-test] SQLite: PASS')
    except Exception as exc:
        failures.append(f'SQLite: {exc}')
        _log(f'[self-test] SQLite: FAIL — {exc}')

    # 4. Windows capture adapter (non-destructive read)
    try:
        from os_adapters import Adapter
        adapter = Adapter()
        title = adapter.get_window_title()
        _log(f'[self-test] WindowsAdapter: PASS (window_title={repr(title[:40])})')
    except Exception as exc:
        failures.append(f'WindowsAdapter: {exc}')
        _log(f'[self-test] WindowsAdapter: FAIL — {exc}')

    # 5. Credential storage (read-only, no write)
    try:
        from os_adapters import Adapter
        Adapter().read_credential()   # returns None if no token stored — that's fine
        _log('[self-test] credential storage: PASS')
    except Exception as exc:
        failures.append(f'credential storage: {exc}')
        _log(f'[self-test] credential storage: FAIL — {exc}')

    # ── Write log and report ──────────────────────────────────────────────────
    if failures:
        _log(f'\n[self-test] FAILED ({len(failures)} failure(s)):')
        for f in failures:
            _log(f'  - {f}')
        exit_code = 1
    else:
        _log('\n[self-test] All checks PASSED')
        exit_code = 0

    try:
        with open(log_path, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(lines) + '\n')
    except Exception:
        pass

    return exit_code


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--noninteractive', action='store_true')
    parser.add_argument('--quit', action='store_true')
    args, _ = parser.parse_known_args()

    if args.quit:
        sys.exit(0)

    if args.self_test:
        sys.exit(run_self_test())

    # ── Handle buildharvey:// protocol URLs ──────────────────────────────────
    # When launched via the URL scheme (e.g. buildharvey://reconnect), the URL
    # is passed as a positional argument by the Windows shell handler.
    _proto_url = None
    for _arg in sys.argv[1:]:
        if _arg.startswith('buildharvey://'):
            _proto_url = _arg
            break

    if _proto_url:
        from urllib.parse import urlparse as _urlparse
        _parsed = _urlparse(_proto_url)
        if _parsed.netloc == 'reconnect':
            # Force re-activation on next launch by clearing stored credential
            auth.delete_credential()
        # buildharvey://open and any other paths fall through to normal launch

    WindowsApp().run()
