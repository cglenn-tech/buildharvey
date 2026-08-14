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
import Foundation
import objc
import auth
import permissions
import realtime_client

# Apple Event constants for URL scheme handling
_kInternetEventClass = 0x4755524C  # 'GURL'
_kAEGetURL = 0x4755524C            # 'GURL'


class AppDelegate(AppKit.NSObject):

    _stop_event = objc.ivar()
    _status_item = objc.ivar()
    _label_item = objc.ivar()
    _connect_item = objc.ivar()

    def applicationDidFinishLaunching_(self, notification):
        # No Dock icon — pure menu-bar accessory
        AppKit.NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

        # Register URL scheme handler for buildharvey:// deep links
        em = AppKit.NSAppleEventManager.sharedAppleEventManager()
        em.setEventHandler_andSelector_forEventClass_andEventID_(
            self,
            objc.selector(self.handleGetURL_withReplyEvent_, signature=b'v@:@@'),
            _kInternetEventClass,
            _kAEGetURL,
        )

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

        disconnect_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Disconnect Account", "disconnectAccount:", ""
        )
        disconnect_item.setTarget_(self)
        menu.addItem_(disconnect_item)
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

        # ── Sleep / session-resign / screen-lock notifications ────────────────
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
        # Screen lock (separate from sleep): NSWorkspaceScreensDidSleepNotification
        nc.addObserver_selector_name_object_(
            self,
            objc.selector(self.workspaceScreenLocked_, signature=b'v@:@'),
            AppKit.NSWorkspaceScreensDidSleepNotification,
            None,
        )

        # ── Credential and permission check, then start ────────────────────────
        threading.Thread(target=self._startup, daemon=True).start()

    def openDashboard_(self, sender):
        webbrowser.open("https://buildharvey.com")

    def workspaceSleep_(self, notification):
        self._on_security_boundary("device_locked")

    def workspaceSessionResign_(self, notification):
        self._on_security_boundary("user_logged_out")

    def workspaceScreenLocked_(self, notification):
        self._on_security_boundary("device_locked")

    def _on_security_boundary(self, reason: str) -> None:
        """
        Called at every security boundary crossing (sleep, lock, logout).
        Phase 1: invalidates all capture leases so re-consent is required on resume.
        Always stops the agent loop.
        """
        import config
        if config.ENABLE_CAPTURE_LEASES:
            # Notify the agent loop to invalidate leases via the shared event;
            # ConsentManager.invalidate_all() is called inside the agent loop
            # on next wake via the session epoch stored in SQLite.
            # We also set a flag so the next startup knows to show batch re-consent.
            try:
                import database
                conn = database.connect()
                conn.execute(
                    "INSERT INTO session_state (key, value) VALUES ('boundary_reason', ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (reason,),
                )
                conn.commit()
            except Exception:
                pass
        self._emergency_stop()

    def _emergency_stop(self):
        realtime_client.force_stop()
        self._stop_event.set()

    def _get_display_name(self) -> str:
        try:
            import subprocess
            r = subprocess.run(
                ['scutil', '--get', 'ComputerName'],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            pass
        import platform
        return platform.node() or 'My Mac'

    def _startup(self):
        """Run credential check, permission check, then start the agent."""
        # 1. Ensure credential
        if not auth.read_credential():
            device_name = self._get_display_name()
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

    def disconnectAccount_(self, sender):
        """Revoke device on server and clear local credential."""
        realtime_client.force_stop()
        auth.disconnect()
        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
            lambda: self._label_item.setTitle_("BuildHarvey: Disconnected")
        )

    def handleGetURL_withReplyEvent_(self, event, replyEvent):
        """Handle buildharvey:// URL scheme events sent by macOS."""
        url_desc = event.paramDescriptorForKeyword_(0x2d2d2d2d)  # keyDirectObject
        if url_desc is None:
            return
        url_str = url_desc.stringValue()
        if not url_str:
            return
        print(f"[app] URL event: {url_str}")
        if url_str.startswith('buildharvey://disconnect'):
            threading.Thread(target=self.disconnectAccount_, args=(None,), daemon=True).start()
        elif url_str.startswith('buildharvey://reconnect'):
            auth.delete_credential()
            threading.Thread(target=self._startup, daemon=True).start()
        # buildharvey://open — no action needed; macOS already foregrounded the app

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
