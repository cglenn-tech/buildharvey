"""
One-shot Supabase provisioning check.

Run once before starting the agent:

    source .venv/bin/activate
    python setup_supabase.py

The episodes table must be created via the Supabase SQL Editor.
See: ../supabase/migrations/002_redesign.sql (or 003_remove_screenshots.sql if upgrading)
"""
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import config

if not config.SUPABASE_URL or not config.SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in agent/.env")
    sys.exit(1)

from supabase import create_client
client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

try:
    client.table("episodes").select("id").limit(1).execute()
    print("[db] episodes table found")
except Exception as exc:
    print(f"[db] episodes table NOT found: {exc}")
    print()
    print("Run the SQL migration in the Supabase SQL Editor:")
    print("  supabase/migrations/002_redesign.sql")
    sys.exit(1)

print()
print("Supabase backend ready. You can now run:  python main.py")
