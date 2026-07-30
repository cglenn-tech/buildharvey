"""
Episode Finalizer.

Runs once when an episode closes, before it is persisted.

Responsibilities:
  - Deduplicate consecutive identical contexts
  - Generate rich key observations via Claude Vision (screenshots as primary evidence)
  - Fall back to text-only LLM summary, then to templates if unavailable
  - Cap at MAX_KEY_OBSERVATIONS
  - Delete all saved screenshots after finalization

Core philosophy: produce observations that read like an executive assistant
summarized the work — not browser history. Synthesize. Connect. Reconstruct.
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

    indices = [int(round(i * (len(paths) - 1) / (n - 1))) for i in range(n)]
    return [paths[i] for i in indices]


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


def _vision_observations(
    client,
    episode: Episode,
    raw: list[RawObservation],
    screenshot_paths: list[str],
) -> list[KeyObservation]:
    """
    Build a multimodal Claude Vision call.

    Screenshots are the primary evidence of what work occurred.
    Metadata is supporting context for grounding the analysis.
    The prompt asks Claude to synthesize and reconstruct — not enumerate.
    """
    path_to_raw: dict[str, RawObservation] = {}
    for r in raw:
        if r.screenshot_path and r.screenshot_path not in path_to_raw:
            path_to_raw[r.screenshot_path] = r

    log = _activity_log(raw)
    duration = episode.duration_minutes

    content: list[dict] = []

    content.append({
        "type": "text",
        "text": (
            f"You are an experienced executive assistant reconstructing a work session "
            f"from screen evidence.\n\n"
            f"Work subject: {episode.case_name}\n"
            f"Session: {episode.started_at} → {episode.ended_at} "
            f"({duration:.0f} minutes)\n\n"
            f"Activity log (timestamp | app | window/url/file | entities):\n"
            f"{log}\n\n"
            f"Below are {len(screenshot_paths)} screenshots from key moments in this session. "
            f"Use them as your primary evidence.\n\n"
            f"Before you write, reason through:\n"
            f"1. What was the user actually trying to accomplish overall?\n"
            f"2. What are the distinct work threads? (e.g., 'drafting X' vs 'researching Y')\n"
            f"3. Does anything appear later in the session that explains earlier activity?\n"
            f"4. Can multiple related observations be synthesized into one clear memory?\n"
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
                if r.app:
                    label_parts.append(r.app)
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
        return _text_observations(client, episode, raw)

    content.append({
        "type": "text",
        "text": _synthesis_instructions(config.MAX_KEY_OBSERVATIONS),
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
    Same synthesis-first philosophy — reconstruct work, not navigation.
    """
    log = _activity_log(raw)
    duration = episode.duration_minutes

    prompt = (
        f"You are an experienced executive assistant reconstructing a work session "
        f"from activity metadata.\n\n"
        f"Work subject: {episode.case_name}\n"
        f"Session: {episode.started_at} → {episode.ended_at} "
        f"({duration:.0f} minutes)\n\n"
        f"Activity log (timestamp | app | window/url/file | entities):\n"
        f"{log}\n\n"
        f"Before you write, reason through:\n"
        f"1. What was the user actually trying to accomplish overall?\n"
        f"2. What are the distinct work threads?\n"
        f"3. Does anything later in the log explain earlier activity? "
        f"(A name or project appearing mid-session often clarifies what came before.)\n"
        f"4. Which entries can be synthesized into one meaningful memory?\n\n"
        + _synthesis_instructions(config.MAX_KEY_OBSERVATIONS)
    )

    response = client.messages.create(
        model=config.OBSERVATION_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    return _parse_response(response.content[0].text)


def _synthesis_instructions(max_obs: int) -> str:
    """
    The core instruction block telling Claude how to produce observations.
    Shared between vision and text-only prompts.
    """
    return (
        f"\nWrite up to {max_obs} observations that reconstruct the actual work. "
        f"These will be read as memories one week later.\n\n"
        f"SYNTHESIZE related activity into single observations:\n"
        f'  Good: "Researched luxury hotel options in New York across multiple sources '
        f'while evaluating relocation costs"\n'
        f'  Bad: "Visited YouTube" / "Visited Aman NYC" / "Searched Google Hotels"\n\n'
        f"DESCRIBE THE WORK, not the tool:\n"
        f'  Good: "Reviewed coverage dispute section of the Smith claim file"\n'
        f'  Bad: "Opened PDF in Preview" / "Used Microsoft Word"\n\n'
        f"CONNECT DELAYED CONTEXT — if a name, project, or subject appears later "
        f"and clearly explains earlier activity, tie them together:\n"
        f'  Good: "Reviewed BuildHarvey deployment configuration while working through '
        f'screenshot-based observation pipeline"\n\n'
        f"BE SPECIFIC about what was visible: document names, people, companies, "
        f"topics, amounts, decisions, problems being solved.\n\n"
        f"ANSWER the questions a colleague would ask a week later:\n"
        f"  - What was being accomplished?\n"
        f"  - Why did it matter?\n"
        f"  - What specifically was worked on?\n\n"
        f"Return ONLY a JSON array with no surrounding text:\n"
        f'[{{"timestamp": "HH:MM", "text": "..."}}]'
    )


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
