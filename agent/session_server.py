"""
Local WebSocket session server.

Protocol:
  Browser → Agent:
    {"type": "auth", "user_id": "<uid>"}   — must be first message (3 s timeout)
    {"type": "start"}                       — begin a work session / recording
    {"type": "stop"}                        — end the work session / recording
  Agent → Browser:
    {"type": "status", "state": "<state>"} — sent on connect and on state change
      states: "idle" | "recording"

Recording is NOT automatic on connect.
The browser must send {"type": "start"} to activate the recording loop.
"""
import asyncio
import json
import threading
from typing import Optional, Set

AGENT_PORT = 39291

_lock = threading.Lock()
_clients: Set = set()

# threading.Event for cross-thread recording control
_recording_event = threading.Event()

# Current state string broadcast to browsers
_current_state: str = 'idle'

# The server's event loop — stored so main.py can schedule broadcasts
_event_loop: Optional[asyncio.AbstractEventLoop] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_stored_user_id() -> Optional[str]:
    try:
        import auth
        return auth.read_user_id()
    except Exception:
        return None


async def _broadcast_status() -> None:
    msg = json.dumps({'type': 'status', 'state': _current_state})
    for ws in list(_clients):
        try:
            await ws.send(msg)
        except Exception:
            pass


# ── WebSocket handler ─────────────────────────────────────────────────────────

async def _handler(websocket) -> None:
    # Require auth message within 3 seconds
    try:
        raw = await asyncio.wait_for(websocket.recv(), timeout=3.0)
        data = json.loads(raw)
    except Exception:
        await websocket.close(code=4001, reason='auth_required')
        return

    if not isinstance(data, dict) or data.get('type') != 'auth':
        await websocket.close(code=4001, reason='auth_required')
        return

    stored_user_id = _get_stored_user_id()
    received_user_id = data.get('user_id')
    if stored_user_id and stored_user_id != received_user_id:
        await websocket.close(code=4001, reason='unauthorized')
        return

    # Auth passed — register and send current state
    with _lock:
        _clients.add(websocket)
    await websocket.send(json.dumps({'type': 'status', 'state': _current_state}))

    try:
        async for raw_msg in websocket:
            try:
                msg = json.loads(raw_msg)
                mtype = msg.get('type')
                if mtype == 'start':
                    _recording_event.set()
                    # main.py will broadcast 'recording' once capture actually starts
                elif mtype == 'stop':
                    _recording_event.clear()
                    await websocket.send(json.dumps({'type': 'status', 'state': 'idle'}))
            except Exception:
                pass
    finally:
        with _lock:
            _clients.discard(websocket)
        # Stop recording when the last browser tab disconnects
        if not _clients:
            _recording_event.clear()


# ── Public API ────────────────────────────────────────────────────────────────

def is_browser_active() -> bool:
    """Kept for backward compatibility. Prefer is_recording_active()."""
    with _lock:
        return bool(_clients)


def is_recording_active() -> bool:
    """
    True when a browser tab is connected AND the user has started a work session.
    Used by main.py to gate the capture loop.
    """
    with _lock:
        return _recording_event.is_set() and bool(_clients)


def set_status(state: str) -> None:
    """
    Called from main.py's thread to broadcast the current recording state
    to all connected browser tabs. Thread-safe.
    """
    global _current_state
    _current_state = state
    loop = _event_loop
    if loop is not None and not loop.is_closed():
        asyncio.run_coroutine_threadsafe(_broadcast_status(), loop)


def force_stop() -> None:
    """
    Immediately invalidate the session.
    Called on lock, logout, sleep, or Windows session disconnect.
    """
    _recording_event.clear()
    with _lock:
        _clients.clear()


def start() -> None:
    """Start the WebSocket server in a background daemon thread."""
    t = threading.Thread(target=_run_server, name='session-server', daemon=True)
    t.start()
    print(f'[session] WebSocket server on ws://localhost:{AGENT_PORT}')


# ── Internal server ───────────────────────────────────────────────────────────

def _run_server() -> None:
    global _event_loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _event_loop = loop
    loop.run_until_complete(_serve())


async def _serve() -> None:
    try:
        import websockets.asyncio.server as ws_server
        async with ws_server.serve(_handler, 'localhost', AGENT_PORT):
            await asyncio.get_event_loop().create_future()  # run forever
    except Exception as exc:
        print(f'[session] server error: {exc}')
