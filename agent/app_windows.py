"""
Windows entry point — tkinter UI with full recording state machine.

States:
  not_connected  → agent has no credential stored
  connecting     → activation flow in progress
  ready_to_start → credential obtained, agent running, waiting for Start click
  recording      → local recording active
  stopping       → session being finalized (waiting for main.py to idle)
  error          → unexpected failure

The user clicks Start Work Session / Stop Work Session in this window.
The browser website is optional — closing it does NOT stop recording.

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
import tkinter as tk

from dotenv import load_dotenv
load_dotenv()

import auth
import realtime_client
from os_adapters import Adapter

_LABELS = {
    'not_connected':   'Connect your BuildHarvey account to get started.',
    'connecting':      'Opening browser for account connection…',
    'ready_to_start':  'Ready to start. Click Start Work Session to begin capturing your work.',
    'recording':       'BuildHarvey is recording your work.',
    'stopping':        'Finishing session…',
    'error':           'Error — see log for details.',
}

_PRIMARY_BUTTONS = {
    'not_connected':   'Connect Account',
    'error':           'Retry',
    'ready_to_start':  'Start Work Session',
    'recording':       'Stop Work Session',
}


def _validate_ocr() -> bool:
    """Verify bundled Tesseract produces readable output."""
    from PIL import Image, ImageDraw
    import tempfile
    img = Image.new('RGB', (200, 50), color='white')
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), 'test', fill='black')
    tmp = tempfile.mktemp(suffix='.png')
    img.save(tmp)
    try:
        adapter = Adapter()
        result = adapter.ocr_image(tmp)
        return 'test' in result.lower()
    except Exception:
        return False
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


class WindowsApp:
    def __init__(self) -> None:
        self._adapter = Adapter()
        self._state = 'not_connected'
        self._stop_event = threading.Event()
        self._root = tk.Tk()
        self._root.title('BuildHarvey')
        self._root.geometry('440x180')
        self._root.resizable(False, False)

        self._label_var = tk.StringVar(value=_LABELS['not_connected'])
        tk.Label(
            self._root,
            textvariable=self._label_var,
            wraplength=400,
            justify='left',
            padx=20,
            pady=20,
        ).pack()

        self._btn = tk.Button(
            self._root,
            text='Connect Account',
            command=self._primary_action,
            width=24,
        )
        self._btn.pack()
        self._update_ui()

    def _set_state(self, state: str) -> None:
        self._state = state
        self._root.after(0, self._update_ui)

    def _update_ui(self) -> None:
        self._label_var.set(_LABELS.get(self._state, self._state))
        btn_text = _PRIMARY_BUTTONS.get(self._state)
        if btn_text:
            self._btn.config(
                text=btn_text,
                state='disabled' if self._state == 'connecting' else 'normal',
            )
            self._btn.pack()
        else:
            # connecting / stopping — hide button
            self._btn.pack_forget()

    def _primary_action(self) -> None:
        state = self._state
        if state == 'not_connected':
            self._set_state('connecting')
            threading.Thread(target=self._run_activation, daemon=True).start()
        elif state == 'error':
            self._set_state('not_connected')
            self._update_ui()
        elif state == 'ready_to_start':
            realtime_client.start_local()
            self._set_state('recording')
        elif state == 'recording':
            realtime_client.stop_local()
            self._set_state('stopping')

    def _run_activation(self) -> None:
        import platform as _platform
        token = auth.activate(device_name=_platform.node() or 'My PC')
        if token:
            self._adapter.store_credential(token)
            self._set_state('ready_to_start')
            threading.Thread(target=self._run_agent, daemon=True).start()
        else:
            self._set_state('not_connected')

    def _emergency_stop(self) -> None:
        """Called immediately on lock/logout/disconnect. Stops recording."""
        realtime_client.force_stop()
        self._stop_event.set()
        self._set_state('ready_to_start')

    def _agent_state_update(self, state: str) -> None:
        """Called from main.py state_callback."""
        if state == 'idle' and self._state == 'stopping':
            self._set_state('ready_to_start')
        elif state == 'idle' and self._state == 'recording':
            # Recording stopped unexpectedly (OS event, error, etc.)
            self._set_state('ready_to_start')

    def _run_agent(self) -> None:
        import main as agent_main
        self._stop_event.clear()
        agent_main.main(state_callback=self._agent_state_update, stop_event=self._stop_event)

    def run(self) -> None:
        # OCR validation on first run
        if getattr(sys, 'frozen', False):
            if not _validate_ocr():
                print('[app_windows] WARNING: OCR validation failed — text extraction may be unavailable')

        # Register Windows session event monitor (lock, logoff, disconnect, shutdown)
        try:
            import session_monitor_windows
            session_monitor_windows.start(stop_callback=self._emergency_stop)
        except Exception as exc:
            print(f'[app_windows] session monitor unavailable: {exc}')

        cred = self._adapter.read_credential()
        if cred:
            self._set_state('ready_to_start')
            threading.Thread(target=self._run_agent, daemon=True).start()

        self._root.mainloop()


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
        # Called by the Inno Setup uninstaller to request a graceful quit.
        # The uninstaller terminates the process separately if needed.
        sys.exit(0)

    if args.self_test:
        sys.exit(run_self_test())

    WindowsApp().run()
