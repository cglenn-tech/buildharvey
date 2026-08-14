"""
Episode Finalizer — Phase 2 of the privacy architecture.

Runs once when an episode closes, before it is persisted.

Screenshot lifecycle (Phase 2 target: zero persistent raw screenshots):
  - Raw frames are ephemeral: captured to /tmp, used for OCR/diff, then overwritten.
  - evidence/ directory and the up-to-8-frames persistence are REMOVED.
  - Structured Episode data (key_observations, activity_classification, confidence)
    survives; raw frames do not.
  - episode.evidence_paths is set to [] — screenshots are never moved or retained.

Key observations path (in priority order):
  1. LocalInferenceBackend (USE_LOCAL_INFERENCE=true) — fully on-device
  2. /api/agent/finalize server call (USE_LOCAL_INFERENCE=false, token available)
  3. Template fallback — deterministic, no network

Core philosophy: produce observations that read like an executive assistant
summarized the work — not browser history. Synthesize. Connect. Reconstruct.
"""
import json
import urllib.request
from pathlib import Path

import auth
import config
import observations as obs_mod
from bh_logging import get_logger
from episode import Episode, KeyObservation, RawObservation

log = get_logger("finalizer")

# Phase 2: evidence directory is deprecated — no persistent screenshots.
# The constant is kept for migration cleanup; no new files are written here.
_EVIDENCE_BASE = config.BASE_DIR / "evidence"


def finalize(episode: Episode) -> None:
    """
    Process a closed episode in place.
    Sets episode.key_observations. Deletes all temporary screenshot files.
    episode.evidence_paths is always set to [] (no persistent raw screenshots).
    """
    try:
        key_obs, activity_class, class_confidence, inference_failed = _generate_observations(episode)
        episode.key_observations = key_obs
        # Store classification metadata on the episode object for the DB caller to use
        episode._activity_classification = activity_class
        episode._classification_confidence = class_confidence
        episode._has_inference_failure = inference_failed
    finally:
        # Phase 2: delete all temporary screenshots immediately — no evidence/ directory.
        _delete_all_screenshots(episode)
        episode.evidence_paths = []
        episode._raw_observations = []


def _generate_observations(
    episode: Episode,
) -> tuple[list[KeyObservation], str | None, float | None, bool]:
    """
    Generate key observations for a closed episode.
    Returns: (key_observations, activity_classification, classification_confidence, inference_failed)
    """
    if config.USE_LOCAL_INFERENCE:
        result = _local_observations(episode)
        if result is not None:
            return result

    if not config.PRIVATE_MODE:
        result = _server_observations(episode)
        if result is not None:
            return result

    obs = _template_observations(episode._raw_observations)
    # inference_failed=True if local was expected but unavailable
    inference_failed = config.USE_LOCAL_INFERENCE
    return obs, None, None, inference_failed


# ── Local inference path (Phase 3+) ───────────────────────────────────────────

def _local_observations(
    episode: Episode,
) -> tuple[list[KeyObservation], str | None, float | None, bool] | None:
    """
    Generate observations via LocalInferenceBackend (fully on-device).
    Returns None if local inference is unavailable (caller falls through to server).
    """
    try:
        from local_inference import get_backend
        backend = get_backend()
        if not backend.is_available():
            return None

        # Build observation list from raw observations (no OCR text — metadata only)
        observations = [
            {
                "timestamp": r.timestamp,
                "app": r.app,
                "window_title": r.window_title,
                "entities": r.entities,
            }
            for r in episode._raw_observations
        ]

        result = backend.summarize_episode(
            episode_name=episode.case_name,
            started_at=episode.started_at,
            ended_at=episode.ended_at or "",
            duration_minutes=episode.duration_minutes,
            observations=observations,
        )

        if result.inference_failed:
            log.error("finalizer.local_inference_failed", episode_id=episode.id)
            # Do not fall through silently — log and return failed marker
            return [], result.activity_classification, result.classification_confidence, True

        key_obs = [
            KeyObservation(timestamp=o["timestamp"], text=o["text"])
            for o in result.key_observations
            if o.get("timestamp") and o.get("text")
        ][:config.MAX_KEY_OBSERVATIONS]

        return (
            key_obs,
            result.activity_classification,
            result.classification_confidence,
            False,
        )
    except Exception as e:
        log.error("finalizer.local_inference_error", error=str(e))
        return None


# ── Server path ────────────────────────────────────────────────────────────────

def _server_observations(
    episode: Episode,
) -> tuple[list[KeyObservation], str | None, float | None, bool] | None:
    """
    POST to /api/agent/finalize to generate observations via server-side Claude.
    Returns None on any failure (caller uses template fallback).
    """
    token = auth.read_credential()
    if not token:
        return None

    body: dict = {
        "episode_name": episode.case_name,
        "episode_objective": episode._objective,
        "started_at": episode.started_at,
        "ended_at": episode.ended_at,
        "duration_minutes": episode.duration_minutes,
    }

    if episode._evidence:
        body["evidence_items"] = [
            {
                "timestamp": ev.timestamp,
                "app_context": ev.app_context,
                "activity_description": ev.activity_description,
                "objective": ev.objective,
                "actions": ev.actions,
                "entities": ev.entities,
                "supporting_evidence": ev.supporting_evidence,
            }
            for ev in episode._evidence
        ]
    else:
        raw = episode._raw_observations
        if not raw:
            return None
        body["activity_log"] = _activity_log(_deduplicate(raw))

    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{config.BASE_URL}/api/agent/finalize",
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
    except Exception as e:
        log.error("finalizer.server_call_failed", error=str(e))
        return None

    if not result.get("success"):
        return None

    observations = result.get("observations", [])
    key_obs = [
        KeyObservation(timestamp=o["timestamp"], text=o["text"])
        for o in observations
        if isinstance(o, dict) and o.get("timestamp") and o.get("text")
    ][:config.MAX_KEY_OBSERVATIONS]
    return key_obs, None, None, False


# ── Activity log ──────────────────────────────────────────────────────────────

def _activity_log(raw: list[RawObservation]) -> str:
    """Format raw observations as a compact activity log for Claude context."""
    lines = []
    for r in raw:
        parts = [r.timestamp]
        if r.app:
            parts.append(r.app)
        if r.window_title:
            parts.append(f'"{r.window_title}"')
        if r.browser_url:
            parts.append(r.browser_url)
        if r.file_path:
            parts.append(r.file_path)
        if r.entities:
            parts.append("entities: " + ", ".join(r.entities[:4]))
        lines.append(" | ".join(parts))
    return "\n".join(lines)


# ── Template fallback ──────────────────────────────────────────────────────────

def _template_observations(raw: list[RawObservation]) -> list[KeyObservation]:
    """Deterministic fallback used when no API key is configured or all LLM calls fail."""
    key_obs: list[KeyObservation] = []
    for r in raw:
        text = obs_mod.describe(r.app, r.window_title, r.browser_url, r.file_path)
        if not text:
            continue
        if key_obs and key_obs[-1].text == text:
            continue
        key_obs.append(KeyObservation(timestamp=r.timestamp, text=text))
        if len(key_obs) >= config.MAX_KEY_OBSERVATIONS:
            break
    return key_obs


# ── Deduplication ─────────────────────────────────────────────────────────────

def _deduplicate(raw: list[RawObservation]) -> list[RawObservation]:
    """Remove consecutive observations with identical app + window + file context."""
    if not raw:
        return []
    result = [raw[0]]
    for r in raw[1:]:
        prev = result[-1]
        if r.app != prev.app or r.window_title != prev.window_title or r.file_path != prev.file_path:
            result.append(r)
    return result


# ── Screenshot lifecycle (Phase 2) ────────────────────────────────────────────

def _delete_all_screenshots(episode: Episode) -> None:
    """
    Delete all temporary screenshot files associated with this episode.

    Phase 2 target: zero persistent raw screenshots.
    Frames are deleted immediately after extraction — they are never moved to
    evidence/ and never uploaded to cloud storage.
    """
    seen: set[str] = set()

    for ev in episode._evidence:
        if ev.screenshot_path and ev.screenshot_path not in seen:
            seen.add(ev.screenshot_path)
            _unlink(ev.screenshot_path)

    for r in episode._raw_observations:
        if r.screenshot_path and r.screenshot_path not in seen:
            seen.add(r.screenshot_path)
            _unlink(r.screenshot_path)


def _unlink(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except Exception as e:
        log.debug("finalizer.unlink_failed", path=path, error=str(e))
