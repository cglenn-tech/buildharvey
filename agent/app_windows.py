"""
Windows entry point — tkinter UI with full recording state machine.

States:
  not_connected → connecting → waiting → recording → grace_period → idle → error

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
import session_server
from os_adapters import Adapter

_LABELS = {
    'not_connected':  'Connect your BuildHarvey account to get started.',
    'connecting':     'Opening browser for account connection…',
    'waiting':        'Open buildharvey.com to begin recording.',
    'recording':      'Recording — observing your work.',
    'grace_period':   'Browser closed — recording pauses in 10 minutes.',
    'idle':           'Paused. Open buildharvey.com to resume.',
    'error':          'Error — see log for details.',
    'sync_pending':   'Recording — syncing completed work.',
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
        self._root.geometry('420x160')
        self._root.resizable(False, False)

        self._label_var = tk.StringVar(value=_LABELS['not_connected'])
        tk.Label(
            self._root,
            textvariable=self._label_var,
            wraplength=380,
            justify='left',
            padx=20,
            pady=20,
        ).pack()

        self._btn = tk.Button(
            self._root,
            text='Connect Account',
            command=self._primary_action,
            width=20,
        )
        self._btn.pack()
        self._update_ui()

    def _set_state(self, state: str) -> None:
        self._state = state
        self._root.after(0, self._update_ui)

    def _update_ui(self) -> None:
        self._label_var.set(_LABELS.get(self._state, self._state))
        if self._state in ('not_connected', 'error'):
            text = 'Connect Account' if self._state == 'not_connected' else 'Retry'
            self._btn.config(text=text, state='normal')
            self._btn.pack()
        elif self._state == 'connecting':
            self._btn.config(state='disabled')
            self._btn.pack()
        else:
            self._btn.pack_forget()

    def _primary_action(self) -> None:
        if self._state == 'not_connected':
            self._set_state('connecting')
            threading.Thread(target=self._run_activation, daemon=True).start()
        elif self._state == 'error':
            self._set_state('not_connected')
            self._update_ui()

    def _run_activation(self) -> None:
        import platform as _platform
        token = auth.activate(device_name=_platform.node() or 'My PC')
        if token:
            self._adapter.store_credential(token)
            self._set_state('waiting')
            threading.Thread(target=self._run_agent, daemon=True).start()
        else:
            self._set_state('not_connected')

    def _emergency_stop(self) -> None:
        """Called immediately on lock/logout/disconnect. Stops recording."""
        session_server.force_stop()
        self._stop_event.set()
        self._set_state('idle')

    def _run_agent(self) -> None:
        import main as agent_main
        self._stop_event.clear()
        agent_main.main(state_callback=self._set_state, stop_event=self._stop_event)

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
            self._set_state('waiting')
            threading.Thread(target=self._run_agent, daemon=True).start()

        self._root.mainloop()


if __name__ == '__main__':
    WindowsApp().run()
