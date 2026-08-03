-- Add work_type, issue_worked_on, and edited_at to episodes.
-- Fully backwards-compatible: desktop-agent synced episodes get work_type='project' default.
ALTER TABLE public.episodes
  ADD COLUMN IF NOT EXISTS work_type TEXT NOT NULL DEFAULT 'project'
    CHECK (work_type IN ('project', 'administrative')),
  ADD COLUMN IF NOT EXISTS issue_worked_on TEXT,
  ADD COLUMN IF NOT EXISTS edited_at TIMESTAMPTZ;
