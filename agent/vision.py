"""
Screenshot analysis — cloud (Phase 1-3) or local inference (Phase 4+).

Phase 1–3 (USE_LOCAL_INFERENCE=false, default):
  Sends a JPEG-compressed screenshot to /api/agent/vision and returns a
  ScreenshotEvidence object, or None on any failure. The server holds the
  Anthropic API key and model selection.

Phase 4+ (USE_LOCAL_INFERENCE=true, after benchmark validation):
  No screenshot is sent anywhere. The local OCR text excerpt and context are
  passed to LocalInferenceBackend.classify_episode_boundary(). Screenshots
  are deleted immediately after extraction — never sent to any server.

On any failure the caller receives None — the episode engine continues
tracking metadata, and all local data is preserved and queued for sync.

The cloud path remains in this file during the transition period so it can be
re-enabled for development by setting USE_LOCAL_INFERENCE=false. It will be
removed entirely once Phase 4 is confirmed stable on all target hardware.
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
from bh_logging import get_logger
from episode import ScreenshotEvidence

log = get_logger("vision")

# Module-level cached local inference backend (initialized lazily on first call)
_local_backend = None


def _get_local_backend():
    global _local_backend
    if _local_backend is None:
        from local_inference import get_backend
        _local_backend = get_backend()
    return _local_backend


def analyze(obs, context: dict) -> Optional[ScreenshotEvidence]:
    """
    Analyze a screenshot against current episode context.

    obs: an Observation with screenshot_path attribute
    context: dict from EpisodeEngine.get_context()

    Returns ScreenshotEvidence if valid and meaningful, None otherwise.
    All local observations are preserved regardless of outcome.

    When USE_LOCAL_INFERENCE=true (Phase 4+):
      - No screenshot is sent to any server.
      - The local backend classifies the episode boundary using the OCR excerpt.
      - The screenshot is deleted immediately after this call.
    """
    screenshot_path = getattr(obs, "screenshot_path", None)
    if not screenshot_path:
        return None

    # ── Phase 4+: local inference path ────────────────────────────────────────
    if config.USE_LOCAL_INFERENCE:
        return _analyze_local(obs, context, screenshot_path)

    # In Private Mode, no cloud fallback — return None (no screenshot sent anywhere)
    if config.PRIVATE_MODE:
        return None

    # ── Cloud path (Phase 1–3) ─────────────────────────────────────────────────
    try:
        jpeg_bytes = _prepare_screenshot(screenshot_path)
    except Exception as e:
        log.error("vision.prepare_failed", error=str(e))
        return None

    b64 = base64.standard_b64encode(jpeg_bytes).decode("utf-8")

    if len(b64) > config.VISION_MAX_ENCODED_BYTES:
        log.warning("vision.screenshot_too_large", size=len(b64), limit=config.VISION_MAX_ENCODED_BYTES)
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
        log.error("vision.request_failed", error=str(e))
        return None

    if not result.get("success"):
        _log_server_error(result.get("error", "unknown"))
        return None

    ev = result.get("evidence", {})

    if not ev.get("meaningful"):
        log.debug("vision.rejected", reason="not_meaningful")
        return None

    if ev.get("personal_or_irrelevant"):
        log.debug("vision.discarded", reason="personal_or_irrelevant")
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

    log.info(
        "vision.accepted",
        episode_name=ev.get("suggested_episode_name", ""),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    return evidence


def _analyze_local(obs, context: dict, screenshot_path: str) -> Optional[ScreenshotEvidence]:
    """
    Phase 4+: Classify episode boundary using the local inference backend.

    The screenshot is NOT sent anywhere. Only a short OCR excerpt (≤200 chars)
    extracted from the already-captured frame is passed to the local model.
    The screenshot file is deleted immediately after extraction.
    """
    import time as _time
    from pathlib import Path as _Path

    try:
        # Extract OCR text excerpt from the screenshot (local, no network)
        try:
            import ocr
            ocr_text = ocr.extract_text(screenshot_path)
            ocr_excerpt = ocr_text[:200] if ocr_text else ""
        except Exception:
            ocr_excerpt = ""
        finally:
            # Phase 4 invariant: screenshot deleted immediately after extraction
            try:
                _Path(screenshot_path).unlink(missing_ok=True)
            except Exception:
                pass

        backend = _get_local_backend()
        if not backend.is_available():
            return None

        current_summary = context.get("episode_name", "") if context else ""
        app = getattr(obs, "app", "") or ""
        window_title = getattr(obs, "window_title", "") or ""

        signal = backend.classify_episode_boundary(
            app=app,
            window_title=window_title,
            ocr_excerpt=ocr_excerpt,
            current_episode_summary=current_summary,
        )

        # Convert BoundarySignal to ScreenshotEvidence (no screenshot_path — deleted)
        return ScreenshotEvidence(
            screenshot_path=None,   # Phase 4: no persistent screenshot
            timestamp=_time.strftime("%H:%M"),
            activity_description=f"{signal.activity_type} activity detected",
            objective=current_summary,
            actions=[],
            entities=getattr(obs, "entities", []),
            supporting_evidence=[],
            app_context=_app_context(obs),
            model="local",
            input_tokens=0,
            output_tokens=0,
            continue_current_episode=not signal.new_episode,
            start_new_episode=signal.new_episode,
            suggested_episode_name="",
        )
    except Exception as e:
        log.error("vision.local_analyze_failed", error=str(e))
        return None


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
    """Log a human-readable status for known structured error codes."""
    messages = {
        "unauthorized":           "account connection expired — work saved locally",
        "invalid_request":        "invalid request sent to server",
        "payload_too_large":      "screenshot was too large for server",
        "server_misconfigured":   "server configuration error — work saved locally",
        "provider_timeout":       "analysis temporarily unavailable (timeout) — work saved locally",
        "provider_error":         "analysis temporarily unavailable — work saved locally",
        "invalid_model_response": "unexpected model response — work saved locally",
    }
    msg = messages.get(error_code, f"server error: {error_code} — work saved locally")
    log.warning("vision.server_error", error_code=error_code, message=msg)


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
