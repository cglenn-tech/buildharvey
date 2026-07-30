"""
Episode Finalizer.

Runs once when an episode closes, before it is persisted.

Responsibilities:
  - Deduplicate consecutive identical contexts
  - Generate rich key observations via Claude Vision (screenshots as primary evidence)
  - Fall back to text-only LLM summary, then to templates if unavailable
  - Cap at MAX_KEY_OBSERVATIONS
  - Delete all saved screenshots after finalization

Screenshots are the primary source of truth.
Metadata (app, URL, window title, entities) is supporting evidence.
"""
import base64
import json
from pathlib import Path

import config
import observations as obs_mod
from episode import Episode, KeyObservation, RawObservation


def finalize(episode: Episode) -> None:
    """
    Process a closed episode in place.
    Sets episode.key_observations from the raw buffer, then clears the buffer.
    Screenshots are always deleted regardless of success or failure.
    """
    raw = episode._raw_observations
    if not raw:
        return

    deduped = _deduplicate(raw)

    try:
        key_obs = _llm_observations(episode, deduped) if config.ANTHROPIC_API_KEY else []
        if not key_obs:
            key_obs = _template_observations(deduped)
        episode.key_observations = key_obs
    finally:
        _cleanup_screenshots(raw)
        episode._raw_observations = []


# ── LLM-based observation generation ──────────────────────────────────────────

def _llm_observations(episode: Episode, raw: list[RawObservation]) -> list[KeyObservation]:
    """
    Use Claude to produce rich narrative observations.

    Prefers vision-based analysis when screenshots are available.
    Screenshots are the primary evidence; metadata is supporting context.
    Falls back to text-only metadata when no screenshots exist.
    """
    try:
        import anthropic
    except ImportError:
        return []

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    screenshot_paths = _select_screenshots(raw)

    try:
        if screenshot_paths:
            return _vision_observations(client, episode, raw, screenshot_paths)
        else:
            return _text_observations(client, episode, raw)
    except Exception as e:
        print(f"[finalizer] LLM observation failed: {e}")
        return []


def _select_screenshots(raw: list[RawObservation]) -> list[str]:
    """
    Return up to MAX_VISION_SCREENSHOTS screenshot paths, evenly distributed
    across the episode so we get coverage from start to end.
    """
    paths = [r.screenshot_path for r in raw if r.screenshot_path]
    if not paths:
        return []

    n = config.MAX_VISION_SCREENSHOTS
    if len(paths) <= n:
        return paths

    # Evenly sample n paths across the full list
    indices = [int(round(i * (len(paths) - 1) / (n - 1))) for i in range(n)]
    return [paths[i] for i in indices]


def _vision_observations(
    client,
    episode: Episode,
    raw: list[RawObservation],
    screenshot_paths: list[str],
) -> list[KeyObservation]:
    """
    Build a multimodal Claude Vision call.

    Screenshots are the primary evidence of what work occurred.
    Metadata (timestamps, window titles, URLs, entities) is included as
    supporting context to help ground the visual analysis.
    """
    # Build a quick-reference index: screenshot path → raw observation
    path_to_raw: dict[str, RawObservation] = {}
    for r in raw:
        if r.screenshot_path and r.screenshot_path not in path_to_raw:
            path_to_raw[r.screenshot_path] = r

    # Build the metadata activity log as supporting context
    log_lines = []
    for r in raw:
        parts = [r.timestamp]
        if r.window_title:
            parts.append(f'"{r.window_title}"')
        if r.browser_url:
            parts.append(r.browser_url)
        if r.file_path:
            parts.append(r.file_path)
        if r.entities:
            parts.append("entities: " + ", ".join(r.entities[:6]))
        log_lines.append(" | ".join(parts))

    activity_log = "\n".join(log_lines)

    # Build the multimodal content array
    content: list[dict] = []

    content.append({
        "type": "text",
        "text": (
            f"You are analyzing a work session to reconstruct what actually happened.\n\n"
            f"Work subject: {episode.case_name}\n"
            f"Session: {episode.started_at} → {episode.ended_at}\n\n"
            f"Supporting metadata (timestamp | window | url/file | entities):\n"
            f"{activity_log}\n\n"
            f"Below are {len(screenshot_paths)} screenshots from this session. "
            f"Use them as the primary evidence of what work occurred.\n\n"
            f"For each screenshot, examine:\n"
            f"- What is actually visible on screen?\n"
            f"- What content is being read, written, or worked on?\n"
            f"- What task appears to be underway?\n"
            f"- What has meaningfully changed since the previous screenshot?\n"
        ),
    })

    loaded = 0
    for path in screenshot_paths:
        try:
            data = Path(path).read_bytes()
            b64 = base64.standard_b64encode(data).decode("utf-8")

            r = path_to_raw.get(path)
            label_parts = []
            if r:
                label_parts.append(r.timestamp)
                if r.window_title:
                    label_parts.append(r.window_title)
                if r.browser_url:
                    label_parts.append(r.browser_url)
            label = f"Screenshot {loaded + 1}"
            if label_parts:
                label += f" — {' | '.join(label_parts)}"

            content.append({"type": "text", "text": f"\n{label}:"})
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": b64,
                },
            })
            loaded += 1
        except Exception as e:
            print(f"[finalizer] could not load screenshot {path}: {e}")

    if loaded == 0:
        # All screenshots failed to load; fall back to text-only
        return _text_observations(client, episode, raw)

    content.append({
        "type": "text",
        "text": (
            f"\nBased on what is actually visible in these screenshots — not just which "
            f"app or website is open — write up to {config.MAX_KEY_OBSERVATIONS} observations "
            f"describing the real work that occurred.\n\n"
            f"Each observation must:\n"
            f"- Describe the actual visible work ('Reviewed Smith appraisal — coverage "
            f"section page 12' not 'Viewed PDF')\n"
            f"- Reference specific content visible in screenshots: names, documents, "
            f"text being written, data being reviewed, forms being filled\n"
            f"- Note meaningful changes between screenshots when relevant\n"
            f"- Connect context across the session (a name appearing mid-session ties "
            f"to earlier activity)\n"
            f"- Be useful as a memory entry one week later\n\n"
            f"Return ONLY a JSON array with no surrounding text:\n"
            f'[{{"timestamp": "HH:MM", "text": "..."}}]'
        ),
    })

    response = client.messages.create(
        model=config.OBSERVATION_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
    )

    return _parse_response(response.content[0].text)


def _text_observations(
    client,
    episode: Episode,
    raw: list[RawObservation],
) -> list[KeyObservation]:
    """
    Text-only Claude call when no screenshots are available.
    Used as fallback when screenshot saving fails across an entire episode.
    """
    lines = []
    for r in raw:
        parts = [r.timestamp]
        if r.window_title:
            parts.append(f'"{r.window_title}"')
        if r.browser_url:
            parts.append(r.browser_url)
        if r.file_path:
            parts.append(r.file_path)
        if r.entities:
            parts.append("entities: " + ", ".join(r.entities[:6]))
        lines.append(" | ".join(parts))

    context_block = "\n".join(lines)

    prompt = (
        f"You are analyzing screen captures from a work session to create rich memory observations.\n\n"
        f"Work subject: {episode.case_name}\n"
        f"Session: {episode.started_at} → {episode.ended_at}\n\n"
        f"Each line is one screen capture (timestamp | window title | entities detected):\n\n"
        f"{context_block}\n\n"
        f"Write up to {config.MAX_KEY_OBSERVATIONS} observations that capture what the user was doing.\n\n"
        f"Each observation must:\n"
        f"- Describe the ACTIVITY, not the screen ('Reviewed the Smith appraisal' not 'Viewed PDF')\n"
        f"- Include names, organizations, case numbers, documents, or projects that appeared\n"
        f"- Connect context across captures when helpful\n"
        f"- Be useful as a memory entry one week later\n\n"
        f"Return ONLY a JSON array with no surrounding text:\n"
        f'[{{"timestamp": "HH:MM", "text": "..."}}]'
    )

    response = client.messages.create(
        model=config.OBSERVATION_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    return _parse_response(response.content[0].text)


def _parse_response(text: str) -> list[KeyObservation]:
    """Parse a Claude JSON response into KeyObservations."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    data = json.loads(text)
    result = [
        KeyObservation(timestamp=d["timestamp"], text=d["text"])
        for d in data
        if isinstance(d, dict) and d.get("timestamp") and d.get("text")
    ]
    return result[: config.MAX_KEY_OBSERVATIONS]


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


# ── Screenshot cleanup ─────────────────────────────────────────────────────────

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
