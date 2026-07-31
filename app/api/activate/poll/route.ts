import type { NextRequest } from 'next/server'
import { createHash, timingSafeEqual } from 'crypto'
import { getAdminClient } from '@/lib/supabase-admin'
import { rateLimit } from '@/lib/rate-limit'

export async function POST(request: NextRequest) {
  const ip = request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() ?? 'unknown'
  const blocked = await rateLimit(`activate-poll:${ip}`, 60, 600)
  if (blocked) {
    return Response.json({ error: 'Too many requests' }, { status: 429 })
  }

  let body: { activation_id?: string; polling_secret?: string }
  try {
    body = await request.json()
  } catch {
    return Response.json({ error: 'Invalid JSON' }, { status: 400 })
  }

  const { activation_id, polling_secret } = body
  if (!activation_id || !polling_secret) {
    return Response.json({ error: 'Missing fields' }, { status: 400 })
  }

  const admin = getAdminClient()
  const { data: activation } = await admin
    .from('device_activations')
    .select('polling_verifier, expires_at, approved_at')
    .eq('id', activation_id)
    .single()

  if (!activation) {
    return Response.json({ status: 'expired' })
  }

  if (new Date(activation.expires_at) < new Date()) {
    return Response.json({ status: 'expired' })
  }

  // Constant-time compare: sha256(polling_secret) vs stored polling_verifier
  const computed = createHash('sha256').update(polling_secret).digest('hex')
  let match = false
  try {
    match = timingSafeEqual(
      Buffer.from(computed, 'hex'),
      Buffer.from(activation.polling_verifier, 'hex')
    )
  } catch {
    // Length mismatch — not equal
  }

  if (!match) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 })
  }

  if (!activation.approved_at) {
    return Response.json({ status: 'pending' })
  }

  return Response.json({ status: 'approved' })
}
