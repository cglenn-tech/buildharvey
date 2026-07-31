import { getBrowserClient } from './supabase-browser'

// Kept for compatibility with existing API routes.
// New code should use getServerClient() or getAdminClient() as appropriate.
export function getSupabaseClient() {
  return getBrowserClient()
}
