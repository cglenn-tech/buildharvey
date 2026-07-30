-- ============================================================
-- BuildHarvey v3 — remove screenshots from episodes
-- Run in the Supabase SQL Editor after 002_redesign.sql
-- ============================================================

ALTER TABLE public.episodes DROP COLUMN IF EXISTS screenshots;
