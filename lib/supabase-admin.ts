import { createClient, SupabaseClient } from '@supabase/supabase-js'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let _admin: SupabaseClient<any> | null = null

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function getAdminClient(): SupabaseClient<any> {
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY) {
    throw new Error('missing SUPABASE_SERVICE_ROLE_KEY')
  }
  _admin ??= createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY,
    { auth: { persistSession: false } }
  )
  return _admin
}
