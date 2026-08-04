-- Migration 018: Add minimum_version to app_releases table
ALTER TABLE app_releases ADD COLUMN IF NOT EXISTS minimum_version TEXT;
