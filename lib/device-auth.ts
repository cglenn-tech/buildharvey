import { createHash } from 'crypto'
import { getAdminClient } from '@/lib/supabase-admin'

export type DeviceRecord = { id: string; user_id: string; installation_id: string | null }

export async function getDeviceFromToken(authHeader: string | null): Promise<DeviceRecord | null> {
  if (!authHeader?.startsWith('Bearer ')) return null
  const rawToken = authHeader.slice(7)
  const tokenHash = createHash('sha256').update(rawToken).digest('hex')
  const admin = getAdminClient()
  const { data: device } = await admin
    .from('devices')
    .select('id, user_id, installation_id')
    .eq('token_hash', tokenHash)
    .is('revoked_at', null)
    .single()
  return device ?? null
}
