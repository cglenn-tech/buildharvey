-- ============================================================
-- BuildHarvey v2 — Supabase schema redesign
-- Run this in the Supabase SQL Editor after 001_create_episodes.sql
-- ============================================================

-- Drop the v1 episodes table (incompatible schema)
DROP TABLE IF EXISTS public.episodes;

-- ── Episodes ──────────────────────────────────────────────────────────────────
--
-- Each row = one work episode on one case.
-- key_observations: [{timestamp, text}]   — small list of meaningful work notes
-- screenshots:      [{id, timestamp, storageUrl}]  — 1–3 representative frames only
-- No full OCR dumps. No browser history. No raw observations.

CREATE TABLE public.episodes (
    id               TEXT        PRIMARY KEY,
    case_name        TEXT        NOT NULL,
    started_at       TIMESTAMPTZ NOT NULL,
    ended_at         TIMESTAMPTZ,
    duration_minutes NUMERIC,
    key_observations JSONB       NOT NULL DEFAULT '[]',
    screenshots      JSONB       NOT NULL DEFAULT '[]',
    created_at       TIMESTAMPTZ NOT NULL
);

-- Index used by the web app (ORDER BY started_at DESC) and report generation
CREATE INDEX episodes_started_at_idx
    ON public.episodes (started_at DESC);

-- Index for report generation queries that filter by date range
CREATE INDEX episodes_case_started_idx
    ON public.episodes (case_name, started_at DESC);

-- Row-level security
-- Service-role key (used by the agent) bypasses RLS entirely.
-- Anon key (used by the web app) needs SELECT and DELETE.
ALTER TABLE public.episodes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon_select" ON public.episodes
    FOR SELECT TO anon USING (true);

CREATE POLICY "anon_delete" ON public.episodes
    FOR DELETE TO anon USING (true);
