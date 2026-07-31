-- ============================================================
-- BuildHarvey — Auth, Devices, and Activation
-- Migration 006
-- ============================================================

-- ── profiles ─────────────────────────────────────────────────────────────────
-- Created on email verification via auth callback.

CREATE TABLE IF NOT EXISTS profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users read own profile" ON profiles FOR SELECT USING (auth.uid() = id);
CREATE POLICY "users update own profile" ON profiles FOR UPDATE USING (auth.uid() = id);

-- ── devices ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS devices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  platform TEXT NOT NULL DEFAULT 'macos',
  token_hash TEXT NOT NULL UNIQUE,
  activated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE devices ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users see own devices" ON devices FOR SELECT USING (auth.uid() = user_id);

-- ── device_activations ────────────────────────────────────────────────────────
-- Internal only — RLS on, no client policies (deny-all to anon/authed).

CREATE TABLE IF NOT EXISTS device_activations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  token_hash TEXT NOT NULL,
  polling_verifier TEXT NOT NULL,
  device_name TEXT,
  platform TEXT NOT NULL DEFAULT 'macos',
  expires_at TIMESTAMPTZ NOT NULL,
  approved_at TIMESTAMPTZ,
  approved_by UUID REFERENCES auth.users(id),
  device_id UUID REFERENCES devices(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE device_activations ENABLE ROW LEVEL SECURITY;
-- No client policies: only service-role access via API routes

-- ── rate_limit_windows ────────────────────────────────────────────────────────
-- Internal only.

CREATE TABLE IF NOT EXISTS rate_limit_windows (
  key TEXT PRIMARY KEY,
  count INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE rate_limit_windows ENABLE ROW LEVEL SECURITY;
-- No client policies

-- Atomic increment function for rate limiting
CREATE OR REPLACE FUNCTION rate_limit_increment(p_key TEXT) RETURNS INTEGER AS $$
  INSERT INTO rate_limit_windows (key, count) VALUES (p_key, 1)
  ON CONFLICT (key) DO UPDATE SET count = rate_limit_windows.count + 1
  RETURNING count;
$$ LANGUAGE SQL;

-- Periodic cleanup (run via pg_cron or on startup):
-- DELETE FROM rate_limit_windows WHERE created_at < now() - interval '2 hours';

-- ── app_releases ──────────────────────────────────────────────────────────────
-- Internal only (read by server components via admin client).

CREATE TABLE IF NOT EXISTS app_releases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  platform TEXT NOT NULL DEFAULT 'macos',
  version TEXT NOT NULL,
  storage_path TEXT NOT NULL,
  sha256 TEXT,
  active BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE app_releases ENABLE ROW LEVEL SECURITY;
-- No client policies

-- Enforce only one active release per platform
CREATE UNIQUE INDEX IF NOT EXISTS app_releases_one_active
  ON app_releases (platform) WHERE active = true;

-- ── download_events ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS download_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id),
  release_id UUID NOT NULL REFERENCES app_releases(id),
  downloaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE download_events ENABLE ROW LEVEL SECURITY;
-- No client policies (server inserts via admin; user access not needed from browser)

-- ── episodes: add ownership ───────────────────────────────────────────────────

ALTER TABLE episodes ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id);
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS device_id UUID REFERENCES devices(id);
CREATE INDEX IF NOT EXISTS episodes_user_idx ON episodes (user_id, started_at DESC);

-- Drop old open policies
DROP POLICY IF EXISTS "Allow public read" ON episodes;
DROP POLICY IF EXISTS "Allow public delete" ON episodes;
DROP POLICY IF EXISTS "Allow anon select" ON episodes;
DROP POLICY IF EXISTS "Allow anon delete" ON episodes;
DROP POLICY IF EXISTS "anon_select" ON episodes;
DROP POLICY IF EXISTS "anon_delete" ON episodes;

-- Authenticated-only policies
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename='episodes' AND policyname='users read own episodes'
  ) THEN
    CREATE POLICY "users read own episodes" ON episodes FOR SELECT USING (auth.uid() = user_id);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename='episodes' AND policyname='users delete own episodes'
  ) THEN
    CREATE POLICY "users delete own episodes" ON episodes FOR DELETE USING (auth.uid() = user_id);
  END IF;
END $$;

-- Mark all existing rows (no user_id) as non-reportable.
-- They remain in DB but are invisible to all users under RLS.
UPDATE episodes SET is_reportable = false WHERE user_id IS NULL;
