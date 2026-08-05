import type { NextRequest } from 'next/server'
import { getAdminClient } from '@/lib/supabase-admin'
import { rateLimit } from '@/lib/rate-limit'

const HEX64 = /^[0-9a-f]{64}$/i
const UUID_RE = /^[0-9a-f-]{36}$/i

export async function POST(request: NextRequest) {
  const ip = request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() ?? 'unknown'
  const blocked = await rateLimit(`activate-request:${ip}`, 10, 3600)
  if (blocked) {
    return Response.json({ error: 'Too many requests' }, { status: 429 })
  }

  let body: {
    device_name?: string
    platform?: string
    token_hash?: string
    polling_verifier?: string
    installation_id?: string
  }
  try {
    body = await request.json()
  } catch {
    return Response.json({ error: 'Invalid JSON' }, { status: 400 })
  }

  const { device_name, platform = 'macos', token_hash, polling_verifier, installation_id } = body

  if (!token_hash || !HEX64.test(token_hash)) {
    return Response.json({ error: 'Invalid token_hash' }, { status: 400 })
  }
  if (!polling_verifier || !HEX64.test(polling_verifier)) {
    return Response.json({ error: 'Invalid polling_verifier' }, { status: 400 })
  }

  // Validate installation_id if provided
  const validatedInstallationId =
    installation_id && UUID_RE.test(installation_id) ? installation_id : null

  const admin = getAdminClient()
  const expiresAt = new Date(Date.now() + 10 * 60 * 1000).toISOString()

  const { data, error } = await admin
    .from('device_activations')
    .insert({
      token_hash,
      polling_verifier,
      device_name: device_name ?? null,
      platform,
      expires_at: expiresAt,
      installation_id: validatedInstallationId,
    })
    .select('id')
    .single()

  if (error || !data) {
    return Response.json({ error: 'Failed to create activation' }, { status: 500 })
  }

  return Response.json({ activation_id: data.id })
}
