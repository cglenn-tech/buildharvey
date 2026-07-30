"""
Episode Finalizer.

Runs once when an episode closes, before it is persisted.

Responsibilities:
  - Deduplicate consecutive identical contexts
  - Generate key observations from the compressed context
  - Cap at MAX_KEY_OBSERVATIONS

After finalization, the raw observation buffer is cleared.
"""
import config
import observations as obs_mod
from episode import Episode, KeyObservation, RawObservation


def finalize(episode: Episode) -> None:
    """
    Process a closed episode in place.
    Sets episode.key_observations from the raw buffer, then clears the buffer.
    """
    raw = episode._raw_observations
    if not raw:
        return

    deduped = _deduplicate(raw)
    key_obs: list[KeyObservation] = []

    for r in deduped:
        text = obs_mod.describe(r.app, r.window_title, r.browser_url, r.file_path)
        if not text:
            continue
        if key_obs and key_obs[-1].text == text:
            continue  # skip exact consecutive duplicate
        key_obs.append(KeyObservation(timestamp=r.timestamp, text=text))
        if len(key_obs) >= config.MAX_KEY_OBSERVATIONS:
            break

    episode.key_observations = key_obs
    episode._raw_observations = []  # free memory


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
