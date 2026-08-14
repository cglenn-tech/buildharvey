"""
Capture Lease Model — Phase 1 of the privacy architecture.

ConsentManager enforces per-window consent before any observation is recorded.
Each window must be individually authorized. Authorization is invalidated at
every security boundary crossing (lock, logout, restart, crash recovery).

State Machine per window:
  UNAUTHORIZED          → window encountered; no BuildHarvey decision
  PENDING_INDIVIDUAL    → individual consent dialog shown, awaiting user response
  AUTHORIZED            → user allowed; capture proceeds
  DECLINED              → user denied or dialog timed out; capture blocked
  TERMINATED            → window no longer exists; lease retained for audit history
  INVALIDATED           → security boundary crossed (lock/logout/restart/crash)
  AWAITING_BATCH_RECONSENT → returned from boundary; batch UI pending

Invariant: privacy fails closed. Timeout in any consent UI → DECLINED.
Invariant: newly created windows always require individual authorization,
           regardless of batch re-consent outcome.

This module is feature-flagged: ENABLE_CAPTURE_LEASES=false bypasses all
consent logic and falls back to the pre-Phase-1 behavior (all windows allowed).
"""
import platform
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import config
from window_identity import WindowIdentity


# ── Lease states ──────────────────────────────────────────────────────────────

class LeaseState:
    UNAUTHORIZED           = "UNAUTHORIZED"
    PENDING_INDIVIDUAL     = "PENDING_INDIVIDUAL"
    AUTHORIZED             = "AUTHORIZED"
    DECLINED               = "DECLINED"
    TERMINATED             = "TERMINATED"
    INVALIDATED            = "INVALIDATED"
    AWAITING_BATCH_RECONSENT = "AWAITING_BATCH_RECONSENT"


@dataclass
class CaptureLease:
    """In-memory representation of a per-window consent lease."""
    id: str                     # auth_key from WindowIdentity
    bundle_id: str
    window_id: int
    owner_pid: int
    process_start_time: float
    session_epoch: int
    app_name: str
    window_title: str
    state: str                  # LeaseState constant
    created_at: str
    updated_at: str


# ── ConsentManager ────────────────────────────────────────────────────────────

class ConsentManager:
    """
    Thread-safe consent manager. The capture loop calls is_authorized() each cycle.

    Consent dialogs run on the main thread (macOS: NSAlert dispatched via main queue;
    Windows: MessageBox in a worker thread).

    The manager maintains an in-memory lease cache backed by SQLite.
    Session epoch is persisted so crash recovery can detect stale leases.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.Lock()
        self._leases: dict[str, CaptureLease] = {}     # auth_key → lease
        self._pending_dialogs: set[str] = set()         # auth_keys with active dialogs
        self._dialog_results: dict[str, Optional[bool]] = {}  # auth_key → True/False/None
        self._session_epoch: int = self._load_or_init_epoch()
        self._load_leases_from_db()

    # ── Public interface ───────────────────────────────────────────────────────

    @property
    def session_epoch(self) -> int:
        return self._session_epoch

    def is_authorized(self, identity: WindowIdentity) -> bool:
        """
        Gate check called by observer before each capture cycle.

        Returns True only if this window has an AUTHORIZED lease for the
        current session epoch. All other states return False (privacy fails closed).

        Side effect: initiates individual consent dialog for UNAUTHORIZED windows.
        """
        with self._lock:
            key = identity.auth_key()
            lease = self._leases.get(key)

            if lease is None:
                # First encounter — initiate individual consent
                self._create_lease(identity, LeaseState.UNAUTHORIZED)
                self._enqueue_individual_consent(identity)
                return False

            # Stale session epoch → treat as INVALIDATED
            if lease.session_epoch != self._session_epoch:
                self._update_state(key, LeaseState.INVALIDATED)
                return False

            if lease.state == LeaseState.AUTHORIZED:
                return True

            if lease.state == LeaseState.PENDING_INDIVIDUAL:
                # Check if a dialog result arrived
                result = self._dialog_results.pop(key, None)
                if result is True:
                    self._update_state(key, LeaseState.AUTHORIZED)
                    return True
                elif result is False:
                    self._update_state(key, LeaseState.DECLINED)
                    return False
                # Still pending
                return False

            if lease.state == LeaseState.AWAITING_BATCH_RECONSENT:
                result = self._dialog_results.pop(key, None)
                if result is True:
                    self._update_state(key, LeaseState.AUTHORIZED)
                    return True
                elif result is False:
                    self._update_state(key, LeaseState.DECLINED)
                    return False
                return False

            # DECLINED, INVALIDATED, TERMINATED → not authorized
            return False

    def invalidate_all(self, reason: str) -> None:
        """
        Called at every security boundary crossing (lock, logout, restart, crash).

        Increments session_epoch and marks all AUTHORIZED leases INVALIDATED.
        Persists the new epoch so crash recovery detects stale leases on restart.
        """
        with self._lock:
            self._session_epoch += 1
            self._save_epoch()

            now = _now()
            for key, lease in self._leases.items():
                if lease.state in (LeaseState.AUTHORIZED, LeaseState.PENDING_INDIVIDUAL):
                    lease.state = LeaseState.INVALIDATED
                    lease.session_epoch = self._session_epoch
                    lease.updated_at = now
                    self._persist_lease(lease)

    def get_invalidated_leases(self) -> list[CaptureLease]:
        """Return leases in INVALIDATED state for batch re-consent UI."""
        with self._lock:
            return [l for l in self._leases.values() if l.state == LeaseState.INVALIDATED]

    def begin_batch_reconsent(self, leases: list[CaptureLease]) -> None:
        """
        Transition INVALIDATED leases to AWAITING_BATCH_RECONSENT.
        Called when the consolidated re-consent UI is about to be shown.
        """
        with self._lock:
            now = _now()
            for lease in leases:
                if lease.state == LeaseState.INVALIDATED:
                    lease.state = LeaseState.AWAITING_BATCH_RECONSENT
                    lease.updated_at = now
                    self._persist_lease(lease)
            self._show_batch_reconsent_ui(leases)

    def record_consent_result(self, auth_key: str, allowed: bool) -> None:
        """
        Called from the consent dialog completion handler (main thread).
        Thread-safe — can be called from any thread.
        """
        with self._lock:
            self._dialog_results[auth_key] = allowed
            self._pending_dialogs.discard(auth_key)

    def terminate_lease(self, auth_key: str) -> None:
        """Mark a lease TERMINATED when its window has been destroyed."""
        with self._lock:
            lease = self._leases.get(auth_key)
            if lease and lease.state not in (LeaseState.TERMINATED,):
                self._update_state(auth_key, LeaseState.TERMINATED)

    # ── Individual consent dialog ──────────────────────────────────────────────

    def _enqueue_individual_consent(self, identity: WindowIdentity) -> None:
        """
        Schedule an individual consent dialog for a newly encountered window.
        The dialog must run on the main thread; this method is called from the
        capture loop (background thread).
        """
        key = identity.auth_key()
        if key in self._pending_dialogs:
            return  # Dialog already in flight
        self._pending_dialogs.add(key)
        self._update_state(key, LeaseState.PENDING_INDIVIDUAL)

        if platform.system() == "Darwin":
            self._show_macos_individual_dialog(identity)
        elif platform.system() == "Windows":
            threading.Thread(
                target=self._show_windows_individual_dialog,
                args=(identity,),
                daemon=True,
            ).start()
        else:
            # Unsupported platform — fail closed
            self.record_consent_result(key, False)

    def _show_macos_individual_dialog(self, identity: WindowIdentity) -> None:
        """
        Show NSAlert on the main thread (non-blocking from capture loop's perspective).
        The capture loop continues to get False from is_authorized() until result arrives.
        """
        try:
            import AppKit

            key = identity.auth_key()
            label = identity.display_label()
            timeout = config.CONSENT_DIALOG_TIMEOUT_SECONDS

            def show():
                alert = AppKit.NSAlert.alloc().init()
                alert.setMessageText_("BuildHarvey \u2014 Allow Observation?")
                alert.setInformativeText_(
                    f"BuildHarvey would like to observe:\n\n"
                    f"{label}\n\n"
                    f"This window has not been previously authorized. "
                    f"Work content remains on your device. "
                    f"Authorization expires when your Mac is locked or restarted."
                )
                alert.addButtonWithTitle_("Allow")
                alert.addButtonWithTitle_("Don\u2019t Allow")

                # Run with a timeout via a separate thread that declines on expiry
                result_holder = [None]
                timeout_fired = threading.Event()

                def on_timeout():
                    timeout_fired.wait(timeout)
                    if result_holder[0] is None:
                        # Timeout — privacy fails closed
                        result_holder[0] = False
                        self.record_consent_result(key, False)
                        AppKit.NSApp.abortModal()

                threading.Thread(target=on_timeout, daemon=True).start()

                response = alert.runModal()
                timeout_fired.set()

                if result_holder[0] is None:
                    # Dialog completed before timeout
                    allowed = (response == AppKit.NSAlertFirstButtonReturn)
                    result_holder[0] = allowed
                    self.record_consent_result(key, allowed)

            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(show)
        except Exception:
            # Any error → fail closed
            self.record_consent_result(identity.auth_key(), False)

    def _show_windows_individual_dialog(self, identity: WindowIdentity) -> None:
        """Show a Win32 MessageBox for individual window consent."""
        try:
            import ctypes
            MB_YESNO = 0x04
            MB_ICONQUESTION = 0x20
            MB_DEFBUTTON2 = 0x100   # Default to "No" (fail closed)
            IDYES = 6

            key = identity.auth_key()
            label = identity.display_label()
            message = (
                f"BuildHarvey would like to observe:\n\n{label}\n\n"
                "Work content remains on your device. Authorization expires on lock/restart.\n\n"
                "Allow observation of this window?"
            )

            # Run dialog with timeout via ctypes MessageBoxTimeoutW
            try:
                result = ctypes.windll.user32.MessageBoxTimeoutW(
                    None,
                    message,
                    "BuildHarvey \u2014 Allow Observation?",
                    MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2,
                    0,
                    config.CONSENT_DIALOG_TIMEOUT_SECONDS * 1000,
                )
            except AttributeError:
                # MessageBoxTimeoutW not available — fall back to MessageBoxW
                result = ctypes.windll.user32.MessageBoxW(
                    None,
                    message,
                    "BuildHarvey \u2014 Allow Observation?",
                    MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2,
                )

            self.record_consent_result(key, result == IDYES)
        except Exception:
            self.record_consent_result(identity.auth_key(), False)

    # ── Batch re-consent UI ───────────────────────────────────────────────────

    def _show_batch_reconsent_ui(self, leases: list[CaptureLease]) -> None:
        """
        Show the consolidated re-consent sheet after a security boundary crossing.
        One dialog for all previously-authorized windows; user selects which to resume.
        """
        if not leases:
            return

        if platform.system() == "Darwin":
            self._show_macos_batch_dialog(leases)
        elif platform.system() == "Windows":
            threading.Thread(
                target=self._show_windows_batch_dialog,
                args=(leases,),
                daemon=True,
            ).start()

    def _show_macos_batch_dialog(self, leases: list[CaptureLease]) -> None:
        """
        Show a single consolidated NSAlert listing all AWAITING_BATCH_RECONSENT windows.

        The user selects via 'Resume All' / 'Don't Resume'. A more granular
        per-window checklist UI is deferred to a future NSPanel implementation;
        this provides the required privacy guarantee with minimal complexity.
        """
        try:
            import AppKit

            timeout = config.BATCH_RECONSENT_TIMEOUT_SECONDS
            keys = [l.id for l in leases]

            window_list = "\n".join(
                f"  \u2022  {l.app_name}" + (f" \u2014 {l.window_title}" if l.window_title else "")
                for l in leases
            )

            def show():
                alert = AppKit.NSAlert.alloc().init()
                alert.setMessageText_("BuildHarvey \u2014 Resume Observation?")
                alert.setInformativeText_(
                    "BuildHarvey was observing these windows before your Mac was locked:\n\n"
                    f"{window_list}\n\n"
                    "Work content remains on your device."
                )
                alert.addButtonWithTitle_("Resume All")
                alert.addButtonWithTitle_("Don\u2019t Resume")

                result_holder = [None]
                timeout_fired = threading.Event()

                def on_timeout():
                    timeout_fired.wait(timeout)
                    if result_holder[0] is None:
                        # Timeout — fail closed
                        result_holder[0] = False
                        for key in keys:
                            self.record_consent_result(key, False)
                        try:
                            AppKit.NSApp.abortModal()
                        except Exception:
                            pass

                threading.Thread(target=on_timeout, daemon=True).start()

                response = alert.runModal()
                timeout_fired.set()

                if result_holder[0] is None:
                    allowed = (response == AppKit.NSAlertFirstButtonReturn)
                    result_holder[0] = allowed
                    for key in keys:
                        self.record_consent_result(key, allowed)

            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(show)
        except Exception:
            for lease in leases:
                self.record_consent_result(lease.id, False)

    def _show_windows_batch_dialog(self, leases: list[CaptureLease]) -> None:
        """Show a Win32 MessageBox for batch re-consent on Windows."""
        try:
            import ctypes
            MB_YESNO = 0x04
            MB_ICONQUESTION = 0x20
            MB_DEFBUTTON2 = 0x100
            IDYES = 6

            keys = [l.id for l in leases]
            window_list = "\n".join(
                f"  - {l.app_name}" + (f" - {l.window_title}" if l.window_title else "")
                for l in leases
            )
            message = (
                "BuildHarvey was observing these windows before your computer was locked:\n\n"
                f"{window_list}\n\n"
                "Work content remains on your device.\n\n"
                "Resume observation of all these windows?"
            )

            try:
                result = ctypes.windll.user32.MessageBoxTimeoutW(
                    None,
                    message,
                    "BuildHarvey \u2014 Resume Observation?",
                    MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2,
                    0,
                    config.BATCH_RECONSENT_TIMEOUT_SECONDS * 1000,
                )
            except AttributeError:
                result = ctypes.windll.user32.MessageBoxW(
                    None,
                    message,
                    "BuildHarvey \u2014 Resume Observation?",
                    MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2,
                )

            allowed = (result == IDYES)
            for key in keys:
                self.record_consent_result(key, allowed)
        except Exception:
            for lease in leases:
                self.record_consent_result(lease.id, False)

    # ── SQLite persistence ────────────────────────────────────────────────────

    def _load_or_init_epoch(self) -> int:
        """Load session epoch from DB, or initialize to 1 (increment on every startup)."""
        row = self._conn.execute(
            "SELECT value FROM session_state WHERE key = 'session_epoch'"
        ).fetchone()
        epoch = int(row[0]) if row else 0
        # Increment on every startup (detects crash recovery via dirty_shutdown flag too)
        epoch += 1
        self._conn.execute(
            "INSERT INTO session_state (key, value) VALUES ('session_epoch', ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(epoch),),
        )
        self._conn.commit()
        return epoch

    def _save_epoch(self) -> None:
        self._conn.execute(
            "INSERT INTO session_state (key, value) VALUES ('session_epoch', ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(self._session_epoch),),
        )
        self._conn.commit()

    def _load_leases_from_db(self) -> None:
        """Populate in-memory cache from the capture_leases table."""
        rows = self._conn.execute(
            "SELECT id, bundle_id, window_id, owner_pid, process_start_time, "
            "session_epoch, app_name, window_title, state, created_at, updated_at "
            "FROM capture_leases"
        ).fetchall()
        for r in rows:
            self._leases[r[0]] = CaptureLease(
                id=r[0], bundle_id=r[1], window_id=r[2], owner_pid=r[3],
                process_start_time=r[4], session_epoch=r[5],
                app_name=r[6], window_title=r[7],
                state=r[8], created_at=r[9], updated_at=r[10],
            )

    def _create_lease(self, identity: WindowIdentity, state: str) -> CaptureLease:
        now = _now()
        lease = CaptureLease(
            id=identity.auth_key(),
            bundle_id=identity.bundle_id,
            window_id=identity.window_id,
            owner_pid=identity.owner_pid,
            process_start_time=identity.process_start_time,
            session_epoch=self._session_epoch,
            app_name=identity.app_name,
            window_title=identity.window_title,
            state=state,
            created_at=now,
            updated_at=now,
        )
        self._leases[lease.id] = lease
        self._persist_lease(lease)
        return lease

    def _update_state(self, key: str, new_state: str) -> None:
        lease = self._leases.get(key)
        if lease:
            lease.state = new_state
            lease.updated_at = _now()
            self._persist_lease(lease)

    def _persist_lease(self, lease: CaptureLease) -> None:
        self._conn.execute(
            """
            INSERT INTO capture_leases
                (id, bundle_id, window_id, owner_pid, process_start_time,
                 session_epoch, app_name, window_title, state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                state         = excluded.state,
                session_epoch = excluded.session_epoch,
                window_title  = excluded.window_title,
                updated_at    = excluded.updated_at
            """,
            (
                lease.id, lease.bundle_id, lease.window_id, lease.owner_pid,
                lease.process_start_time, lease.session_epoch,
                lease.app_name, lease.window_title,
                lease.state, lease.created_at, lease.updated_at,
            ),
        )
        self._conn.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
