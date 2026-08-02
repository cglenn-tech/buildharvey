"""
Local WebSocket session server.

The BuildHarvey web page connects to ws://localhost:39291 while open.
Connection present → recording allowed.
No connection for > IDLE_TIMEOUT_SECONDS → agent idles.

Uses asyncio + websockets library. Runs in a background daemon thread.
Never contacts Supabase or the cloud to determine recording state.
Cloud availability does not affect idle/recording decisions.
"""
import asyncio
import json
import threading
import time
from typing import Optional, Set

AGENT_PORT = 39291
IDLE_TIMEOUT_SECONDS = 600  # 10 minutes

_lock = threading.Lock()
_clients: Set = set()
_last_seen: float = 0.0   # monotonic time of last client disconnect


def _get_stored_user_id() -> Optional[str]:
    try:
        import auth
        return auth.read_user_id()
    except Exception:
        return None


async def _handler(websocket):
    # Require an auth message within 3 seconds
    try:
        raw = await asyncio.wait_for(websocket.recv(), timeout=3.0)
        data = json.loads(raw)
    except Exception:
        await websocket.close(code=4001, reason='auth_required')
        return

    stored_user_id = _get_stored_user_id()
    received_user_id = data.get('user_id') if isinstance(data, dict) else None

    # Only enforce identity check when a user_id has been stored (post-activation)
    if stored_user_id and stored_user_id != received_user_id:
        await websocket.close(code=4001, reason='unauthorized')
        return

    if data.get('type') != 'auth':
        await websocket.close(code=4001, reason='auth_required')
        return

    with _lock:
        _clients.add(websocket)
    try:
        async for _ in websocket:
            pass   # presence of connection is the signal; messages are ignored
    finally:
        with _lock:
            _clients.discard(websocket)
            global _last_seen
            _last_seen = time.monotonic()


def is_browser_active() -> bool:
    """
    Returns True while at least one browser tab is connected,
    OR within IDLE_TIMEOUT_SECONDS of the last disconnect.
    Returns False only after the timeout has elapsed with no connections.
    Network/cloud availability does not affect this result.
    """
    with _lock:
        if _clients:
            return True
        if _last_seen == 0.0:
            return False   # never connected — stay idle
        return (time.monotonic() - _last_seen) < IDLE_TIMEOUT_SECONDS


def force_stop() -> None:
    """
    Immediately invalidate the session.
    Called by emergency stop (lock, logout, sleep, disconnect).
    After this, is_browser_active() returns False until a new client connects.
    """
    with _lock:
        _clients.clear()
        global _last_seen
        _last_seen = 0.0  # Reset to 'never connected' — no grace period


def start() -> None:
    """Start the WebSocket server in a background daemon thread."""
    t = threading.Thread(target=_run_server, name='session-server', daemon=True)
    t.start()
    print(f'[session] WebSocket server on ws://localhost:{AGENT_PORT}')


def _run_server() -> None:
    asyncio.run(_serve())


async def _serve() -> None:
    try:
        import websockets.asyncio.server as ws_server
        async with ws_server.serve(_handler, 'localhost', AGENT_PORT):
            await asyncio.get_event_loop().create_future()  # run forever
    except Exception as exc:
        print(f'[session] server error: {exc}')
