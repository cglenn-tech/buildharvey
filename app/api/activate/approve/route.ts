import type { NextRequest } from 'next/server'
import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'
import { rateLimit } from '@/lib/rate-limit'

export async function POST(request: NextRequest) {
  const supabase = await getServerClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const blocked = await rateLimit(`activate-approve:${user.id}`, 20, 3600)
  if (blocked) {
    return Response.json({ error: 'Too many requests' }, { status: 429 })
  }

  let body: { activation_id?: string }
  try {
    body = await request.json()
  } catch {
    return Response.json({ error: 'Invalid JSON' }, { status: 400 })
  }

  const { activation_id } = body
  if (!activation_id) {
    return Response.json({ error: 'Missing activation_id' }, { status: 400 })
  }

  const admin = getAdminClient()

  // Fetch and lock the activation row
  const { data: activation, error: fetchError } = await admin
    .from('device_activations')
    .select('*')
    .eq('id', activation_id)
    .gt('expires_at', new Date().toISOString())
    .is('approved_at', null)
    .single()

  if (fetchError || !activation) {
    return Response.json({ error: 'Activation not found or already used' }, { status: 404 })
  }

  const installationId = activation.installation_id ?? null

  let device: { id: string }
  if (installationId) {
    // PostgREST upsert doesn't work with partial unique indexes (WHERE clause),
    // so we do a manual select-then-update-or-insert instead.
    const { data: existing } = await admin
      .from('devices')
      .select('id')
      .eq('user_id', user.id)
      .eq('installation_id', installationId)
      .single()

    if (existing) {
      // Reconnect: update the existing row (clears revocation, refreshes token)
      const { data, error } = await admin
        .from('devices')
        .update({
          name: activation.device_name ?? 'My Device',
          platform: activation.platform,
          token_hash: activation.token_hash,
          revoked_at: null,
          activated_at: new Date().toISOString(),
        })
        .eq('id', existing.id)
        .select('id')
        .single()
      if (error || !data) return Response.json({ error: 'Failed to register device' }, { status: 500 })
      device = data
    } else {
      // First activation for this installation
      const { data, error } = await admin
        .from('devices')
        .insert({
          user_id: user.id,
          installation_id: installationId,
          name: activation.device_name ?? 'My Device',
          platform: activation.platform,
          token_hash: activation.token_hash,
          activated_at: new Date().toISOString(),
        })
        .select('id')
        .single()
      if (error || !data) return Response.json({ error: 'Failed to register device' }, { status: 500 })
      device = data
    }
  } else {
    // Legacy: no installation_id → plain INSERT (old clients)
    const { data, error } = await admin.from('devices').insert({
      user_id: user.id,
      name: activation.device_name ?? 'My Device',
      platform: activation.platform,
      token_hash: activation.token_hash,
    }).select('id').single()
    if (error || !data) return Response.json({ error: 'Failed to register device' }, { status: 500 })
    device = data
  }

  // Mark activation as approved
  await admin
    .from('device_activations')
    .update({
      approved_at: new Date().toISOString(),
      approved_by: user.id,
      device_id: device.id,
    })
    .eq('id', activation_id)

  return Response.json({ ok: true })
}
