import { createHash } from 'crypto'
import type { NextRequest } from 'next/server'
import { getAdminClient } from '@/lib/supabase-admin'

async function getDeviceFromToken(authHeader: string | null) {
  if (!authHeader?.startsWith('Bearer ')) return null
  const rawToken = authHeader.slice(7)
  const tokenHash = createHash('sha256').update(rawToken).digest('hex')

  const admin = getAdminClient()
  const { data: device } = await admin
    .from('devices')
    .select('id, user_id')
    .eq('token_hash', tokenHash)
    .is('revoked_at', null)
    .single()

  if (!device) return null

  // Update last_seen_at (fire-and-forget)
  admin.from('devices').update({ last_seen_at: new Date().toISOString() }).eq('id', device.id)

  return device
}

export async function POST(request: NextRequest) {
  const device = await getDeviceFromToken(request.headers.get('authorization'))
  if (!device) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 })
  }

  let episode: Record<string, unknown>
  try {
    episode = await request.json()
  } catch {
    return Response.json({ error: 'Invalid JSON' }, { status: 400 })
  }

  const admin = getAdminClient()
  const { error } = await admin.from('episodes').upsert({
    ...episode,
    user_id: device.user_id,
    device_id: device.id,
  })

  if (error) {
    return Response.json({ error: error.message }, { status: 500 })
  }

  return Response.json({ ok: true })
}
