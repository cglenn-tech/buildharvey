ALTER TABLE devices ADD COLUMN IF NOT EXISTS installation_id UUID;
ALTER TABLE device_activations ADD COLUMN IF NOT EXISTS installation_id UUID;

-- One active device row per (user, installation). Partial index: NULL rows exempt.
CREATE UNIQUE INDEX IF NOT EXISTS devices_user_installation_unique
  ON devices (user_id, installation_id)
  WHERE installation_id IS NOT NULL;
