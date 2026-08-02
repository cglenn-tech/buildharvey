-- Creates weekly_reports with all columns (initial + period metadata + structured output).
-- Self-contained: safe to run whether or not migration 008 was previously applied.

CREATE TABLE IF NOT EXISTS weekly_reports (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  week_start          DATE NOT NULL,
  week_end            DATE NOT NULL,
  period_start        DATE,
  period_end          DATE,
  period_label        TEXT,
  source_episode_ids  JSONB DEFAULT '[]',
  summary_json        JSONB,
  content             TEXT NOT NULL,
  version             INTEGER NOT NULL DEFAULT 1,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Add new columns to any pre-existing rows (no-op if table was just created)
ALTER TABLE weekly_reports
  ADD COLUMN IF NOT EXISTS period_start       DATE,
  ADD COLUMN IF NOT EXISTS period_end         DATE,
  ADD COLUMN IF NOT EXISTS period_label       TEXT,
  ADD COLUMN IF NOT EXISTS source_episode_ids JSONB DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS summary_json       JSONB;

ALTER TABLE weekly_reports ENABLE ROW LEVEL SECURITY;

-- Safe policy creation (CREATE POLICY IF NOT EXISTS requires PG17; use DO block instead)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename  = 'weekly_reports'
      AND policyname = 'users manage own reports'
  ) THEN
    CREATE POLICY "users manage own reports" ON weekly_reports
      USING (auth.uid() = user_id)
      WITH CHECK (auth.uid() = user_id);
  END IF;
END $$;

-- Backfill period columns from existing rows
UPDATE weekly_reports
  SET period_start = week_start,
      period_end   = week_end
  WHERE period_start IS NULL;

CREATE INDEX IF NOT EXISTS weekly_reports_user_week_idx
  ON weekly_reports (user_id, week_start DESC);

CREATE INDEX IF NOT EXISTS weekly_reports_period_idx
  ON weekly_reports (user_id, period_start, period_end);
