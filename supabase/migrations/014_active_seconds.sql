-- Add active_seconds to episodes.
-- Tracks billable/active time after subtracting paused periods.
-- Nullable: existing episodes recorded before this change will have NULL.
ALTER TABLE public.episodes
  ADD COLUMN IF NOT EXISTS active_seconds NUMERIC;
