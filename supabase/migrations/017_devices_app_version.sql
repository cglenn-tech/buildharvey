-- Migration 017: Add app_version to devices table
ALTER TABLE devices ADD COLUMN IF NOT EXISTS app_version TEXT;
