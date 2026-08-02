-- Supabase Realtime channel authorization for BuildHarvey device channels.
--
-- PREREQUISITE: Enable "Channel Policies" in the Supabase dashboard before
-- applying this migration (Dashboard → Realtime → Channel Policies → Enable).
-- Without that toggle, realtime.messages may not exist and RLS is not enforced.
--
-- Policy: an authenticated user may only send/receive on the Realtime channel
-- for a device they own (devices.user_id = auth.uid() and not revoked).

ALTER TABLE realtime.messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY "device_channel_access"
ON realtime.messages
FOR ALL
TO authenticated
USING (
  realtime.topic() LIKE 'buildharvey:device:%'
  AND EXISTS (
    SELECT 1
    FROM public.devices
    WHERE id::text = split_part(realtime.topic(), ':', 3)
      AND user_id = (SELECT auth.uid())
      AND revoked_at IS NULL
  )
)
WITH CHECK (
  realtime.topic() LIKE 'buildharvey:device:%'
  AND EXISTS (
    SELECT 1
    FROM public.devices
    WHERE id::text = split_part(realtime.topic(), ':', 3)
      AND user_id = (SELECT auth.uid())
      AND revoked_at IS NULL
  )
);
