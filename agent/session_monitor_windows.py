"""
Windows session event monitor.

Registers WM_WTSSESSION_CHANGE and WM_QUERYENDSESSION/WM_ENDSESSION via a
hidden message-only window. Runs a message pump in a background daemon thread.

Calls stop_callback() immediately on:
  - Windows session lock
  - Logoff
  - Session disconnect / fast-user switch
  - System shutdown / restart

Usage:
    import session_monitor_windows
    session_monitor_windows.start(stop_callback=some_fn)
"""

import ctypes
import ctypes.wintypes
import threading

# WTS session change reasons
WTS_CONSOLE_DISCONNECT   = 0x1
WTS_SESSION_LOGOFF       = 0x6
WTS_SESSION_LOCK         = 0x7
WTS_SESSION_DISCONNECT   = 0x4

# Window messages
WM_WTSSESSION_CHANGE  = 0x02B1
WM_QUERYENDSESSION    = 0x0011
WM_ENDSESSION         = 0x0016

NOTIFY_FOR_THIS_SESSION = 0

_STOP_REASONS = {WTS_CONSOLE_DISCONNECT, WTS_SESSION_LOGOFF, WTS_SESSION_LOCK, WTS_SESSION_DISCONNECT}

_user32   = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

WNDPROCTYPE = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    ctypes.wintypes.HWND,
    ctypes.c_uint,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)


def start(stop_callback) -> None:
    """Start session monitor in a background daemon thread."""
    t = threading.Thread(target=_run_monitor, args=(stop_callback,), daemon=True)
    t.start()


def _run_monitor(stop_callback) -> None:
    try:
        _stop = stop_callback

        def _wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_WTSSESSION_CHANGE:
                if wparam in _STOP_REASONS:
                    try:
                        _stop()
                    except Exception:
                        pass
            elif msg == WM_QUERYENDSESSION:
                try:
                    _stop()
                except Exception:
                    pass
                return 1   # allow shutdown to proceed
            elif msg == WM_ENDSESSION:
                if wparam:
                    try:
                        _stop()
                    except Exception:
                        pass
            return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wndproc_c = WNDPROCTYPE(_wndproc)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ('style',         ctypes.c_uint),
                ('lpfnWndProc',   WNDPROCTYPE),
                ('cbClsExtra',    ctypes.c_int),
                ('cbWndExtra',    ctypes.c_int),
                ('hInstance',     ctypes.wintypes.HANDLE),
                ('hIcon',         ctypes.wintypes.HANDLE),
                ('hCursor',       ctypes.wintypes.HANDLE),
                ('hbrBackground', ctypes.wintypes.HANDLE),
                ('lpszMenuName',  ctypes.wintypes.LPCWSTR),
                ('lpszClassName', ctypes.wintypes.LPCWSTR),
            ]

        hinstance  = _kernel32.GetModuleHandleW(None)
        class_name = 'BHSessionMonitor'

        wc = WNDCLASSW()
        wc.lpfnWndProc  = wndproc_c
        wc.hInstance    = hinstance
        wc.lpszClassName = class_name

        _user32.RegisterClassW(ctypes.byref(wc))

        # HWND_MESSAGE (-3) creates a message-only window (no visible UI)
        HWND_MESSAGE = ctypes.wintypes.HWND(-3)
        hwnd = _user32.CreateWindowExW(
            0, class_name, 'BH Session Monitor', 0,
            0, 0, 0, 0,
            HWND_MESSAGE, None, hinstance, None,
        )
        if not hwnd:
            print('[session_monitor_windows] CreateWindowExW failed')
            return

        # Register for WTS session notifications (optional — non-fatal if unavailable)
        try:
            import win32ts
            win32ts.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION)
        except Exception:
            pass  # fall back to WM_QUERYENDSESSION only

        # Message pump
        msg = ctypes.wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    except Exception as exc:
        print(f'[session_monitor_windows] error: {exc}')
