-- Weekly reports table.
-- Each generated report is a new row; multiple versions per week are allowed.
-- The web app shows the latest version per week (max version per week_start).

CREATE TABLE IF NOT EXISTS weekly_reports (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  week_start    DATE NOT NULL,
  week_end      DATE NOT NULL,
  content       TEXT NOT NULL,
  version       INTEGER NOT NULL DEFAULT 1,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE weekly_reports ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users manage own reports" ON weekly_reports
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

CREATE INDEX weekly_reports_user_week_idx
  ON weekly_reports (user_id, week_start DESC);
