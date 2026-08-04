"""
BuildHarvey macOS app entry point — headless tray daemon.

Runs as a menu-bar (tray) app with no Dock icon and no GUI window.
All user-facing UI lives on buildharvey.com.

Startup flow:
  1. If no credential stored → call auth.activate() to register device and poll for approval.
  2. If screen recording permission not granted → show NSAlert + open System Settings.
  3. Launch the capture loop in a background thread.
  4. Register for macOS sleep/session-resign notifications → force-stop on sleep.

Menu bar icon:
  ⬛  idle
  🟢  recording
"""
import threading
import webbrowser

from dotenv import load_dotenv
load_dotenv()

import AppKit
import objc
import auth
import permissions
import realtime_client


class AppDelegate(AppKit.NSObject):

    _stop_event = objc.ivar()
    _status_item = objc.ivar()
    _label_item = objc.ivar()
    _connect_item = objc.ivar()

    def applicationDidFinishLaunching_(self, notification):
        # No Dock icon — pure menu-bar accessory
        AppKit.NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

        self._stop_event = threading.Event()

        # ── Menu bar status item ───────────────────────────────────────────────
        status_bar = AppKit.NSStatusBar.systemStatusBar()
        self._status_item = status_bar.statusItemWithLength_(
            AppKit.NSVariableStatusItemLength
        )
        self._status_item.button().setTitle_("⬛")

        menu = AppKit.NSMenu.alloc().init()

        self._label_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "BuildHarvey: Idle", None, ""
        )
        menu.addItem_(self._label_item)
        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        self._connect_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Connect Account…", "connectAccount:", ""
        )
        self._connect_item.setTarget_(self)
        menu.addItem_(self._connect_item)
        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        open_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open Dashboard", "openDashboard:", ""
        )
        open_item.setTarget_(self)
        menu.addItem_(open_item)
        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        quit_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit BuildHarvey", "terminate:", ""
        )
        menu.addItem_(quit_item)

        self._status_item.setMenu_(menu)

        # ── Sleep / session-resign notifications ──────────────────────────────
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

        # ── Credential and permission check, then start ────────────────────────
        threading.Thread(target=self._startup, daemon=True).start()

    def openDashboard_(self, sender):
        webbrowser.open("https://buildharvey.com")

    def workspaceSleep_(self, notification):
        self._emergency_stop()

    def workspaceSessionResign_(self, notification):
        self._emergency_stop()

    def _emergency_stop(self):
        realtime_client.force_stop()
        self._stop_event.set()

    def _startup(self):
        """Run credential check, permission check, then start the agent."""
        # 1. Ensure credential
        if not auth.read_credential():
            import platform as _platform
            device_name = _platform.node() or 'My Mac'
            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                lambda: self._label_item.setTitle_("BuildHarvey: Connecting…")
            )
            print(f"[app] No credential — activating device '{device_name}'")
            token = auth.activate(device_name=device_name)
            if not token:
                print("[app] Activation failed or timed out")
                AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                    lambda: self._label_item.setTitle_("BuildHarvey: Not connected")
                )
                return
            auth.store_credential(token)

        # 2. Check screen recording permission
        status = permissions.check()
        if status != 'GRANTED':
            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                self._prompt_permissions
            )
            return

        self.startAgent()

    def connectAccount_(self, sender):
        """Re-trigger activation if no credential is stored (e.g. after timeout)."""
        if auth.read_credential():
            return
        threading.Thread(target=self._startup, daemon=True).start()

    def _prompt_permissions(self):
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_("Screen Recording Required")
        alert.setInformativeText_(
            "BuildHarvey needs Screen Recording permission to capture your work. "
            "Click OK to open System Settings."
        )
        alert.addButtonWithTitle_("OK")
        alert.addButtonWithTitle_("Quit")
        response = alert.runModal()
        if response == AppKit.NSAlertFirstButtonReturn:
            permissions.open_system_prefs()
            # After the user grants permission the app must be restarted
        else:
            AppKit.NSApp.terminate_(None)

    def startAgent(self):
        self._stop_event.clear()
        threading.Thread(target=self._run_agent, daemon=True).start()

    def _run_agent(self):
        import main as agent_main
        agent_main.main(state_callback=self._on_agent_state, stop_event=self._stop_event)

    def _on_agent_state(self, state: str) -> None:
        """Called from main.py state_callback on the agent thread. Dispatches to main queue."""
        def update():
            if state == 'recording':
                self._status_item.button().setTitle_("🟢")
                self._label_item.setTitle_("BuildHarvey: Recording")
            else:
                self._status_item.button().setTitle_("⬛")
                self._label_item.setTitle_("BuildHarvey: Idle")

        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(update)

    def applicationShouldTerminateAfterLastWindowClosed_(self, app):
        return False


def main():
    app = AppKit.NSApplication.sharedApplication()
    delegate = AppDelegate.new()
    app.setDelegate_(delegate)
    app.run()


if __name__ == '__main__':
    main()
