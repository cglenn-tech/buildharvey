import { NextRequest } from 'next/server'
import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'
import { rateLimit } from '@/lib/rate-limit'
import type { Episode } from '@/lib/types'

export async function POST(request: NextRequest) {
  const supabase = await getServerClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const over = await rateLimit(`episode_save:${user.id}`, 60, 3600)
  if (over) {
    return Response.json({ error: 'rate_limited' }, { status: 429 })
  }

  let body: Partial<Episode>
  try {
    body = (await request.json()) as Partial<Episode>
  } catch {
    return Response.json({ error: 'Invalid JSON' }, { status: 400 })
  }

  if (!body.id || !body.case_name) {
    return Response.json({ error: 'id and case_name are required' }, { status: 400 })
  }

  const admin = getAdminClient()

  const { error } = await admin.from('episodes').upsert(
    {
      id: body.id,
      case_name: body.case_name,
      work_type: body.work_type ?? 'project',
      issue_worked_on: body.issue_worked_on ?? null,
      started_at: body.started_at,
      ended_at: body.ended_at,
      duration_minutes: body.duration_minutes,
      key_observations: body.key_observations ?? [],
      created_at: body.created_at,
      is_reportable: body.is_reportable ?? true,
      user_id: user.id,
      device_id: null,
    },
    { onConflict: 'id', ignoreDuplicates: false }
  )

  if (error) {
    return Response.json({ error: error.message }, { status: 500 })
  }

  return Response.json({ ok: true })
}
