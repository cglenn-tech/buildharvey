-- ============================================================
-- BuildHarvey — Activate macOS release 1.0.2
-- Migration 016
--
-- NOTE: verify sha256 before applying:
--   shasum -a 256 BuildHarvey-1.0.2.dmg
-- The file must already be uploaded to Supabase Storage at:
--   releases/macos/BuildHarvey-1.0.2.dmg
-- ============================================================

BEGIN;

  -- 1. Deactivate all macOS releases (clears the partial unique index so we can set a new active row)
  UPDATE app_releases
  SET active = FALSE
  WHERE platform = 'macos';

  -- 2. Upsert 1.0.2 row and activate it.
  --    There is no (platform, version) unique constraint, so we use a DO block
  --    to branch on whether the row already exists.
  DO $$
  BEGIN
    IF EXISTS (
      SELECT 1 FROM app_releases WHERE platform = 'macos' AND version = '1.0.2'
    ) THEN
      UPDATE app_releases
      SET storage_path = 'macos/BuildHarvey-1.0.2.dmg',
          sha256       = 'aa220f1f997d1c94b43e6893f5aedd3fe387fa9974f85a8846652e088378ee0',
          active       = TRUE
      WHERE platform = 'macos' AND version = '1.0.2';
    ELSE
      INSERT INTO app_releases (platform, version, storage_path, sha256, active)
      VALUES (
        'macos',
        '1.0.2',
        'macos/BuildHarvey-1.0.2.dmg',
        'aa220f1f997d1c94b43e6893f5aedd3fe387fa9974f85a8846652e088378ee0',
        TRUE
      );
    END IF;
  END $$;

COMMIT;
