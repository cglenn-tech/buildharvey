"""
Windows entry point — tkinter UI with full recording state machine.

States:
  not_connected    → agent has no credential stored
  connecting       → activation flow in progress
  task_entry       → credential obtained, user enters case context to begin
  recording        → local recording active, timer running
  paused           → session active but timing paused (idle > 5 min)
  switch_suggestion → agent suggests switching to a new case
  daily_review     → session ended, showing today's totals
  stopping         → session being finalized
  error            → unexpected failure

The user clicks Start Task / Stop Work Session in this window.
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
import time
import tkinter as tk
from tkinter import ttk, simpledialog

from dotenv import load_dotenv
load_dotenv()

import auth
import database
import realtime_client
import task_context as tc
from os_adapters import Adapter


_ADMIN_SUBTYPES = [
    'Internal email', 'Scheduling', 'Meetings',
    'Training', 'General research', 'Reporting', 'Other',
]


def _fmt_elapsed(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _fmt_dur(minutes: float) -> str:
    h = int(minutes // 60)
    m = round(minutes % 60)
    if h == 0:
        return f"{m} min"
    if m == 0:
        return f"{h} hr"
    return f"{h} hr {m} min"


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
        self._session_start: float = 0.0
        self._timer_job = None

        self._root = tk.Tk()
        self._root.title('BuildHarvey')
        self._root.resizable(False, False)
        self._root.configure(padx=16, pady=12)

        self._build_ui()
        self._update_ui()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        root = self._root

        # ── not_connected / connecting / error ────────────────────────────────
        self._onboard_frame = ttk.Frame(root)
        self._onboard_label = ttk.Label(
            self._onboard_frame, text='', wraplength=380, justify='left'
        )
        self._onboard_label.pack(pady=(0, 10))
        self._onboard_btn = ttk.Button(
            self._onboard_frame, text='', command=self._primary_action
        )
        self._onboard_btn.pack()

        # ── task_entry ────────────────────────────────────────────────────────
        self._entry_frame = ttk.Frame(root)

        ttk.Label(self._entry_frame, text='Case / Matter:').grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 2)
        )
        self._case_var = tk.StringVar()
        self._case_combo = ttk.Combobox(
            self._entry_frame, textvariable=self._case_var, width=42
        )
        self._case_combo.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(0, 8))
        self._case_combo.bind('<<ComboboxSelected>>', self._on_case_selected)
        self._case_combo.bind('<FocusIn>', self._on_case_focus)

        ttk.Label(self._entry_frame, text='Issue / Task (optional):').grid(
            row=2, column=0, columnspan=2, sticky='w', pady=(0, 2)
        )
        self._issue_var = tk.StringVar()
        self._issue_combo = ttk.Combobox(
            self._entry_frame, textvariable=self._issue_var, width=42
        )
        self._issue_combo.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(0, 12))

        btn_frame = ttk.Frame(self._entry_frame)
        btn_frame.grid(row=4, column=0, columnspan=2, sticky='w')

        ttk.Button(btn_frame, text='Start Task', command=self._start_task).pack(
            side='left', padx=(0, 8)
        )

        admin_frame = ttk.LabelFrame(self._entry_frame, text='Administrative Work', padding=6)
        admin_frame.grid(row=5, column=0, columnspan=2, sticky='ew', pady=(10, 0))

        self._admin_var = tk.StringVar(value=_ADMIN_SUBTYPES[0])
        admin_combo = ttk.Combobox(
            admin_frame, textvariable=self._admin_var,
            values=_ADMIN_SUBTYPES, state='readonly', width=30
        )
        admin_combo.pack(side='left', padx=(0, 8))
        ttk.Button(admin_frame, text='Start', command=self._admin_work).pack(side='left')

        # ── recording / paused ────────────────────────────────────────────────
        self._rec_frame = ttk.Frame(root)

        self._rec_case_var = tk.StringVar()
        ttk.Label(self._rec_frame, textvariable=self._rec_case_var,
                  font=('TkDefaultFont', 11, 'bold'), wraplength=380).pack(anchor='w')

        self._rec_issue_var = tk.StringVar()
        ttk.Label(self._rec_frame, textvariable=self._rec_issue_var,
                  foreground='gray').pack(anchor='w')

        self._timer_var = tk.StringVar(value='00:00')
        ttk.Label(self._rec_frame, textvariable=self._timer_var,
                  font=('Courier', 20, 'bold')).pack(anchor='w', pady=(4, 0))

        self._activity_var = tk.StringVar()
        ttk.Label(self._rec_frame, textvariable=self._activity_var,
                  foreground='gray', wraplength=380).pack(anchor='w', pady=(2, 8))

        rec_btn_frame = ttk.Frame(self._rec_frame)
        rec_btn_frame.pack(anchor='w')
        ttk.Button(rec_btn_frame, text='Switch Task', command=self._switch_task).pack(
            side='left', padx=(0, 6)
        )
        ttk.Button(rec_btn_frame, text='Stop Task', command=self._stop_task).pack(
            side='left', padx=(0, 6)
        )
        ttk.Button(rec_btn_frame, text='Stop Work Session', command=self._stop_session).pack(
            side='left'
        )

        # ── switch_suggestion ─────────────────────────────────────────────────
        self._suggest_frame = ttk.Frame(root)

        self._suggest_var = tk.StringVar()
        ttk.Label(self._suggest_frame, textvariable=self._suggest_var,
                  wraplength=380, justify='left').pack(anchor='w', pady=(0, 10))

        sug_btn_frame = ttk.Frame(self._suggest_frame)
        sug_btn_frame.pack(anchor='w')
        ttk.Button(sug_btn_frame, text='Switch', command=self._confirm_switch).pack(
            side='left', padx=(0, 6)
        )
        ttk.Button(sug_btn_frame, text='Stay', command=self._stay_on_task).pack(
            side='left', padx=(0, 6)
        )
        ttk.Button(sug_btn_frame, text='Choose other…', command=self._choose_other).pack(
            side='left'
        )

        # ── daily_review ──────────────────────────────────────────────────────
        self._review_frame = ttk.Frame(root)

        self._review_var = tk.StringVar()
        ttk.Label(self._review_frame, textvariable=self._review_var,
                  justify='left', wraplength=380).pack(anchor='w', pady=(0, 10))

        ttk.Button(self._review_frame, text='Done', command=self._done_review).pack(anchor='w')

    # ── State machine ──────────────────────────────────────────────────────────

    def _set_state(self, state: str) -> None:
        self._state = state
        self._root.after(0, self._update_ui)

    def _update_ui(self) -> None:
        state = self._state

        # Hide all frames
        for frame in (self._onboard_frame, self._entry_frame,
                      self._rec_frame, self._suggest_frame, self._review_frame):
            frame.pack_forget()

        if state in ('not_connected', 'connecting', 'stopping', 'error'):
            self._render_onboard(state)
            self._root.geometry('440x140')
        elif state == 'task_entry':
            self._render_task_entry()
            self._root.geometry('440x360')
        elif state in ('recording', 'paused'):
            self._render_recording(state)
            self._root.geometry('440x220')
        elif state == 'switch_suggestion':
            self._render_switch_suggestion()
            self._root.geometry('440x180')
        elif state == 'daily_review':
            self._render_daily_review()
            self._root.geometry('440x280')

    def _render_onboard(self, state: str):
        _LABELS = {
            'not_connected': 'Connect your BuildHarvey account to get started.',
            'connecting':    'Opening browser for account connection…',
            'stopping':      'Finishing session…',
            'error':         'Error — see log for details.',
        }
        _BUTTONS = {
            'not_connected': 'Connect Account',
            'error':         'Retry',
        }
        self._onboard_label.configure(text=_LABELS.get(state, state))
        btn_text = _BUTTONS.get(state)
        if btn_text:
            self._onboard_btn.configure(text=btn_text, state='normal')
            self._onboard_btn.pack()
        else:
            self._onboard_btn.pack_forget()
        self._onboard_frame.pack(fill='both', expand=True)

    def _render_task_entry(self):
        # Refresh case list from DB
        try:
            conn = database.connect()
            cases = database.get_recent_cases(conn)
            conn.close()
            self._case_combo['values'] = cases
        except Exception:
            pass
        self._entry_frame.pack(fill='both', expand=True)

    def _render_recording(self, state: str):
        ctx = tc.get_context()
        self._rec_case_var.set(ctx.case_name or 'Recording…')
        self._rec_issue_var.set(ctx.issue_worked_on or '')
        if state == 'paused':
            self._stop_timer()
            self._timer_var.set('⏸ Paused')
        else:
            self._start_timer()
        self._activity_var.set(tc.get_latest_activity())
        self._rec_frame.pack(fill='both', expand=True)

    def _render_switch_suggestion(self):
        candidate = tc.get_switch_suggestion()
        self._suggest_var.set(
            f'It looks like you moved to:\n"{candidate}"\n\nSwitch to this case?'
        )
        self._suggest_frame.pack(fill='both', expand=True)

    def _render_daily_review(self):
        summary = self._read_today_summary()
        self._review_var.set(summary)
        self._review_frame.pack(fill='both', expand=True)

    def _read_today_summary(self) -> str:
        try:
            today = time.strftime("%Y-%m-%d", time.gmtime())
            conn = database.connect()
            rows = conn.execute(
                "SELECT case_name, work_type, duration_minutes FROM episodes "
                "WHERE started_at LIKE ? AND is_reportable = 1",
                (today + '%',)
            ).fetchall()
            conn.close()
        except Exception:
            return "Today's summary unavailable."

        if not rows:
            return "No sessions recorded today."

        project_totals: dict[str, float] = {}
        admin_total = 0.0
        for case_name, work_type, dur in rows:
            dur = dur or 0.0
            if work_type == 'administrative':
                admin_total += dur
            else:
                k = (case_name or 'Unknown').strip()
                project_totals[k] = project_totals.get(k, 0.0) + dur

        lines = ["Today's Work Summary", ""]
        for name, mins in sorted(project_totals.items(), key=lambda x: -x[1]):
            lines.append(f"  {name}: {_fmt_dur(mins)}")
        if admin_total > 0:
            lines.append(f"  Administrative: {_fmt_dur(admin_total)}")
        grand = sum(project_totals.values()) + admin_total
        lines.append("")
        lines.append(f"Total: {_fmt_dur(grand)}")
        return "\n".join(lines)

    # ── Timer ──────────────────────────────────────────────────────────────────

    def _start_timer(self):
        if self._timer_job is not None:
            return
        self._tick()

    def _stop_timer(self):
        if self._timer_job is not None:
            self._root.after_cancel(self._timer_job)
            self._timer_job = None

    def _tick(self):
        if self._state == 'recording':
            elapsed = time.time() - (self._session_start or time.time())
            self._timer_var.set(_fmt_elapsed(elapsed))
            self._activity_var.set(tc.get_latest_activity())
        self._timer_job = self._root.after(1000, self._tick)

    # ── Button actions ─────────────────────────────────────────────────────────

    def _primary_action(self) -> None:
        state = self._state
        if state == 'not_connected':
            self._set_state('connecting')
            threading.Thread(target=self._run_activation, daemon=True).start()
        elif state == 'error':
            self._set_state('not_connected')

    def _on_case_focus(self, event=None):
        """Refresh case list on focus."""
        try:
            conn = database.connect()
            cases = database.get_recent_cases(conn)
            conn.close()
            self._case_combo['values'] = cases
        except Exception:
            pass

    def _on_case_selected(self, event=None):
        """Populate issue list when case is selected."""
        case = self._case_var.get()
        if not case:
            return
        try:
            conn = database.connect()
            issues = database.get_recent_issues(conn, case)
            conn.close()
            self._issue_combo['values'] = issues
        except Exception:
            pass

    def _start_task(self) -> None:
        case = self._case_var.get().strip()
        issue = self._issue_var.get().strip()
        if not case:
            self._case_combo.focus_set()
            return
        tc.set_context(case, issue, 'project')
        self._session_start = time.time()
        realtime_client.start_local()
        self._set_state('recording')

    def _admin_work(self) -> None:
        subtype = self._admin_var.get() or 'Other'
        tc.set_context('Administrative', subtype, 'administrative')
        self._session_start = time.time()
        realtime_client.start_local()
        self._set_state('recording')

    def _switch_task(self) -> None:
        """Finalize current episode and go back to task_entry for a new case."""
        self._stop_timer()
        tc.request_force_stop()
        tc.clear_context()
        self._set_state('task_entry')

    def _stop_task(self) -> None:
        """Finalize the current episode, keep session running, return to task_entry."""
        self._stop_timer()
        tc.request_force_stop()
        tc.clear_context()
        self._set_state('task_entry')

    def _stop_session(self) -> None:
        """Finalize and show daily review."""
        self._stop_timer()
        tc.request_force_stop()
        self._set_state('stopping')

    def _confirm_switch(self) -> None:
        tc.request_confirm_switch("")
        self._session_start = time.time()
        self._set_state('recording')

    def _stay_on_task(self) -> None:
        tc.request_reject_switch()
        self._set_state('recording')

    def _choose_other(self) -> None:
        """Ask user for a different case name."""
        name = simpledialog.askstring(
            "Switch to…", "Enter case / matter name:", parent=self._root
        )
        if name and name.strip():
            tc.set_context(name.strip(), '', 'project')
            tc.request_confirm_switch(name.strip())
            self._session_start = time.time()
            self._set_state('recording')
        else:
            tc.request_reject_switch()
            self._set_state('recording')

    def _done_review(self) -> None:
        tc.clear_context()
        self._set_state('task_entry')

    # ── Agent state callback ───────────────────────────────────────────────────

    def _agent_state_update(self, state: str) -> None:
        """Called from main.py state_callback."""
        current = self._state
        if state == 'idle' and current in ('stopping', 'recording', 'paused', 'switch_suggestion'):
            self._set_state('task_entry')
        elif state == 'daily_review':
            self._set_state('daily_review')
        elif state == 'paused' and current in ('recording', 'paused'):
            self._set_state('paused')
        elif state == 'recording' and current == 'paused':
            self._set_state('recording')
        elif state.startswith('switch_suggestion:') and current in ('recording', 'paused'):
            self._set_state('switch_suggestion')

    # ── Activation / agent ────────────────────────────────────────────────────

    def _run_activation(self) -> None:
        import platform as _platform
        token = auth.activate(device_name=_platform.node() or 'My PC')
        if token:
            self._adapter.store_credential(token)
            self._set_state('task_entry')
            threading.Thread(target=self._run_agent, daemon=True).start()
        else:
            self._set_state('not_connected')

    def _emergency_stop(self) -> None:
        """Called immediately on lock/logout/disconnect. Stops recording."""
        realtime_client.force_stop()
        self._stop_event.set()
        self._stop_timer()
        self._set_state('task_entry')

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
            self._set_state('task_entry')
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
        sys.exit(0)

    if args.self_test:
        sys.exit(run_self_test())

    WindowsApp().run()
