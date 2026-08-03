"""
Supabase Realtime relay for BuildHarvey.

Replaces the local WebSocket session_server. Both the browser and the agent
connect outward to Supabase Realtime on the channel:
  buildharvey:device:<device_id>

Local (desktop) controls — primary:
  start_local()  → agent begins recording without requiring the browser
  stop_local()   → agent stops recording regardless of browser state

Browser controls — secondary (optional):
  Browser → Realtime broadcast "start" → agent begins recording.
  Browser → Realtime broadcast "stop"  → agent stops recording.

Agent   → Realtime broadcast "status" (state) → browser updates UI.
Agent   → Realtime presence {type:"agent"} → browser knows agent is alive.

Threading model:
  Main thread (sync):  main.py calls is_recording_active(), set_status(), force_stop().
  Realtime thread:     asyncio event loop handles Supabase WebSocket connection.
  Cross-thread:        threading.Event for recording gate, run_coroutine_threadsafe
                       for broadcasts.

Grace period:
  When the last browser leaves presence, a 10-minute timer starts.
  If a browser returns, the timer cancels and the session resumes.
  If 10 minutes pass AND recording was started from the browser (not locally),
  recording stops and the agent idles.
  Local recording is unaffected by browser presence.
"""
import asyncio
import json
import threading
import time
import traceback
import urllib.request
import urllib.error
from typing import Optional

import auth
import config

# ── Public state ──────────────────────────────────────────────────────────────

_lock = threading.Lock()
_recording_event = threading.Event()
_local_recording: bool = False    # set by desktop UI Start/Stop buttons
_browser_present: bool = False
_current_state: str = 'idle'
_event_loop: Optional[asyncio.AbstractEventLoop] = None
_channel = None          # AsyncRealtimeChannel — set from async thread
_grace_timer: Optional[threading.Timer] = None
_credentials: Optional[dict] = None


# ── Credential management ─────────────────────────────────────────────────────

def _fetch_credentials() -> Optional[dict]:
    """Call /api/realtime/token with the device token to get Supabase JWT."""
    token = auth.read_credential()
    if not token:
        print("[realtime] no device credential stored — cannot connect")
        return None

    url = f"{config.BASE_URL}/api/realtime/token"
    req = urllib.request.Request(
        url,
        headers={'Authorization': f'Bearer {token}'},
        method='GET',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        data['expires_at'] = time.time() + data.get('expires_in', 86400)
        # Persist device_id so other modules can read it
        device_id = data.get('device_id')
        if device_id and auth.read_device_id() != device_id:
            auth.store_device_id(device_id)
        return data
    except urllib.error.HTTPError as exc:
        print(f"[realtime] token fetch HTTP error {exc.code}: {exc.reason}")
        return None
    except Exception as exc:
        print(f"[realtime] token fetch error: {exc}")
        return None


# ── Grace period ──────────────────────────────────────────────────────────────

def _cancel_grace_timer() -> None:
    global _grace_timer
    if _grace_timer is not None:
        _grace_timer.cancel()
        _grace_timer = None


def _grace_period_expired() -> None:
    """Called after 10 minutes with no browser.
    Only stops recording if the session was browser-initiated, not locally."""
    global _browser_present
    with _lock:
        if _local_recording:
            print("[realtime] grace period expired — local recording active, continuing")
            return
    print("[realtime] 10-minute grace period expired — stopping recording")
    with _lock:
        _browser_present = False
    _recording_event.clear()
    set_status('idle')


# ── Local recording controls (primary) ────────────────────────────────────────

def start_local() -> None:
    """
    Start recording from the desktop UI.
    Does not require a browser to be present or connected.
    """
    global _local_recording
    with _lock:
        _local_recording = True
    _recording_event.set()
    print("[realtime] local recording started")
    set_status('recording')


def stop_local() -> None:
    """
    Stop recording from the desktop UI.
    main.py will finalize the active episode and broadcast 'idle' when done.
    """
    global _local_recording
    with _lock:
        _local_recording = False
    _recording_event.clear()
    print("[realtime] local recording stopped")


# ── Public API (called from main thread) ──────────────────────────────────────

def is_recording_active() -> bool:
    """
    True when a work session is active.

    Recording is active if:
    - The desktop UI started recording locally (no browser required), OR
    - A browser sent 'start' AND the browser is still present.
    """
    with _lock:
        if _local_recording:
            return _recording_event.is_set()
        return _recording_event.is_set() and _browser_present


def set_status(state: str) -> None:
    """
    Broadcast the current agent state to all connected browser tabs.
    Thread-safe; safe to call from the main capture loop.
    """
    global _current_state
    _current_state = state
    loop = _event_loop
    if loop is not None and not loop.is_closed():
        asyncio.run_coroutine_threadsafe(_broadcast_status(state), loop)


def force_stop() -> None:
    """
    Immediately stop recording. Called on OS sleep, logout, or user switch.
    Does not attempt to broadcast (Realtime connection likely dropped anyway).
    """
    global _browser_present, _local_recording
    _cancel_grace_timer()
    _recording_event.clear()
    with _lock:
        _browser_present = False
        _local_recording = False
    _current_state = 'idle'


def start() -> None:
    """Start the Realtime client in a background daemon thread."""
    try:
        import realtime  # noqa: F401 — verify package is installed
    except ImportError:
        print("[realtime] WARNING: 'realtime' package not installed — browser control disabled")
        return
    t = threading.Thread(target=_run, name='realtime-client', daemon=True)
    t.start()


# ── Async broadcast helper ────────────────────────────────────────────────────

async def _broadcast_status(state: str) -> None:
    ch = _channel
    if ch is not None:
        try:
            await ch.send_broadcast('status', {'state': state})
        except Exception:
            pass


# ── Internal async loop ───────────────────────────────────────────────────────

def _run() -> None:
    global _event_loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _event_loop = loop
    loop.run_until_complete(_connect_loop())


async def _connect_loop() -> None:
    """Outer reconnect loop — fetch credentials and connect; retry on any error."""
    while True:
        try:
            await _connect_once()
        except Exception:
            traceback.print_exc()
        print("[realtime] reconnecting in 10 s…")
        await asyncio.sleep(10)


async def _connect_once() -> None:
    """Fetch credentials, open channel, run until token near-expiry or error."""
    global _channel, _credentials, _browser_present

    from realtime import AsyncRealtimeClient

    # ── Credentials ───────────────────────────────────────────────────────────
    creds = _credentials
    if creds is None or time.time() > creds['expires_at'] - 300:
        creds = _fetch_credentials()
        if creds is None:
            print("[realtime] could not obtain credentials — retrying in 30 s")
            await asyncio.sleep(30)
            return
        _credentials = creds

    supabase_url: str = creds['supabase_url']
    anon_key: str = creds['anon_key']
    access_token: str = creds['access_token']
    device_id: str = creds['device_id']
    expires_at: float = creds['expires_at']

    realtime_url = supabase_url.replace('https://', 'wss://') + '/realtime/v1/websocket'
    topic = f'buildharvey:device:{device_id}'

    print(f"[realtime] connecting — channel {topic[:40]}…")

    client = AsyncRealtimeClient(
        realtime_url,
        access_token,
        params={'apikey': anon_key},
    )
    await client.connect()
    print("[realtime] WebSocket open")

    channel = client.channel(topic, {
        'config': {
            'broadcast': {'ack': False, 'self': False},
            'presence': {'key': ''},
            'private': True,
        }
    })
    _channel = channel

    # ── Broadcast handlers ────────────────────────────────────────────────────

    async def on_start(payload, ref=None, join_ref=None):
        print("[realtime] ← start (browser)")
        _recording_event.set()
        # main.py broadcasts 'recording' once capture actually starts

    async def on_stop(payload, ref=None, join_ref=None):
        print("[realtime] ← stop (browser)")
        # Don't clear if locally started — local controls take priority
        with _lock:
            if _local_recording:
                print("[realtime] ignoring browser stop — local recording active")
                return
        _recording_event.clear()
        # main.py broadcasts 'idle' once episode is finalized

    async def on_status_request(payload, ref=None, join_ref=None):
        await _broadcast_status(_current_state)

    channel.on_broadcast('start', on_start)
    channel.on_broadcast('stop', on_stop)
    channel.on_broadcast('status_request', on_status_request)

    # ── Presence handler ──────────────────────────────────────────────────────

    async def on_presence_sync():
        global _browser_present, _grace_timer
        state = channel.presence_state()
        has_browser = any(
            p.get('type') == 'browser'
            for presences in state.values()
            for p in presences
        )
        was_browser = _browser_present

        with _lock:
            _browser_present = has_browser

        if has_browser and not was_browser:
            print("[realtime] browser connected")
            _cancel_grace_timer()
            # Send current status to the newly connected browser
            await _broadcast_status(_current_state)

        elif not has_browser and was_browser:
            if _recording_event.is_set():
                with _lock:
                    if _local_recording:
                        print("[realtime] last browser left — local recording continues unaffected")
                        return
                print("[realtime] last browser left — 10-min grace period started")
                _grace_timer = threading.Timer(600, _grace_period_expired)
                _grace_timer.start()

    channel.on_presence_sync(on_presence_sync)

    # ── Subscribe ─────────────────────────────────────────────────────────────

    subscribe_done = asyncio.Event()

    def on_subscribe(status, err=None):
        print(f"[realtime] channel → {status}")
        subscribe_done.set()

    await channel.subscribe(on_subscribe)
    await asyncio.wait_for(subscribe_done.wait(), timeout=10)

    await channel.track({'type': 'agent', 'state': _current_state})
    print(f"[realtime] subscribed and tracking on {topic}")

    # ── Keep alive until token is near expiry ─────────────────────────────────

    sleep_seconds = max(0.0, expires_at - time.time() - 300)
    print(f"[realtime] will refresh token in {sleep_seconds / 3600:.1f} h")
    await asyncio.sleep(sleep_seconds)

    # Clean up before reconnect
    _channel = None
    _credentials = None  # force fresh token fetch on next connect
    try:
        await channel.unsubscribe()
        await client.disconnect()
    except Exception:
        pass
