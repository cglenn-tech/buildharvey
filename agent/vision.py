"""
Live screenshot analysis via BuildHarvey server.

Sends a JPEG-compressed screenshot to /api/agent/vision and returns a
ScreenshotEvidence object, or None on any failure.

The server holds the Anthropic API key and model selection.
The agent never needs an ANTHROPIC_API_KEY.

On any server failure the caller receives None — the episode engine continues
tracking metadata, and all local data is preserved and queued for sync.
"""
import base64
import io
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import auth
import config
from episode import ScreenshotEvidence


def analyze(obs, context: dict) -> Optional[ScreenshotEvidence]:
    """
    Analyze a screenshot against current episode context.

    obs: an Observation with screenshot_path attribute
    context: dict from EpisodeEngine.get_context()

    Returns ScreenshotEvidence if valid and meaningful, None otherwise.
    All local observations are preserved regardless of outcome.
    """
    screenshot_path = getattr(obs, "screenshot_path", None)
    if not screenshot_path:
        return None

    try:
        jpeg_bytes = _prepare_screenshot(screenshot_path)
    except Exception as e:
        print(f"[vision] failed — could not prepare screenshot: {e}")
        return None

    b64 = base64.standard_b64encode(jpeg_bytes).decode("utf-8")

    if len(b64) > config.VISION_MAX_ENCODED_BYTES:
        print(
            f"[vision] failed — screenshot too large after compression "
            f"({len(b64):,} bytes > {config.VISION_MAX_ENCODED_BYTES:,} limit)"
        )
        return None

    token = auth.read_credential()
    if not token:
        return None

    app_context = _app_context(obs)
    payload = json.dumps({
        "screenshot_b64": b64,
        "context": context,
        "app_context": app_context,
    }).encode()

    req = urllib.request.Request(
        f"{config.BASE_URL}/api/agent/vision",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # Try to parse structured error from response body
        try:
            body = json.loads(e.read())
            error_code = body.get("error", "unknown")
        except Exception:
            error_code = f"http_{e.code}"
        _log_server_error(error_code)
        return None
    except Exception as e:
        print(f"[vision] failed — {type(e).__name__}: {e}")
        return None

    if not result.get("success"):
        _log_server_error(result.get("error", "unknown"))
        return None

    ev = result.get("evidence", {})

    if not ev.get("meaningful"):
        print("[vision] rejected — not meaningful")
        return None

    if ev.get("personal_or_irrelevant"):
        print("[vision] discarded — personal/irrelevant")
        return None

    timestamp = time.strftime("%H:%M")
    model = ev.get("model", "")
    input_tokens = ev.get("input_tokens", 0)
    output_tokens = ev.get("output_tokens", 0)

    evidence = ScreenshotEvidence(
        screenshot_path=screenshot_path,
        timestamp=timestamp,
        activity_description=ev.get("activity_description", ""),
        objective=ev.get("objective", ""),
        actions=ev.get("actions", []),
        entities=ev.get("entities", []),
        supporting_evidence=ev.get("supporting_evidence", []),
        app_context=app_context,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        continue_current_episode=ev.get("continue_current_episode", True),
        start_new_episode=ev.get("start_new_episode", False),
        suggested_episode_name=ev.get("suggested_episode_name", ""),
    )

    print(
        f"[vision] accepted — {ev.get('suggested_episode_name', '')} | "
        f"meaningful=true | {input_tokens}t/{output_tokens}t"
    )
    return evidence


def _prepare_screenshot(path: str) -> bytes:
    """
    Read, resize, and JPEG-compress a screenshot for server-side analysis.

    Always outputs RGB JPEG at VISION_JPEG_QUALITY, capped at VISION_ANALYSIS_SIZE.
    Full-resolution raw images are never sent to the server.
    """
    from PIL import Image

    img = Image.open(path)

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    max_w, max_h = config.VISION_ANALYSIS_SIZE
    if img.width > max_w or img.height > max_h:
        img.thumbnail((max_w, max_h), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=config.VISION_JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def _log_server_error(error_code: str) -> None:
    """Print a human-readable status for known structured error codes."""
    messages = {
        "unauthorized":          "[vision] account connection expired — work saved locally",
        "invalid_request":       "[vision] invalid request sent to server",
        "payload_too_large":     "[vision] screenshot was too large for server",
        "server_misconfigured":  "[vision] server configuration error — work saved locally",
        "provider_timeout":      "[vision] analysis temporarily unavailable (timeout) — work saved locally",
        "provider_error":        "[vision] analysis temporarily unavailable — work saved locally",
        "invalid_model_response": "[vision] unexpected model response — work saved locally",
    }
    print(messages.get(error_code, f"[vision] server error: {error_code} — work saved locally"))


def _app_context(obs) -> str:
    parts = []
    app = getattr(obs, "app", "") or ""
    if app:
        parts.append(app)
    url = getattr(obs, "browser_url", "") or ""
    if url:
        try:
            host = urlparse(url).hostname or ""
            if host:
                parts.append(host)
        except Exception:
            pass
    return " | ".join(parts) if parts else "Unknown"
