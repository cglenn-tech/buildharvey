"""
BuildHarvey agent authentication.

Device activation flow:
  1. Generate raw_device_token and raw_polling_secret locally.
  2. POST /api/activate/request with hashes.
  3. Open browser to /activate?id=...
  4. Poll /api/activate/poll until approved.
  5. Store raw_device_token in macOS Keychain.

The server never sees the raw device token.
"""
import hashlib
import json
import os
import subprocess
import time
import urllib.request
import urllib.error
from typing import Optional

import config
from os_adapters import Adapter as _Adapter

_adapter = _Adapter()


# ── Credential storage (delegated to platform adapter) ────────────────────────

def read_credential() -> Optional[str]:
    """Read device token from platform credential store. Returns hex string or None."""
    return _adapter.read_credential(account='device-token')


def store_credential(raw_token_hex: str) -> None:
    """Store device token in platform credential store, replacing any existing entry."""
    _adapter.store_credential(raw_token_hex, account='device-token')


def read_user_id() -> Optional[str]:
    """Read the stored user_id (UUID) associated with this device."""
    return _adapter.read_credential(account='user-id')


def store_user_id(user_id: str) -> None:
    """Store the user_id alongside the device token for WebSocket identity validation."""
    _adapter.store_credential(user_id, account='user-id')


# ── Token helpers ──────────────────────────────────────────────────────────────

def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _api(path: str, body: dict) -> dict:
    """POST to the BuildHarvey API. Returns parsed JSON response."""
    url = f"{config.BASE_URL}{path}"
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


# ── Activation flow ────────────────────────────────────────────────────────────

def activate(device_name: str = 'My Mac') -> Optional[str]:
    """
    Run the device activation flow.
    Returns raw_device_token hex string on success, None on failure.
    """
    # Step 1: Generate secrets locally
    raw_device_token = os.urandom(32)
    raw_polling_secret = os.urandom(32)

    token_hash = _sha256_hex(raw_device_token)
    polling_verifier = _sha256_hex(raw_polling_secret)

    # Step 2: Register with server
    try:
        resp = _api('/api/activate/request', {
            'device_name': device_name,
            'platform': 'macos',
            'token_hash': token_hash,
            'polling_verifier': polling_verifier,
        })
    except Exception as exc:
        print(f"[auth] activate request failed: {exc}")
        return None

    activation_id = resp.get('activation_id')
    if not activation_id:
        print("[auth] no activation_id in response")
        return None

    # Step 3: Open browser (cross-platform)
    activate_url = f"{config.BASE_URL}/activate?id={activation_id}"
    import webbrowser
    webbrowser.open(activate_url)
    print(f"[auth] opened browser: {activate_url}")

    # Step 4: Poll for approval
    raw_polling_secret_hex = raw_polling_secret.hex()
    raw_device_token_hex = raw_device_token.hex()

    deadline = time.time() + 600  # 10 minute window
    while time.time() < deadline:
        time.sleep(3)
        try:
            poll_resp = _api('/api/activate/poll', {
                'activation_id': activation_id,
                'polling_secret': raw_polling_secret_hex,
            })
            status = poll_resp.get('status')
            if status == 'approved':
                user_id = poll_resp.get('user_id')
                if user_id:
                    store_user_id(user_id)
                return raw_device_token_hex
            elif status == 'expired':
                print("[auth] activation expired")
                return None
            # status == 'pending' → keep polling
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                print("[auth] poll unauthorized")
                return None
            print(f"[auth] poll error: {exc}")
        except Exception as exc:
            print(f"[auth] poll error: {exc}")

    print("[auth] activation timed out")
    return None
