"""
Episode Finalizer.

Runs once when an episode closes, before it is persisted.

Preferred path: POST to /api/agent/finalize with accumulated ScreenshotEvidence.
The server synthesizes observations using Claude (text-only — screenshots were
already analyzed during the session).

Fallback path (when no evidence exists): POST activity log to /api/agent/finalize.

Template fallback: deterministic observations from raw metadata when server call
fails or times out.

Core philosophy: produce observations that read like an executive assistant
summarized the work — not browser history. Synthesize. Connect. Reconstruct.
"""
import json
import shutil
import urllib.request
from pathlib import Path

import auth
import config
import observations as obs_mod
from episode import Episode, KeyObservation, RawObservation

# Directory for evidence screenshots that survive finalization
EVIDENCE_BASE = config.BASE_DIR / "evidence"
EVIDENCE_BASE.mkdir(exist_ok=True)


def finalize(episode: Episode) -> None:
    """
    Process a closed episode in place.
    Sets episode.key_observations and episode.evidence_paths.
    Selected screenshots are moved to ~/.buildharvey/evidence/<episode_id>/.
    All other tmp screenshots are deleted.
    """
    try:
        key_obs = _generate_observations(episode)
        episode.key_observations = key_obs
    finally:
        # Collect all screenshot paths from both evidence and raw observations
        all_paths: list[str] = []
        seen: set[str] = set()

        for ev in episode._evidence:
            if ev.screenshot_path and ev.screenshot_path not in seen:
                seen.add(ev.screenshot_path)
                all_paths.append(ev.screenshot_path)

        for r in episode._raw_observations:
            if r.screenshot_path and r.screenshot_path not in seen:
                seen.add(r.screenshot_path)
                all_paths.append(r.screenshot_path)

        # Select representative screenshots to preserve as evidence
        selected = _select_screenshots_from_paths(all_paths)
        episode.evidence_paths = _move_to_evidence(episode.id, selected)

        # Delete everything that wasn't selected
        for path in all_paths:
            if path not in selected:
                try:
                    Path(path).unlink(missing_ok=True)
                except Exception:
                    pass

        episode._raw_observations = []
        # Do not clear _evidence — the caller may inspect it before discard


def _generate_observations(episode: Episode) -> list[KeyObservation]:
    result = _server_observations(episode)
    if result is not None:
        return result
    return _template_observations(episode._raw_observations)


# ── Server call ───────────────────────────────────────────────────────────────

def _server_observations(episode: Episode) -> list[KeyObservation] | None:
    """
    POST to /api/agent/finalize to generate observations via server-side Claude.
    Returns a list of KeyObservations, or None on any failure (caller uses template).
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
        print(f"[finalizer] server call failed: {e}")
        return None

    if not result.get("success"):
        return None

    observations = result.get("observations", [])
    return [
        KeyObservation(timestamp=o["timestamp"], text=o["text"])
        for o in observations
        if isinstance(o, dict) and o.get("timestamp") and o.get("text")
    ][:config.MAX_KEY_OBSERVATIONS]


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
    """Deterministic fallback used when no API key is configured or LLM call fails."""
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


# ── Evidence screenshot management ────────────────────────────────────────────

def _select_screenshots_from_paths(paths: list[str]) -> list[str]:
    """Select up to MAX_VISION_SCREENSHOTS paths, evenly distributed."""
    if not paths:
        return []
    n = config.MAX_VISION_SCREENSHOTS
    if len(paths) <= n:
        return list(paths)
    indices = [int(round(i * (len(paths) - 1) / (n - 1))) for i in range(n)]
    return [paths[i] for i in indices]


def _move_to_evidence(episode_id: str, paths: list[str]) -> list[str]:
    """
    Move selected screenshots to ~/.buildharvey/evidence/<episode_id>/.
    Returns list of new paths. Files that fail to move are skipped silently.
    """
    dest_dir = EVIDENCE_BASE / episode_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for i, src in enumerate(paths):
        src_path = Path(src)
        if not src_path.exists():
            continue
        dest = dest_dir / f"frame_{i:03d}{src_path.suffix}"
        try:
            shutil.move(str(src_path), str(dest))
            moved.append(str(dest))
        except Exception as e:
            print(f"[finalizer] could not move {src}: {e}")
    return moved


# ── Screenshot cleanup (legacy) ────────────────────────────────────────────────

def _cleanup_screenshots(raw: list[RawObservation]) -> None:
    """Delete all screenshot files associated with this episode's observations."""
    seen: set[str] = set()
    for r in raw:
        if r.screenshot_path and r.screenshot_path not in seen:
            seen.add(r.screenshot_path)
            try:
                Path(r.screenshot_path).unlink(missing_ok=True)
            except Exception:
                pass
