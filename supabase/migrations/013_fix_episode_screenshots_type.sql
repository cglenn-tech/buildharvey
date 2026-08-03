-- Fix type mismatch: episode_screenshots.episode_id was UUID but episodes.id is TEXT.
-- Drop the broken FK, cast the column to TEXT (preserving existing rows), recreate FK with CASCADE,
-- and add a unique constraint on (user_id, storage_path) to prevent duplicate confirmations.

-- Step 1: drop the broken foreign key
ALTER TABLE public.episode_screenshots
  DROP CONSTRAINT IF EXISTS episode_screenshots_episode_id_fkey;

-- Step 2: change column type with explicit cast (safe — UUID values are valid TEXT)
ALTER TABLE public.episode_screenshots
  ALTER COLUMN episode_id TYPE TEXT USING episode_id::text;

-- Step 3: recreate foreign key — now TEXT-to-TEXT, with ON DELETE CASCADE preserved
ALTER TABLE public.episode_screenshots
  ADD CONSTRAINT episode_screenshots_episode_id_fkey
    FOREIGN KEY (episode_id)
    REFERENCES public.episodes(id)
    ON DELETE CASCADE;

-- Step 4: unique constraint prevents duplicate screenshot confirmations per user+path
CREATE UNIQUE INDEX IF NOT EXISTS episode_screenshots_user_storage_path_unique
  ON public.episode_screenshots(user_id, storage_path);
