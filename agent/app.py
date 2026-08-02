"""
BuildHarvey macOS app entry point.

Shows an onboarding window (PyObjC/AppKit), then launches the main
capture loop in a background thread once a credential is obtained
and screen capture permission is granted.

States:
  connect_account   → no credential stored
  connecting        → activation flow in progress
  permission_required → credential ok, no screen capture permission
  waiting_permission → permission dialog shown, waiting
  restart_required  → permission granted but restart needed
  ready             → all good, agent running
"""
import threading

from dotenv import load_dotenv
load_dotenv()

import AppKit
import objc
import auth
import permissions
import realtime_client


class OnboardingController(AppKit.NSObject):
    """Manages the onboarding window and state transitions."""

    window = objc.ivar()
    label = objc.ivar()
    button = objc.ivar()
    secondary_button = objc.ivar()
    _state = objc.ivar()

    def init(self):
        self = objc.super(OnboardingController, self).init()
        if self is None:
            return None
        self._state = 'connect_account'
        self._build_window()
        return self

    def _build_window(self):
        rect = AppKit.NSMakeRect(0, 0, 400, 200)
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
            AppKit.NSMakeRect(20, 100, 360, 60)
        )
        self.label.setBezeled_(False)
        self.label.setDrawsBackground_(False)
        self.label.setEditable_(False)
        self.label.setSelectable_(False)
        content.addSubview_(self.label)

        self.button = AppKit.NSButton.alloc().initWithFrame_(
            AppKit.NSMakeRect(20, 50, 160, 32)
        )
        self.button.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self.button.setTarget_(self)
        self.button.setAction_(objc.selector(self.primaryAction_, signature=b'v@:@'))
        content.addSubview_(self.button)

        self.secondary_button = AppKit.NSButton.alloc().initWithFrame_(
            AppKit.NSMakeRect(200, 50, 180, 32)
        )
        self.secondary_button.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self.secondary_button.setTarget_(self)
        self.secondary_button.setAction_(objc.selector(self.secondaryAction_, signature=b'v@:@'))
        content.addSubview_(self.secondary_button)

        self._render()
        self.window.makeKeyAndOrderFront_(None)

    def _render(self):
        state = self._state
        if state == 'connect_account':
            self.label.setStringValue_('Connect your BuildHarvey account to get started.')
            self.button.setTitle_('Connect Account')
            self.button.setHidden_(False)
            self.secondary_button.setHidden_(True)
        elif state == 'connecting':
            self.label.setStringValue_('Opening browser — approve the connection request.')
            self.button.setHidden_(True)
            self.secondary_button.setHidden_(True)
        elif state == 'permission_required':
            self.label.setStringValue_('BuildHarvey needs Screen Recording permission to capture your work.')
            self.button.setTitle_('Grant Permission')
            self.button.setHidden_(False)
            self.secondary_button.setHidden_(True)
        elif state == 'waiting_permission':
            self.label.setStringValue_('Grant Screen Recording permission in System Settings, then click Continue.')
            self.button.setTitle_('Continue')
            self.button.setHidden_(False)
            self.secondary_button.setHidden_(True)
        elif state == 'restart_required':
            self.label.setStringValue_('Permission granted. Please restart BuildHarvey to begin capturing.')
            self.button.setHidden_(True)
            self.secondary_button.setHidden_(True)
        elif state == 'ready':
            self.label.setStringValue_('BuildHarvey is running and capturing your work.')
            self.button.setHidden_(True)
            self.secondary_button.setHidden_(True)

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

    def secondaryAction_(self, sender):
        pass

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
            self._set_state('ready')
            self.window.orderOut_(None)
            AppKit.NSApp.delegate().startAgent()
        else:
            self._set_state('permission_required')

    def _check_or_request_permission(self):
        if self._state == 'waiting_permission':
            status = permissions.check()
            if status == 'GRANTED':
                self._set_state('ready')
                self.window.orderOut_(None)
                AppKit.NSApp.delegate().startAgent()
            else:
                self._set_state('restart_required')
        else:
            permissions.open_system_prefs()
            result = permissions.request()
            if result == 'GRANTED':
                self._set_state('ready')
                self.window.orderOut_(None)
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

    def _show_onboarding(self, initial_state='connect_account'):
        self._onboarding = OnboardingController.alloc().init()
        self._onboarding._set_state(initial_state)

    def startAgent(self):
        if self._stop_event is not None:
            self._stop_event.clear()
        threading.Thread(target=self._run_agent, daemon=True).start()

    def _run_agent(self):
        import main as agent_main
        agent_main.main(stop_event=self._stop_event)

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
