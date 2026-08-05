"""Stable installation UUID, persisted outside the app bundle."""
import json
import sys
import uuid
import datetime
from pathlib import Path


def _data_dir() -> Path:
    if sys.platform == 'win32':
        import os
        base = os.environ.get('LOCALAPPDATA') or (Path.home() / 'AppData' / 'Local')
        return Path(base) / 'BuildHarvey'
    elif sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'BuildHarvey'
    return Path.home() / '.buildharvey-data'


def get_installation_id() -> str:
    """Return stable UUID for this installation. Created once, never regenerated."""
    d = _data_dir()
    d.mkdir(parents=True, exist_ok=True)
    f = d / 'device.json'
    if f.exists():
        try:
            data = json.loads(f.read_text())
            iid = data.get('installation_id', '')
            uuid.UUID(iid)   # validates format
            return iid
        except Exception:
            pass
    iid = str(uuid.uuid4())
    f.write_text(json.dumps({
        'installation_id': iid,
        'created_at': datetime.datetime.utcnow().isoformat() + 'Z',
    }, indent=2))
    return iid
