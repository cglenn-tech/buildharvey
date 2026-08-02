-- Episode screenshots table.
-- One row per uploaded screenshot, linked to the episode.
-- Storage bucket "episode-screenshots" must be created manually in the
-- Supabase dashboard: Storage → New bucket → "episode-screenshots" (private).

CREATE TABLE IF NOT EXISTS episode_screenshots (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  episode_id   UUID NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  storage_path TEXT NOT NULL,
  uploaded_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE episode_screenshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users see own screenshots" ON episode_screenshots
  FOR SELECT USING (auth.uid() = user_id);

CREATE INDEX episode_screenshots_episode_idx ON episode_screenshots (episode_id);
