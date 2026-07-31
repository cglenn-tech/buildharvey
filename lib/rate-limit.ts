import { getAdminClient } from './supabase-admin'

export async function rateLimit(
  key: string,
  limit: number,
  windowSeconds: number
): Promise<boolean> {
  const admin = getAdminClient()
  const windowEpoch = Math.floor(Date.now() / 1000 / windowSeconds)
  const rkey = `${key}:${windowEpoch}`

  const { data } = await admin.rpc('rate_limit_increment', { p_key: rkey })
  return (data ?? 0) > limit
}
