"""Supabase Storage uploads."""
from pathlib import Path
from typing import Optional

import config


def upload(local_path: Path, episode_id: str, screenshot_id: str) -> Optional[str]:
    """Upload a screenshot PNG and return its public URL, or None on failure."""
    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        return None
    try:
        from supabase import create_client
        client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
        remote_path = f"{episode_id}/{screenshot_id}.png"
        with open(local_path, "rb") as f:
            client.storage.from_(config.STORAGE_BUCKET).upload(
                path=remote_path,
                file=f.read(),
                file_options={"content-type": "image/png", "upsert": "true"},
            )
        return client.storage.from_(config.STORAGE_BUCKET).get_public_url(remote_path)
    except Exception as exc:
        print(f"[storage] upload failed: {exc}")
        return None
