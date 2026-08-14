"""
IPC Protocol — interface between the app shell and the private work engine.

No work content crosses this interface. Episode IDs and durations are structural
references, not content. The interface is intentionally narrow.

macOS: Carried via NSXPCConnection with a defined NSXPCInterface.
Windows: Carried via Windows named pipe (see PIPE_NAME_WINDOWS constant below).

IMPORT BOUNDARY: this file must not import any networking library.
"""
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class WindowIdentityInfo:
    """Minimal window information for consent events. No content."""
    auth_key: str           # hash — not content
    app_name: str           # application name (not title, not content)
    window_title: str       # shown in consent UI only; not stored in episode data
    platform: str           # "darwin" | "windows"


@dataclass
class EngineStatus:
    """Current state of the private engine."""
    state: str              # "idle" | "capturing" | "awaiting_consent" | "inference" | "error"
    session_epoch: int
    active_episode_id: str | None
    open_gap_id: str | None
    last_error: str | None


# ── Commands: App Shell → Private Engine ─────────────────────────────────────

@runtime_checkable
class PrivateEngineCommand(Protocol):
    """Commands that the app shell sends to the private engine."""

    def start_capture(self) -> None:
        """Begin capture loop for the current session."""
        ...

    def stop_capture(self) -> None:
        """Stop capture loop; close any active episode."""
        ...

    def request_report(self, period_start: str, period_end: str) -> None:
        """
        Generate a weekly report for the given ISO 8601 date range.
        The engine responds with on_report_ready() when complete.
        period_start, period_end: ISO 8601 date strings (no work content).
        """
        ...

    def delete_all_data(self) -> None:
        """
        Irreversibly delete all local data and exit.
        Caller must not restart the engine without user re-consent.
        """
        ...

    def get_status(self) -> EngineStatus:
        """Return current engine status."""
        ...

    def record_consent_result(self, auth_key: str, allowed: bool) -> None:
        """
        Deliver user's consent decision for a window.
        Called from the app shell after showing the consent dialog.
        auth_key: from WindowIdentityInfo (hash — not content)
        allowed: True = AUTHORIZED, False = DECLINED
        """
        ...

    def record_batch_reconsent_result(self, auth_keys: list[str], allowed: bool) -> None:
        """
        Deliver user's batch re-consent decision after device unlock.
        auth_keys: list of window auth_keys from the batch consent UI
        allowed: True = all AUTHORIZED, False = all DECLINED
        """
        ...


# ── Events: Private Engine → App Shell ────────────────────────────────────────

@runtime_checkable
class PrivateEngineEvent(Protocol):
    """Events that the private engine sends to the app shell."""

    def on_episode_closed(self, episode_id: str, duration_minutes: float) -> None:
        """
        An episode has been finalized and saved to SQLite.
        episode_id: UUID (structural reference, not content)
        duration_minutes: computed duration (no content)
        """
        ...

    def on_gap_recorded(self, gap_id: str, cause: str) -> None:
        """
        An observation gap has been opened.
        gap_id: UUID (structural reference)
        cause: 'device_locked' | 'window_not_consented' | etc.
        """
        ...

    def on_report_ready(self, local_path: str) -> None:
        """
        A locally generated report is available at local_path.
        local_path: filesystem path (no work content in the path itself)
        """
        ...

    def on_consent_needed(self, window: WindowIdentityInfo) -> None:
        """
        A new window requires individual consent before capture can proceed.
        The app shell shows the consent dialog and calls record_consent_result().
        """
        ...

    def on_batch_reconsent_needed(self, windows: list[WindowIdentityInfo]) -> None:
        """
        Returning from a security boundary — show batch re-consent for these windows.
        The app shell shows the consolidated UI and calls record_batch_reconsent_result().
        """
        ...

    def on_inference_failure(self, reason: str) -> None:
        """
        Local inference failed for an episode.
        reason: brief description (no work content)
        The engine has already recorded the gap / closed the episode with inference_failed=True.
        There is NO cloud fallback in production Private Mode builds.
        """
        ...

    def on_status_update(self, status: EngineStatus) -> None:
        """Engine state has changed."""
        ...


# ── IPC message framing ────────────────────────────────────────────────────────

@dataclass
class IPCMessage:
    """
    Wire format for IPC messages over the named pipe (Windows) or XPC (macOS).
    Both directions use the same envelope.
    """
    message_id: str             # UUID for request/response correlation
    message_type: str           # e.g. "start_capture", "on_episode_closed"
    payload: dict               # type-specific fields
    protocol_version: int = 1


PIPE_NAME_WINDOWS = r"\\.\pipe\BuildHarveyPrivateEngine"
XPC_SERVICE_ID_MACOS = "com.buildharvey.PrivateEngine"
