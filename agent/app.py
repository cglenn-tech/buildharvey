"""
BuildHarvey macOS app entry point.

Shows an onboarding/control window (PyObjC/AppKit), then launches the main
capture loop in a background thread once a credential is obtained
and screen capture permission is granted.

States:
  connect_account     → no credential stored
  connecting          → activation flow in progress
  permission_required → credential ok, no screen capture permission
  waiting_permission  → permission dialog shown, waiting
  restart_required    → permission granted but restart needed
  task_entry          → agent running, user enters case context to begin
  recording           → session active, timer running
  paused              → session active but timing paused (idle > 5 min)
  switch_suggestion   → agent suggests switching to a new case
  daily_review        → session ended, showing today's totals
  stopping            → session being finalized
"""
import threading
import time

from dotenv import load_dotenv
load_dotenv()

import AppKit
import objc
import auth
import database
import permissions
import realtime_client
import task_context as tc


_ADMIN_SUBTYPES = [
    'Internal email',
    'Scheduling',
    'Meetings',
    'Training',
    'General research',
    'Reporting',
    'Other',
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


class OnboardingController(AppKit.NSObject):
    """Manages the onboarding/control window and state transitions."""

    window = objc.ivar()
    _state = objc.ivar()

    # Subviews — built once, shown/hidden per state
    _label = objc.ivar()           # general status label (onboarding states)
    _btn_primary = objc.ivar()     # primary action button

    # task_entry views
    _case_combo = objc.ivar()
    _issue_combo = objc.ivar()
    _case_label_static = objc.ivar()
    _issue_label_static = objc.ivar()
    _btn_start_task = objc.ivar()
    _btn_admin = objc.ivar()
    _admin_popup = objc.ivar()

    # recording / paused views
    _case_display = objc.ivar()
    _issue_display = objc.ivar()
    _timer_label = objc.ivar()
    _activity_label = objc.ivar()
    _btn_switch = objc.ivar()
    _btn_stop_task = objc.ivar()
    _btn_stop_session = objc.ivar()
    _ns_timer = objc.ivar()
    _session_start = objc.ivar()

    # switch_suggestion views
    _suggestion_label = objc.ivar()
    _btn_switch_confirm = objc.ivar()
    _btn_stay = objc.ivar()
    _btn_choose_other = objc.ivar()

    # daily_review views
    _review_label = objc.ivar()
    _btn_done = objc.ivar()

    def init(self):
        self = objc.super(OnboardingController, self).init()
        if self is None:
            return None
        self._state = 'connect_account'
        self._session_start = 0.0
        self._build_window()
        return self

    def _build_window(self):
        rect = AppKit.NSMakeRect(0, 0, 420, 160)
        style = (
            AppKit.NSWindowStyleMaskTitled
            | AppKit.NSWindowStyleMaskClosable
            | AppKit.NSWindowStyleMaskMiniaturizable
        )
        self.window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, AppKit.NSBackingStoreBuffered, False,
        )
        self.window.setTitle_('BuildHarvey')
        self.window.center()
        content = self.window.contentView()

        # ── Onboarding / status label ─────────────────────────────────────────
        self._label = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(20, 80, 380, 60)
        )
        self._label.setBezeled_(False)
        self._label.setDrawsBackground_(False)
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        self._label.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
        content.addSubview_(self._label)

        # Primary button (onboarding states)
        self._btn_primary = AppKit.NSButton.alloc().initWithFrame_(
            AppKit.NSMakeRect(20, 30, 200, 32)
        )
        self._btn_primary.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self._btn_primary.setTarget_(self)
        self._btn_primary.setAction_(objc.selector(self._primaryAction_, signature=b'v@:@'))
        content.addSubview_(self._btn_primary)

        # ── task_entry views ──────────────────────────────────────────────────
        self._case_label_static = _make_label(content, "Case / Matter:", AppKit.NSMakeRect(20, 280, 120, 20))
        self._case_combo = _make_combo(content, AppKit.NSMakeRect(20, 255, 380, 26))
        self._case_combo.setTarget_(self)
        self._case_combo.setAction_(objc.selector(self._caseChanged_, signature=b'v@:@'))

        self._issue_label_static = _make_label(content, "Issue / Task (optional):", AppKit.NSMakeRect(20, 225, 180, 20))
        self._issue_combo = _make_combo(content, AppKit.NSMakeRect(20, 200, 380, 26))

        self._btn_start_task = _make_button(
            content, "Start Task", AppKit.NSMakeRect(20, 155, 160, 32),
            self, objc.selector(self._startTask_, signature=b'v@:@')
        )

        self._btn_admin = _make_button(
            content, "Administrative Work", AppKit.NSMakeRect(190, 155, 200, 32),
            self, objc.selector(self._adminWork_, signature=b'v@:@')
        )

        self._admin_popup = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
            AppKit.NSMakeRect(20, 110, 380, 26), False
        )
        for item in _ADMIN_SUBTYPES:
            self._admin_popup.addItemWithTitle_(item)
        content.addSubview_(self._admin_popup)

        # ── recording / paused views ──────────────────────────────────────────
        self._case_display = _make_label(content, "", AppKit.NSMakeRect(20, 370, 380, 20))
        font_bold = AppKit.NSFont.boldSystemFontOfSize_(13)
        self._case_display.setFont_(font_bold)

        self._issue_display = _make_label(content, "", AppKit.NSMakeRect(20, 345, 380, 20))
        self._issue_display.setTextColor_(AppKit.NSColor.secondaryLabelColor())

        self._timer_label = _make_label(content, "00:00", AppKit.NSMakeRect(20, 315, 200, 28))
        font_mono = AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_(22, AppKit.NSFontWeightMedium)
        self._timer_label.setFont_(font_mono)

        self._activity_label = _make_label(content, "", AppKit.NSMakeRect(20, 285, 380, 20))
        self._activity_label.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        self._activity_label.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)

        self._btn_switch = _make_button(
            content, "Switch Task", AppKit.NSMakeRect(20, 240, 130, 32),
            self, objc.selector(self._switchTask_, signature=b'v@:@')
        )
        self._btn_stop_task = _make_button(
            content, "Stop Task", AppKit.NSMakeRect(160, 240, 120, 32),
            self, objc.selector(self._stopTask_, signature=b'v@:@')
        )
        self._btn_stop_session = _make_button(
            content, "Stop Work Session", AppKit.NSMakeRect(290, 240, 150, 32),
            self, objc.selector(self._stopSession_, signature=b'v@:@')
        )

        # ── switch_suggestion views ───────────────────────────────────────────
        self._suggestion_label = _make_label(content, "", AppKit.NSMakeRect(20, 365, 380, 40))
        self._suggestion_label.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)

        self._btn_switch_confirm = _make_button(
            content, "Switch", AppKit.NSMakeRect(20, 315, 100, 32),
            self, objc.selector(self._confirmSwitch_, signature=b'v@:@')
        )
        self._btn_stay = _make_button(
            content, "Stay", AppKit.NSMakeRect(130, 315, 100, 32),
            self, objc.selector(self._stayOnTask_, signature=b'v@:@')
        )
        self._btn_choose_other = _make_button(
            content, "Choose other…", AppKit.NSMakeRect(240, 315, 140, 32),
            self, objc.selector(self._chooseOther_, signature=b'v@:@')
        )

        # ── daily_review views ────────────────────────────────────────────────
        self._review_label = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(20, 280, 380, 80)
        )
        self._review_label.setBezeled_(False)
        self._review_label.setDrawsBackground_(False)
        self._review_label.setEditable_(False)
        self._review_label.setSelectable_(False)
        self._review_label.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
        content.addSubview_(self._review_label)

        self._btn_done = _make_button(
            content, "Done", AppKit.NSMakeRect(20, 235, 100, 32),
            self, objc.selector(self._doneReview_, signature=b'v@:@')
        )

        self._render()
        self.window.makeKeyAndOrderFront_(None)

    def _all_subviews(self):
        return [
            self._label, self._btn_primary,
            self._case_label_static, self._case_combo,
            self._issue_label_static, self._issue_combo,
            self._btn_start_task, self._btn_admin, self._admin_popup,
            self._case_display, self._issue_display,
            self._timer_label, self._activity_label,
            self._btn_switch, self._btn_stop_task, self._btn_stop_session,
            self._suggestion_label,
            self._btn_switch_confirm, self._btn_stay, self._btn_choose_other,
            self._review_label, self._btn_done,
        ]

    def _render(self):
        state = self._state
        # Hide all subviews first
        for v in self._all_subviews():
            if v is not None:
                v.setHidden_(True)

        if state in ('connect_account', 'connecting', 'permission_required',
                     'waiting_permission', 'restart_required', 'stopping'):
            self._render_onboarding(state)
        elif state == 'task_entry':
            self._render_task_entry()
        elif state in ('recording', 'paused'):
            self._render_recording(state)
        elif state == 'switch_suggestion':
            self._render_switch_suggestion()
        elif state == 'daily_review':
            self._render_daily_review()

    def _render_onboarding(self, state: str):
        _LABELS = {
            'connect_account':    'Connect your BuildHarvey account to get started.',
            'connecting':         'Opening browser — approve the connection request.',
            'permission_required': 'BuildHarvey needs Screen Recording permission to capture your work.',
            'waiting_permission': 'Grant Screen Recording permission in System Settings, then click Continue.',
            'restart_required':   'Permission granted. Please restart BuildHarvey to begin capturing.',
            'stopping':           'Finishing session…',
        }
        _BUTTONS = {
            'connect_account':    'Connect Account',
            'permission_required': 'Grant Permission',
            'waiting_permission': 'Continue',
        }
        self.window.setContentSize_(AppKit.NSMakeSize(420, 160))
        self._label.setStringValue_(_LABELS.get(state, state))
        self._label.setHidden_(False)
        btn_title = _BUTTONS.get(state)
        if btn_title:
            self._btn_primary.setTitle_(btn_title)
            self._btn_primary.setEnabled_(True)
            self._btn_primary.setHidden_(False)

    def _render_task_entry(self):
        self.window.setContentSize_(AppKit.NSMakeSize(420, 340))
        for v in [self._case_label_static, self._case_combo,
                  self._issue_label_static, self._issue_combo,
                  self._btn_start_task, self._btn_admin, self._admin_popup]:
            v.setHidden_(False)
        # Populate case combo from recent contexts
        try:
            conn = database.connect()
            cases = database.get_recent_cases(conn)
            conn.close()
            self._case_combo.removeAllItems()
            if cases:
                self._case_combo.addItemsWithObjectValues_(cases)
        except Exception:
            pass

    def _render_recording(self, state: str):
        self.window.setContentSize_(AppKit.NSMakeSize(420, 420))
        ctx = tc.get_context()
        self._case_display.setStringValue_(ctx.case_name or "Recording…")
        issue = ctx.issue_worked_on or ""
        self._issue_display.setStringValue_(issue)

        for v in [self._case_display, self._issue_display,
                  self._timer_label, self._activity_label,
                  self._btn_switch, self._btn_stop_task, self._btn_stop_session]:
            v.setHidden_(False)

        if state == 'paused':
            self._timer_label.setStringValue_("⏸ Paused")
        else:
            self._tick_(None)  # update timer immediately
            if self._ns_timer is None:
                self._ns_timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    1.0, self, objc.selector(self._tick_, signature=b'v@:@'), None, True
                )

        self._activity_label.setStringValue_(tc.get_latest_activity())

    def _render_switch_suggestion(self):
        self.window.setContentSize_(AppKit.NSMakeSize(420, 420))
        candidate = tc.get_switch_suggestion()
        self._suggestion_label.setStringValue_(
            f"It looks like you moved to:\n\"{candidate}\"\n\nSwitch to this case?"
        )
        for v in [self._suggestion_label,
                  self._btn_switch_confirm, self._btn_stay, self._btn_choose_other]:
            v.setHidden_(False)

    def _render_daily_review(self):
        self.window.setContentSize_(AppKit.NSMakeSize(420, 360))
        # Read today's totals from SQLite
        summary = self._read_today_summary()
        self._review_label.setStringValue_(summary)
        self._review_label.setHidden_(False)
        self._btn_done.setHidden_(False)

    def _read_today_summary(self) -> str:
        try:
            import time as _time
            today = _time.strftime("%Y-%m-%d", _time.gmtime())
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
                k = (case_name or "Unknown").strip()
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

    def _set_state(self, state: str):
        self._state = state
        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(self._render)

    # ── Timer ──────────────────────────────────────────────────────────────────

    def _tick_(self, _timer):
        if self._state not in ('recording',):
            return
        elapsed = time.time() - (self._session_start or time.time())
        self._timer_label.setStringValue_(_fmt_elapsed(elapsed))
        # Update activity label
        self._activity_label.setStringValue_(tc.get_latest_activity())

    def _stop_timer(self):
        if self._ns_timer is not None:
            self._ns_timer.invalidate()
            self._ns_timer = None

    # ── Button actions ─────────────────────────────────────────────────────────

    def _primaryAction_(self, sender):
        """Handles onboarding state buttons."""
        state = self._state
        if state == 'connect_account':
            self._set_state('connecting')
            threading.Thread(target=self._run_activation, daemon=True).start()
        elif state in ('permission_required', 'waiting_permission'):
            self._check_or_request_permission()

    def _caseChanged_(self, sender):
        """Populate issue combo when case selection changes."""
        case = self._case_combo.stringValue()
        if not case:
            return
        try:
            conn = database.connect()
            issues = database.get_recent_issues(conn, case)
            conn.close()
            self._issue_combo.removeAllItems()
            if issues:
                self._issue_combo.addItemsWithObjectValues_(issues)
        except Exception:
            pass

    def _startTask_(self, sender):
        case = (self._case_combo.stringValue() or "").strip()
        issue = (self._issue_combo.stringValue() or "").strip()
        if not case:
            # Shake the combo to indicate required field
            self._case_combo.becomeFirstResponder()
            return
        tc.set_context(case, issue, 'project')
        self._session_start = time.time()
        realtime_client.start_local()
        self._set_state('recording')

    def _adminWork_(self, sender):
        subtype = self._admin_popup.titleOfSelectedItem() or 'Other'
        tc.set_context('Administrative', subtype, 'administrative')
        self._session_start = time.time()
        realtime_client.start_local()
        self._set_state('recording')

    def _switchTask_(self, sender):
        """User wants to manually switch to a new task (from recording state)."""
        # Stop current, prompt for new case via task_entry overlay
        # Simplest UX: transition to task_entry, user picks new case, new session opens
        self._stop_timer()
        tc.request_force_stop()   # finalize current episode
        tc.clear_context()
        self._set_state('task_entry')

    def _stopTask_(self, sender):
        """Finalize the current episode but keep the session running."""
        tc.request_force_stop()
        tc.clear_context()
        self._stop_timer()
        self._set_state('task_entry')

    def _stopSession_(self, sender):
        """Stop the entire work session and show daily review."""
        tc.request_force_stop()
        self._stop_timer()
        self._set_state('stopping')

    def _confirmSwitch_(self, sender):
        tc.request_confirm_switch("")
        self._set_state('recording')

    def _stayOnTask_(self, sender):
        tc.request_reject_switch()
        self._set_state('recording')

    def _chooseOther_(self, sender):
        """User wants to switch to a different case than the suggestion."""
        tc.request_reject_switch()
        tc.clear_context()
        self._stop_timer()
        self._set_state('task_entry')

    def _doneReview_(self, sender):
        tc.clear_context()
        self._set_state('task_entry')

    # ── Activation / permissions ───────────────────────────────────────────────

    def _run_activation(self):
        import platform as _platform
        device_name = _platform.node() or 'My Mac'
        token = auth.activate(device_name=device_name)
        if token:
            auth.store_credential(token)
            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                lambda: self._check_permissions()
            )
        else:
            self._set_state('connect_account')

    def _check_permissions(self):
        status = permissions.check()
        if status == 'GRANTED':
            self._set_state('task_entry')
            AppKit.NSApp.delegate().startAgent()
        else:
            self._set_state('permission_required')

    def _check_or_request_permission(self):
        if self._state == 'waiting_permission':
            status = permissions.check()
            if status == 'GRANTED':
                self._set_state('task_entry')
                AppKit.NSApp.delegate().startAgent()
            else:
                self._set_state('restart_required')
        else:
            permissions.open_system_prefs()
            result = permissions.request()
            if result == 'GRANTED':
                self._set_state('task_entry')
                AppKit.NSApp.delegate().startAgent()
            else:
                self._set_state('waiting_permission')


# ── Helpers for building AppKit views ─────────────────────────────────────────

def _make_label(parent, text: str, frame) -> AppKit.NSTextField:
    lbl = AppKit.NSTextField.alloc().initWithFrame_(frame)
    lbl.setStringValue_(text)
    lbl.setBezeled_(False)
    lbl.setDrawsBackground_(False)
    lbl.setEditable_(False)
    lbl.setSelectable_(False)
    parent.addSubview_(lbl)
    return lbl


def _make_combo(parent, frame) -> AppKit.NSComboBox:
    cb = AppKit.NSComboBox.alloc().initWithFrame_(frame)
    cb.setUsesDataSource_(False)
    cb.setCompletes_(True)
    cb.setNumberOfVisibleItems_(8)
    parent.addSubview_(cb)
    return cb


def _make_button(parent, title: str, frame, target, action) -> AppKit.NSButton:
    btn = AppKit.NSButton.alloc().initWithFrame_(frame)
    btn.setTitle_(title)
    btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
    btn.setTarget_(target)
    btn.setAction_(action)
    parent.addSubview_(btn)
    return btn


# ── App Delegate ───────────────────────────────────────────────────────────────

class AppDelegate(AppKit.NSObject):

    _onboarding = objc.ivar()
    _stop_event = objc.ivar()

    def applicationDidFinishLaunching_(self, notification):
        self._stop_event = threading.Event()

        # Register for macOS sleep and session-resign notifications
        nc = AppKit.NSWorkspace.sharedWorkspace().notificationCenter()
        nc.addObserver_selector_name_object_(
            self,
            objc.selector(self.workspaceSleep_, signature=b'v@:@'),
            AppKit.NSWorkspaceWillSleepNotification,
            None,
        )
        nc.addObserver_selector_name_object_(
            self,
            objc.selector(self.workspaceSessionResign_, signature=b'v@:@'),
            AppKit.NSWorkspaceSessionDidResignActiveNotification,
            None,
        )

        credential = auth.read_credential()
        if credential:
            status = permissions.check()
            if status == 'GRANTED':
                self._show_onboarding('task_entry')
                self.startAgent()
            else:
                self._show_onboarding('permission_required')
        else:
            self._show_onboarding('connect_account')

    def workspaceSleep_(self, notification):
        self._emergency_stop()

    def workspaceSessionResign_(self, notification):
        self._emergency_stop()

    def _emergency_stop(self):
        """Called on sleep or session resign. Stops recording immediately."""
        realtime_client.force_stop()
        if self._stop_event is not None:
            self._stop_event.set()
        if self._onboarding is not None:
            self._onboarding._stop_timer()
            self._onboarding._set_state('task_entry')

    def _show_onboarding(self, initial_state='connect_account'):
        self._onboarding = OnboardingController.alloc().init()
        self._onboarding._set_state(initial_state)

    def _on_agent_state(self, state: str) -> None:
        """Called from main.py state_callback. Updates the UI on the main thread."""
        if self._onboarding is None:
            return

        def update():
            current = self._onboarding._state
            if state == 'idle' and current in ('recording', 'paused', 'switch_suggestion', 'stopping'):
                self._onboarding._stop_timer()
                self._onboarding._set_state('task_entry')
            elif state == 'daily_review':
                self._onboarding._stop_timer()
                self._onboarding._set_state('daily_review')
            elif state == 'paused' and current in ('recording', 'paused'):
                self._onboarding._stop_timer()
                self._onboarding._set_state('paused')
            elif state == 'recording' and current == 'paused':
                self._onboarding._set_state('recording')
            elif state.startswith('switch_suggestion:') and current in ('recording', 'paused'):
                self._onboarding._set_state('switch_suggestion')
            # 'recording' and 'waiting' state changes during normal recording
            # are handled by button clicks; UI stays as-is otherwise.

        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(update)

    def startAgent(self):
        if self._stop_event is not None:
            self._stop_event.clear()
        threading.Thread(target=self._run_agent, daemon=True).start()

    def _run_agent(self):
        import main as agent_main
        agent_main.main(state_callback=self._on_agent_state, stop_event=self._stop_event)

    def applicationShouldTerminateAfterLastWindowClosed_(self, app):
        return False


def main():
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.new()
    app.setDelegate_(delegate)
    AppKit.NSApp.activateIgnoringOtherApps_(True)
    app.run()


if __name__ == '__main__':
    main()
