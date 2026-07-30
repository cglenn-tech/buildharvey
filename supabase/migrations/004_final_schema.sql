-- ============================================================
-- BuildHarvey — final schema (run this if starting fresh)
-- Replaces all previous migrations.
-- Paste into Supabase SQL Editor and click Run.
-- ============================================================

DROP TABLE IF EXISTS public.episodes;

CREATE TABLE public.episodes (
    id               TEXT        PRIMARY KEY,
    case_name        TEXT        NOT NULL,
    started_at       TIMESTAMPTZ NOT NULL,
    ended_at         TIMESTAMPTZ,
    duration_minutes NUMERIC,
    key_observations JSONB       NOT NULL DEFAULT '[]',
    created_at       TIMESTAMPTZ NOT NULL
);

CREATE INDEX episodes_started_at_idx
    ON public.episodes (started_at DESC);

ALTER TABLE public.episodes ENABLE ROW LEVEL SECURITY;

-- Web app (anon key) can read and delete episodes
CREATE POLICY "anon_select" ON public.episodes
    FOR SELECT TO anon USING (true);

CREATE POLICY "anon_delete" ON public.episodes
    FOR DELETE TO anon USING (true);
