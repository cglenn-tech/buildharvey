"""
Window Identity — stable tuple for per-window consent tracking.

Phase 1 of the privacy architecture: before any observation is recorded,
the capture lease model requires consent for each unique window.

macOS identity tuple: (bundle_id, CGWindowID, owner_pid, process_start_time, session_epoch)
Windows identity tuple: (process_name, HWND, pid, process_creation_time, session_epoch)

The auth_key is a SHA-256 hash of the stable fields. Window title is intentionally
excluded from the key to prevent title changes from invalidating existing consent.
"""
import hashlib
import platform
from dataclasses import dataclass
from typing import Optional


@dataclass
class WindowIdentity:
    """Platform-stable identity for a single window, used as consent key."""
    bundle_id: str              # com.microsoft.Word (macOS) or process name (Windows)
    window_id: int              # CGWindowID (macOS) or HWND (Windows); session-scoped
    owner_pid: int              # process identifier
    process_start_time: float   # prevents PID recycling — from proc_pidinfo / GetProcessTimes
    session_epoch: int          # incremented at every security boundary crossing

    # Display fields — NOT part of the auth key, used only in consent UI
    app_name: str = ""
    window_title: str = ""

    def auth_key(self) -> str:
        """
        Stable hash for lease lookup. Excludes window title (content) to ensure
        title changes do not invalidate existing consent for the same window.
        """
        raw = (
            f"{self.bundle_id}:{self.window_id}:"
            f"{self.process_start_time}:{self.session_epoch}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    def display_label(self) -> str:
        """Human-readable label for the consent UI. Window title is shown but not stored in key."""
        if self.window_title:
            return f"{self.app_name} \u2014 {self.window_title}"
        return self.app_name or self.bundle_id


def get_window_identity(ctx, session_epoch: int) -> Optional[WindowIdentity]:
    """
    Extract a WindowIdentity from the current ScreenContext.
    Returns None if identity cannot be determined (e.g. no frontmost window).
    """
    if platform.system() == "Darwin":
        return _macos_identity(ctx, session_epoch)
    elif platform.system() == "Windows":
        return _windows_identity(ctx, session_epoch)
    return None


# ── macOS ─────────────────────────────────────────────────────────────────────

def _macos_identity(ctx, session_epoch: int) -> Optional[WindowIdentity]:
    """
    Build a macOS WindowIdentity from the frontmost on-screen window.

    CGWindowID is session-scoped (recycled after window closes), so it is
    paired with process_start_time to prevent stale-lease reuse attacks.
    """
    try:
        import Quartz

        options = (
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements
        )
        windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
        frontmost = None
        for w in (windows or []):
            if w.get("kCGWindowLayer") == 0:
                frontmost = w
                break

        if frontmost is None:
            return None

        cg_window_id = int(frontmost.get("kCGWindowNumber", 0))
        owner_pid = int(frontmost.get("kCGWindowOwnerPID", 0))
        process_start_time = _macos_process_start_time(owner_pid)

        return WindowIdentity(
            bundle_id=ctx.bundle_id or "",
            window_id=cg_window_id,
            owner_pid=owner_pid,
            process_start_time=process_start_time,
            session_epoch=session_epoch,
            app_name=ctx.app_name or "",
            window_title=ctx.window_title or "",
        )
    except Exception:
        return None


def _macos_process_start_time(pid: int) -> float:
    """
    Retrieve process start time via proc_pidinfo(PROC_PIDTBSDINFO).
    Pairing PID with start time prevents PID recycling from reusing an expired lease.
    Returns 0.0 on any failure (safe: makes the key unique per PID but not attack-resistant).
    """
    try:
        import ctypes
        import ctypes.util

        libc_path = ctypes.util.find_library("c")
        if not libc_path:
            return 0.0
        libc = ctypes.CDLL(libc_path)

        PROC_PIDTBSDINFO = 3

        # Partial struct — only the fields we need, up to pbi_start_tvusec.
        # Full ProcBSDInfo is ~232 bytes; we request exactly sizeof this partial struct.
        class _ProcBSDInfoPartial(ctypes.Structure):
            _fields_ = [
                ("pbi_flags",       ctypes.c_uint32),
                ("pbi_status",      ctypes.c_uint32),
                ("pbi_xstatus",     ctypes.c_uint32),
                ("pbi_pid",         ctypes.c_uint32),
                ("pbi_ppid",        ctypes.c_uint32),
                ("pbi_uid",         ctypes.c_uint32),
                ("pbi_gid",         ctypes.c_uint32),
                ("pbi_ruid",        ctypes.c_uint32),
                ("pbi_rgid",        ctypes.c_uint32),
                ("pbi_svuid",       ctypes.c_uint32),
                ("pbi_svgid",       ctypes.c_uint32),
                ("rfu_1",           ctypes.c_uint32),
                ("pbi_comm",        ctypes.c_char * 16),
                ("pbi_name",        ctypes.c_char * 32),
                ("pbi_nfiles",      ctypes.c_uint32),
                ("pbi_pgid",        ctypes.c_uint32),
                ("pbi_pjobc",       ctypes.c_uint32),
                ("e_tdev",          ctypes.c_uint32),
                ("e_tpgid",         ctypes.c_uint32),
                ("pbi_nice",        ctypes.c_int32),
                ("pbi_start_tvsec", ctypes.c_uint64),
                ("pbi_start_tvusec",ctypes.c_uint64),
            ]

        info = _ProcBSDInfoPartial()
        size = ctypes.sizeof(info)
        ret = libc.proc_pidinfo(
            ctypes.c_int(pid),
            ctypes.c_int(PROC_PIDTBSDINFO),
            ctypes.c_uint64(0),
            ctypes.byref(info),
            ctypes.c_int(size),
        )
        if ret > 0:
            return float(info.pbi_start_tvsec) + float(info.pbi_start_tvusec) / 1_000_000
    except Exception:
        pass
    return 0.0


# ── Windows ───────────────────────────────────────────────────────────────────

def _windows_identity(ctx, session_epoch: int) -> Optional[WindowIdentity]:
    """
    Build a Windows WindowIdentity from the foreground window.

    HWND is session-scoped (recycled after window destroys), so it is paired
    with process_creation_time to prevent both HWND and PID recycling.
    """
    try:
        import win32gui
        import win32process

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        creation_time = _windows_process_creation_time(pid)

        # On Windows, use process name as bundle_id equivalent
        process_name = ctx.bundle_id or ctx.app_name or ""

        return WindowIdentity(
            bundle_id=process_name,
            window_id=hwnd,
            owner_pid=pid,
            process_start_time=creation_time,
            session_epoch=session_epoch,
            app_name=ctx.app_name or "",
            window_title=ctx.window_title or "",
        )
    except Exception:
        return None


def _windows_process_creation_time(pid: int) -> float:
    """
    Retrieve process creation time from Win32 GetProcessTimes.
    Pairing HWND and PID with creation time prevents recycling attacks.
    Returns 0.0 on any failure.
    """
    try:
        import win32api
        import win32con
        import win32process
        import datetime

        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, pid)
        if not handle:
            return 0.0
        try:
            times = win32process.GetProcessTimes(handle)
            # times[0] is creation time as a pywintypes.datetime
            creation = times[0]
            # Convert Windows FILETIME epoch (1601-01-01) to Unix epoch
            filetime_epoch = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)
            return (
                creation.replace(tzinfo=datetime.timezone.utc) - filetime_epoch
            ).total_seconds()
        finally:
            win32api.CloseHandle(handle)
    except Exception:
        return 0.0
