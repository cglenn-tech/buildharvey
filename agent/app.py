"""
BuildHarvey macOS app entry point.

Shows an onboarding/control window (PyObjC/AppKit), then launches the main
capture loop in a background thread once a credential is obtained
and screen capture permission is granted.

States:
  connect_account    → no credential stored
  connecting         → activation flow in progress
  permission_required → credential ok, no screen capture permission
  waiting_permission → permission dialog shown, waiting
  restart_required   → permission granted but restart needed
  ready_to_start     → agent running, waiting for user to start a session
  recording          → session active, recording work
  stopping           → session being finalized
"""
import threading

from dotenv import load_dotenv
load_dotenv()

import AppKit
import objc
import auth
import permissions
import realtime_client


_LABELS = {
    'connect_account':    'Connect your BuildHarvey account to get started.',
    'connecting':         'Opening browser — approve the connection request.',
    'permission_required': 'BuildHarvey needs Screen Recording permission to capture your work.',
    'waiting_permission': 'Grant Screen Recording permission in System Settings, then click Continue.',
    'restart_required':   'Permission granted. Please restart BuildHarvey to begin capturing.',
    'ready_to_start':     'Ready to start. Click Start Work Session to begin capturing your work.',
    'recording':          'BuildHarvey is recording your work.',
    'stopping':           'Finishing session…',
}

_PRIMARY_BUTTONS = {
    'connect_account':    'Connect Account',
    'permission_required': 'Grant Permission',
    'waiting_permission': 'Continue',
    'ready_to_start':     'Start Work Session',
    'recording':          'Stop Work Session',
}


class OnboardingController(AppKit.NSObject):
    """Manages the onboarding/control window and state transitions."""

    window = objc.ivar()
    label = objc.ivar()
    button = objc.ivar()
    _state = objc.ivar()

    def init(self):
        self = objc.super(OnboardingController, self).init()
        if self is None:
            return None
        self._state = 'connect_account'
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
            rect,
            style,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_('BuildHarvey')
        self.window.center()

        content = self.window.contentView()

        self.label = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(20, 80, 380, 60)
        )
        self.label.setBezeled_(False)
        self.label.setDrawsBackground_(False)
        self.label.setEditable_(False)
        self.label.setSelectable_(False)
        self.label.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
        content.addSubview_(self.label)

        self.button = AppKit.NSButton.alloc().initWithFrame_(
            AppKit.NSMakeRect(20, 30, 200, 32)
        )
        self.button.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self.button.setTarget_(self)
        self.button.setAction_(objc.selector(self.primaryAction_, signature=b'v@:@'))
        content.addSubview_(self.button)

        self._render()
        self.window.makeKeyAndOrderFront_(None)

    def _render(self):
        state = self._state
        label_text = _LABELS.get(state, state)
        self.label.setStringValue_(label_text)

        btn_title = _PRIMARY_BUTTONS.get(state)
        if btn_title:
            self.button.setTitle_(btn_title)
            self.button.setHidden_(False)
            self.button.setEnabled_(state not in ('connecting', 'stopping'))
        else:
            self.button.setHidden_(True)

    def _set_state(self, state):
        self._state = state
        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(self._render)

    def primaryAction_(self, sender):
        state = self._state
        if state == 'connect_account':
            self._set_state('connecting')
            threading.Thread(target=self._run_activation, daemon=True).start()
        elif state in ('permission_required', 'waiting_permission'):
            self._check_or_request_permission()
        elif state == 'ready_to_start':
            self._set_state('recording')
            realtime_client.start_local()
        elif state == 'recording':
            self._set_state('stopping')
            realtime_client.stop_local()
            # UI will transition back to ready_to_start via agent state callback

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
            self._set_state('ready_to_start')
            AppKit.NSApp.delegate().startAgent()
        else:
            self._set_state('permission_required')

    def _check_or_request_permission(self):
        if self._state == 'waiting_permission':
            status = permissions.check()
            if status == 'GRANTED':
                self._set_state('ready_to_start')
                AppKit.NSApp.delegate().startAgent()
            else:
                self._set_state('restart_required')
        else:
            permissions.open_system_prefs()
            result = permissions.request()
            if result == 'GRANTED':
                self._set_state('ready_to_start')
                AppKit.NSApp.delegate().startAgent()
            else:
                self._set_state('waiting_permission')


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
                self._show_onboarding('ready_to_start')
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
            self._onboarding._set_state('ready_to_start')

    def _show_onboarding(self, initial_state='connect_account'):
        self._onboarding = OnboardingController.alloc().init()
        self._onboarding._set_state(initial_state)

    def _on_agent_state(self, state: str) -> None:
        """Called from main.py state_callback. Updates the UI on the main thread."""
        if self._onboarding is None:
            return

        def update():
            current = self._onboarding._state
            if state == 'idle' and current in ('recording', 'stopping'):
                self._onboarding._set_state('ready_to_start')
            # 'recording' and 'waiting' states are handled by button clicks;
            # we don't override here so the UI stays responsive.

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
