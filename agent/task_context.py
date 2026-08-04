"""
Thread-safe shared state between the UI thread and the capture loop thread.

The UI thread writes context (case_name, issue, work_type) via set_context().
The capture loop reads it each cycle via get_context().

The capture loop writes agent status (latest_activity, timing_paused, switch_suggestion).
The UI reads these to update its display.

Pending user actions (confirm/reject switch, force stop) are written by the UI
and consumed (popped) by the capture loop each cycle.
"""
import threading
from dataclasses import dataclass
from typing import Optional

_lock = threading.Lock()

# ── Context (UI → engine) ─────────────────────────────────────────────────────

@dataclass
class TaskContext:
    case_name: str = ""
    issue_worked_on: str = ""
    work_type: str = "project"
    is_set: bool = False


_context = TaskContext()


def set_context(case_name: str, issue: str, work_type: str) -> None:
    """UI calls this when the user enters a case name and clicks Start Task."""
    global _context
    with _lock:
        _context = TaskContext(
            case_name=case_name,
            issue_worked_on=issue,
            work_type=work_type,
            is_set=True,
        )


def clear_context() -> None:
    """Reset context (e.g. after session ends or user dismisses daily review)."""
    global _context
    with _lock:
        _context = TaskContext()


def get_context() -> TaskContext:
    """Return a snapshot of the current context (safe to read from any thread)."""
    with _lock:
        return TaskContext(
            case_name=_context.case_name,
            issue_worked_on=_context.issue_worked_on,
            work_type=_context.work_type,
            is_set=_context.is_set,
        )


# ── Agent status (engine → UI) ────────────────────────────────────────────────

_latest_activity: str = ""
_timing_paused: bool = False
_switch_suggestion: str = ""


def set_latest_activity(text: str) -> None:
    global _latest_activity
    with _lock:
        _latest_activity = text


def get_latest_activity() -> str:
    with _lock:
        return _latest_activity


def set_timing_paused(paused: bool) -> None:
    global _timing_paused
    with _lock:
        _timing_paused = paused


def is_timing_paused() -> bool:
    with _lock:
        return _timing_paused


def set_switch_suggestion(candidate: str) -> None:
    global _switch_suggestion
    with _lock:
        _switch_suggestion = candidate


def get_switch_suggestion() -> str:
    with _lock:
        return _switch_suggestion


def clear_switch_suggestion() -> None:
    global _switch_suggestion
    with _lock:
        _switch_suggestion = ""


# ── Pending user actions (UI → engine, consumed by main.py each cycle) ────────

# Sentinel: distinguishes "not requested" from "requested with empty name".
_UNSET: object = object()
_confirm_switch_name: object = _UNSET
_reject_switch_pending: bool = False
_force_stop_pending: bool = False


def request_confirm_switch(name: str = "") -> None:
    """
    UI calls when user clicks Switch (or Choose other).
    name="" means use the current switch suggestion.
    name="Smith v. Jones" means switch to a custom name.
    """
    global _confirm_switch_name
    with _lock:
        _confirm_switch_name = name


def request_reject_switch() -> None:
    """UI calls when user clicks Stay."""
    global _reject_switch_pending
    with _lock:
        _reject_switch_pending = True


def request_force_stop() -> None:
    """UI calls when user clicks Stop Work Session."""
    global _force_stop_pending
    with _lock:
        _force_stop_pending = True


def pop_confirm_switch() -> Optional[str]:
    """
    main.py calls each cycle.
    Returns the confirmed name (may be "") if user confirmed, None if not requested.
    Clears the pending action.
    """
    global _confirm_switch_name
    with _lock:
        if _confirm_switch_name is _UNSET:
            return None
        name = str(_confirm_switch_name)
        _confirm_switch_name = _UNSET
        return name


def pop_reject_switch() -> bool:
    """main.py calls each cycle. Returns True if a reject was requested. Clears it."""
    global _reject_switch_pending
    with _lock:
        val = _reject_switch_pending
        _reject_switch_pending = False
        return val


def pop_force_stop() -> bool:
    """main.py calls each cycle. Returns True if a force stop was requested. Clears it."""
    global _force_stop_pending
    with _lock:
        val = _force_stop_pending
        _force_stop_pending = False
        return val
