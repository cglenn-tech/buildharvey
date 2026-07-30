-- ============================================================
-- BuildHarvey — Supabase backend provisioning
-- Run this once in the Supabase SQL Editor:
--   Dashboard → SQL Editor → New query → paste → Run
-- ============================================================

-- Episodes table
-- Matches episode.to_dict() exactly.
-- storyline / screenshots are JSONB arrays.

CREATE TABLE IF NOT EXISTS public.episodes (
    id          TEXT        PRIMARY KEY,
    title       TEXT        NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL,
    ended_at    TIMESTAMPTZ,
    summary     TEXT        NOT NULL DEFAULT '',
    storyline   JSONB       NOT NULL DEFAULT '[]',
    screenshots JSONB       NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ NOT NULL
);

-- Index used by the web app (ORDER BY started_at DESC)
CREATE INDEX IF NOT EXISTS episodes_started_at_idx
    ON public.episodes (started_at DESC);

-- Row-level security
-- The agent uses the service-role key, which bypasses RLS entirely.
-- The web app (anon key) needs SELECT and DELETE.
ALTER TABLE public.episodes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon_select" ON public.episodes
    FOR SELECT TO anon USING (true);

CREATE POLICY "anon_delete" ON public.episodes
    FOR DELETE TO anon USING (true);
