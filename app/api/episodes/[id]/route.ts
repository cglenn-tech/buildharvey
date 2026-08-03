import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'
import type { Episode } from '@/lib/types'

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params

  const supabase = await getServerClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 })
  }

  // RLS ensures user can only delete their own episodes
  const { error } = await supabase.from('episodes').delete().eq('id', id)

  if (error) {
    return Response.json({ error: error.message }, { status: 500 })
  }

  return new Response(null, { status: 204 })
}

const PATCHABLE = [
  'case_name', 'work_type', 'issue_worked_on', 'key_observations',
  'started_at', 'ended_at', 'duration_minutes', 'is_reportable',
] as const

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params

  const supabase = await getServerClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const admin = getAdminClient()

  // Verify ownership
  const { data: existing, error: lookupErr } = await admin
    .from('episodes')
    .select('id, user_id')
    .eq('id', id)
    .single()

  if (lookupErr || !existing) {
    return Response.json({ error: 'Not found' }, { status: 404 })
  }
  if (existing.user_id !== user.id) {
    return Response.json({ error: 'Forbidden' }, { status: 403 })
  }

  const body = await request.json()
  const patch: Record<string, unknown> = { edited_at: new Date().toISOString() }
  for (const key of PATCHABLE) {
    if (key in body) patch[key] = body[key]
  }

  const { data, error } = await admin
    .from('episodes')
    .update(patch)
    .eq('id', id)
    .select('*')
    .single()

  if (error) {
    return Response.json({ error: error.message }, { status: 500 })
  }

  return Response.json({ episode: data as Episode })
}
