"""
Live screenshot analysis via Claude Vision.

Analyzes a single screenshot against current episode context and returns
validated ScreenshotEvidence or None.

Claude — not OCR or NER — names episodes, decides boundaries, and determines
whether a screenshot is meaningful. Raw metadata is supporting context only.

Returns None on:
  - API failure (buffers screenshot for retry)
  - Validation failure (partial/malformed response)
  - Non-meaningful screenshot (loading screen, idle, etc.)
  - Personal/irrelevant content (entertainment, non-work)
"""
import json
import base64
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import config
from episode import ScreenshotEvidence


_REQUIRED_FIELDS = {
    "meaningful",
    "personal_or_irrelevant",
    "activity_description",
    "objective",
    "entities",
    "actions",
    "continue_current_episode",
    "start_new_episode",
    "suggested_episode_name",
    "supporting_evidence",
}


def analyze(obs, context: dict) -> Optional[ScreenshotEvidence]:
    """
    Analyze a screenshot against current episode context.

    obs: an Observation with screenshot_path attribute
    context: dict from EpisodeEngine.get_context()

    Returns ScreenshotEvidence if valid and meaningful, None otherwise.
    """
    if not config.ANTHROPIC_API_KEY:
        return None

    screenshot_path = getattr(obs, "screenshot_path", None)
    if not screenshot_path:
        return None

    try:
        import anthropic
    except ImportError:
        return None

    try:
        data = Path(screenshot_path).read_bytes()
    except Exception as e:
        print(f"[vision] failed — could not read screenshot: {e} (buffering screenshot)")
        return None

    b64 = base64.standard_b64encode(data).decode("utf-8")
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    import time
    timestamp = time.strftime("%H:%M")

    try:
        response = client.messages.create(
            model=config.VISION_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": _build_content(b64, context, obs)}],
        )
    except Exception as e:
        print(f"[vision] failed — {e} (buffering screenshot)")
        return None

    raw_text = response.content[0].text if response.content else ""

    parsed = _parse_response(raw_text)
    if parsed is None:
        return None

    error = _validate(parsed)
    if error:
        print(f"[vision] rejected — validation: {error}")
        return None

    if not parsed["meaningful"]:
        print("[vision] rejected — not meaningful")
        return None

    if parsed["personal_or_irrelevant"]:
        print("[vision] discarded — personal/irrelevant")
        return None

    app_context = _app_context(obs)
    evidence = ScreenshotEvidence(
        screenshot_path=screenshot_path,
        timestamp=timestamp,
        activity_description=parsed["activity_description"],
        objective=parsed["objective"],
        actions=parsed["actions"],
        entities=parsed["entities"],
        supporting_evidence=parsed["supporting_evidence"],
        app_context=app_context,
        model=config.VISION_MODEL,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        continue_current_episode=parsed["continue_current_episode"],
        start_new_episode=parsed["start_new_episode"],
        suggested_episode_name=parsed["suggested_episode_name"],
    )

    print(
        f"[vision] accepted — {parsed['suggested_episode_name']} | "
        f"meaningful=true | {response.usage.input_tokens}t/{response.usage.output_tokens}t"
    )
    return evidence


def _build_content(b64: str, context: dict, obs) -> list:
    app_info = _app_context(obs)
    current_ep = context.get("current_episode_name", "")
    current_obj = context.get("current_objective", "")
    duration = context.get("episode_duration_minutes", 0)
    recent_actions = context.get("recent_actions", [])
    known_entities = context.get("known_entities", [])

    context_block = ""
    if current_ep:
        context_block = (
            f"\nCurrent episode: {current_ep}\n"
            f"Current objective: {current_obj}\n"
            f"Duration so far: {duration:.0f} minutes\n"
        )
        if recent_actions:
            flat = []
            for sublist in recent_actions:
                if isinstance(sublist, list):
                    flat.extend(sublist)
                elif sublist:
                    flat.append(sublist)
            if flat:
                context_block += f"Recent actions: {'; '.join(flat[-6:])}\n"
        if known_entities:
            context_block += f"Known entities: {', '.join(known_entities[:10])}\n"

    prompt = (
        f"You are analyzing a screenshot to determine what work is being done.\n"
        f"App context: {app_info}{context_block}\n\n"
        f"Analyze the screenshot carefully and respond with ONLY valid JSON matching this exact schema:\n\n"
        f'{{\n'
        f'  "meaningful": true,\n'
        f'  "personal_or_irrelevant": false,\n'
        f'  "activity_description": "Specific description of what is visible and what work is being done",\n'
        f'  "objective": "What the user is trying to accomplish overall",\n'
        f'  "entities": [{{"name": "EntityName", "type": "project|client|case|person|company|tool", "evidence_strength": "strong|moderate|weak"}}],\n'
        f'  "actions": ["Specific action 1", "Specific action 2"],\n'
        f'  "continue_current_episode": true,\n'
        f'  "start_new_episode": false,\n'
        f'  "suggested_episode_name": "Descriptive Name — Specific Task",\n'
        f'  "supporting_evidence": ["Visual evidence item 1", "Visual evidence item 2"]\n'
        f'}}\n\n'
        f"Rules for meaningful:\n"
        f"- Set meaningful=false for: loading screens, blank screens, idle desktops, screensavers, "
        f"login prompts, menus with no work context, reset states\n"
        f"- Set meaningful=true for any actual work activity\n\n"
        f"Rules for personal_or_irrelevant:\n"
        f"- Set personal_or_irrelevant=true ONLY for clearly non-work activity (entertainment, "
        f"personal social media browsing unrelated to work)\n"
        f"- Do NOT set personal_or_irrelevant=true for: email, scheduling, admin tasks, "
        f"research, meetings, overhead work\n\n"
        f"Rules for episode boundaries:\n"
        f"- continue_current_episode=true when work relates to the same objective — switching "
        f"apps does NOT split episodes (GitHub → terminal → Vercel → Supabase for the same "
        f"project is ONE episode)\n"
        f"- start_new_episode=true ONLY when the objective has clearly shifted to unrelated work\n"
        f"- continue_current_episode and start_new_episode must NOT both be true\n\n"
        f"Rules for suggested_episode_name:\n"
        f'- Must be specific and descriptive: "BuildHarvey — Deployment Debugging" NOT just "BuildHarvey"\n'
        f"- Must NOT be empty or a placeholder if meaningful=true\n"
        f"- Must NOT be empty if start_new_episode=true\n\n"
        f"Respond with ONLY the JSON object. No explanation, no markdown."
    )

    return [
        {"type": "text", "text": prompt},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": b64,
            },
        },
    ]


def _parse_response(text: str) -> Optional[dict]:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"[vision] rejected — invalid JSON: {e}")
        return None


def _validate(data: dict) -> Optional[str]:
    """Return error string if invalid, None if valid."""
    for f in _REQUIRED_FIELDS:
        if f not in data:
            return f"missing field '{f}'"

    if not isinstance(data["meaningful"], bool):
        return "meaningful must be bool"
    if not isinstance(data["personal_or_irrelevant"], bool):
        return "personal_or_irrelevant must be bool"
    if not isinstance(data["continue_current_episode"], bool):
        return "continue_current_episode must be bool"
    if not isinstance(data["start_new_episode"], bool):
        return "start_new_episode must be bool"
    if not isinstance(data["entities"], list):
        return "entities must be list"
    if not isinstance(data["actions"], list):
        return "actions must be list"
    if not isinstance(data["supporting_evidence"], list):
        return "supporting_evidence must be list"

    if data["continue_current_episode"] and data["start_new_episode"]:
        return "continue_current_episode and start_new_episode are both true"

    if not data["meaningful"] and data["actions"]:
        return "meaningful=false but actions is non-empty"

    if data["meaningful"]:
        if not str(data.get("objective", "")).strip():
            return "meaningful=true but objective is empty"
        if not str(data.get("suggested_episode_name", "")).strip():
            return "meaningful=true but suggested_episode_name is empty"

    if data["start_new_episode"]:
        if not str(data.get("suggested_episode_name", "")).strip():
            return "start_new_episode=true but suggested_episode_name is empty"

    return None


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
