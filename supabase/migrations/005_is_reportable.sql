-- Migration 005: Add is_reportable column to episodes
--
-- Invalid/garbage episodes are flagged, not deleted.
-- This allows the report generator to filter them out while keeping
-- records available for audit and manual review.
--
-- Apply to Supabase before deploying the updated agent.
-- SQLite migration is handled automatically by database._migrate() on startup.

-- Add the column (safe to run multiple times via IF NOT EXISTS workaround)
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS is_reportable BOOLEAN DEFAULT true;

-- Index for efficient filtering in report generation
CREATE INDEX IF NOT EXISTS episodes_reportable_idx
    ON episodes (is_reportable, started_at DESC);

-- Mark known garbage records as non-reportable (do NOT delete)
UPDATE episodes
SET is_reportable = false
WHERE
    TRIM(case_name) = ''
    OR key_observations = '[]'
    OR key_observations IS NULL
    OR duration_minutes IS NULL
    OR LOWER(TRIM(case_name)) IN (
        'optional',
        'file edit',
        'sql editor',
        'new tab',
        'file path',
        'matter of',
        'case reset',
        'case requests',
        'summarizing timeline',
        'new yo',
        'active session',
        '• instagram d',
        'quenlin blackwell •'
    );
