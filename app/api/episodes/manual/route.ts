import { NextRequest } from 'next/server'
import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'
import type { Episode, KeyObservation } from '@/lib/types'

type ManualEpisodeBody = {
  case_name?: string
  work_type?: 'project' | 'administrative'
  issue_worked_on?: string
  task_description?: string
  notes?: string
  started_at?: string
  ended_at?: string
  is_reportable?: boolean
}

export async function POST(request: NextRequest) {
  const supabase = await getServerClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 })
  }

  let body: ManualEpisodeBody
  try {
    body = (await request.json()) as ManualEpisodeBody
  } catch {
    return Response.json({ error: 'Invalid JSON' }, { status: 400 })
  }

  if (!body.case_name) {
    return Response.json({ error: 'case_name is required' }, { status: 400 })
  }
  if (!body.task_description) {
    return Response.json({ error: 'task_description is required' }, { status: 400 })
  }
  if (!body.started_at) {
    return Response.json({ error: 'started_at is required' }, { status: 400 })
  }
  if (!body.ended_at) {
    return Response.json({ error: 'ended_at is required' }, { status: 400 })
  }

  // Validate ISO strings and ordering
  const startMs = Date.parse(body.started_at)
  const endMs = Date.parse(body.ended_at)

  if (isNaN(startMs)) {
    return Response.json({ error: 'started_at is not a valid ISO date' }, { status: 400 })
  }
  if (isNaN(endMs)) {
    return Response.json({ error: 'ended_at is not a valid ISO date' }, { status: 400 })
  }
  if (endMs <= startMs) {
    return Response.json({ error: 'ended_at must be after started_at' }, { status: 400 })
  }

  const duration_minutes = (endMs - startMs) / 60_000

  const obs: KeyObservation[] = []
  if (body.task_description) {
    obs.push({ timestamp: body.started_at, text: body.task_description })
  }
  if (body.notes) {
    obs.push({ timestamp: body.started_at, text: body.notes })
  }

  const id = crypto.randomUUID()
  const now = new Date().toISOString()

  const episode: Episode = {
    id,
    case_name: body.case_name,
    work_type: body.work_type ?? 'project',
    issue_worked_on: body.issue_worked_on ?? null,
    started_at: body.started_at,
    ended_at: body.ended_at,
    duration_minutes,
    key_observations: obs,
    created_at: now,
    is_reportable: body.is_reportable ?? true,
    edited_at: null,
  }

  const admin = getAdminClient()

  const { error } = await admin.from('episodes').upsert(
    {
      id: episode.id,
      case_name: episode.case_name,
      work_type: episode.work_type,
      issue_worked_on: episode.issue_worked_on,
      started_at: episode.started_at,
      ended_at: episode.ended_at,
      duration_minutes: episode.duration_minutes,
      key_observations: episode.key_observations,
      created_at: episode.created_at,
      is_reportable: episode.is_reportable,
      edited_at: episode.edited_at,
      user_id: user.id,
      device_id: null,
    },
    { onConflict: 'id', ignoreDuplicates: false }
  )

  if (error) {
    return Response.json({ error: error.message }, { status: 500 })
  }

  return Response.json({ ok: true, episode })
}
