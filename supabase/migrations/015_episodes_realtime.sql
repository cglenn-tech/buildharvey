-- Enable Supabase Realtime on the episodes table.
-- This allows web clients to subscribe to postgres_changes on episodes,
-- receiving live updates when new episodes are synced from the desktop agent.
--
-- Run this migration after enabling Realtime in the Supabase dashboard for
-- the episodes table, or apply directly via supabase db push.
ALTER PUBLICATION supabase_realtime ADD TABLE public.episodes;
