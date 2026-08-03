/**
 * POST /api/screenshots/session-confirm
 * Body: { episode_id: string, path: string }
 *
 * Session auth (cookie). Inserts an episode_screenshots row after the client
 * has successfully uploaded the file to Supabase Storage.
 * Idempotent: returns { ok: true, duplicate: true } if the row already exists.
 */
import { NextRequest } from 'next/server'
import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'

export async function POST(request: NextRequest) {
  const supabase = await getServerClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 })
  }

  let body: { episode_id?: string; path?: string }
  try {
    body = (await request.json()) as { episode_id?: string; path?: string }
  } catch {
    return Response.json({ error: 'Invalid JSON' }, { status: 400 })
  }

  const { episode_id: episodeId, path } = body

  if (!episodeId || !path) {
    return Response.json({ error: 'episode_id and path are required' }, { status: 400 })
  }

  const admin = getAdminClient()

  // Verify the episode belongs to this user
  const { data: ep } = await admin
    .from('episodes')
    .select('id')
    .eq('id', episodeId)
    .eq('user_id', user.id)
    .single()

  if (!ep) {
    return Response.json({ error: 'Episode not found' }, { status: 404 })
  }

  // Idempotency check: has this storage_path already been recorded for this user?
  const { data: existing } = await admin
    .from('episode_screenshots')
    .select('id')
    .eq('user_id', user.id)
    .eq('storage_path', path)
    .maybeSingle()

  if (existing) {
    return Response.json({ ok: true, duplicate: true }, { status: 200 })
  }

  const { error } = await admin.from('episode_screenshots').insert({
    episode_id: episodeId,
    user_id: user.id,
    storage_path: path,
  })

  if (error) {
    return Response.json({ error: error.message }, { status: 500 })
  }

  return Response.json({ ok: true })
}
