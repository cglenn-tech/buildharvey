import 'server-only'
import { getAdminClient } from './supabase-admin'

export async function rateLimit(
  key: string,
  limit: number,
  windowSeconds: number
): Promise<boolean> {
  const admin = getAdminClient()
  const windowEpoch = Math.floor(Date.now() / 1000 / windowSeconds)
  const rkey = `${key}:${windowEpoch}`

  const { data, error } = await admin.rpc('rate_limit_increment', { p_key: rkey })
  if (error) {
    console.error('[rate-limit] increment failed', { key, message: error.message })
    return false  // fail open — limiter failure must not block valid requests
  }
  return (data ?? 0) > limit
}
