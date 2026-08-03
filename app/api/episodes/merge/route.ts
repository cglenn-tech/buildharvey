import { NextRequest } from 'next/server'
import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'
import type { Episode, KeyObservation } from '@/lib/types'

type EpisodeRow = Episode & { user_id: string }

export async function POST(request: NextRequest) {
  const supabase = await getServerClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 })
  }

  let body: { keep_id?: string; drop_id?: string }
  try {
    body = (await request.json()) as { keep_id?: string; drop_id?: string }
  } catch {
    return Response.json({ error: 'Invalid JSON' }, { status: 400 })
  }

  const { keep_id, drop_id } = body
  if (!keep_id || !drop_id) {
    return Response.json({ error: 'keep_id and drop_id are required' }, { status: 400 })
  }

  const admin = getAdminClient()

  // Load both episodes and verify ownership
  const [{ data: keepData }, { data: dropData }] = await Promise.all([
    admin
      .from('episodes')
      .select('*')
      .eq('id', keep_id)
      .eq('user_id', user.id)
      .single<EpisodeRow>(),
    admin
      .from('episodes')
      .select('*')
      .eq('id', drop_id)
      .eq('user_id', user.id)
      .single<EpisodeRow>(),
  ])

  if (!keepData || !dropData) {
    return Response.json(
      { error: 'One or both episodes not found or not owned by user' },
      { status: 404 }
    )
  }

  const keep = keepData
  const drop = dropData

  // Merge timestamps
  const merged_started_at = [keep.started_at, drop.started_at].sort()[0]
  const merged_ended_at = [keep.ended_at, drop.ended_at].sort().reverse()[0]

  // Merge duration
  const merged_duration_minutes = keep.duration_minutes + drop.duration_minutes

  // Merge and deduplicate observations (remove obs with same text as immediately preceding)
  const combined: KeyObservation[] = [
    ...(keep.key_observations ?? []),
    ...(drop.key_observations ?? []),
  ].sort((a, b) => a.timestamp.localeCompare(b.timestamp))

  const merged_key_observations: KeyObservation[] = combined.filter((obs, idx) => {
    if (idx === 0) return true
    return obs.text !== combined[idx - 1].text
  })

  const editedAt = new Date().toISOString()

  const returnEpisode: Episode = {
    id: keep.id,
    case_name: keep.case_name,
    work_type: keep.work_type,
    issue_worked_on: keep.issue_worked_on ?? drop.issue_worked_on ?? null,
    started_at: merged_started_at,
    ended_at: merged_ended_at,
    duration_minutes: merged_duration_minutes,
    key_observations: merged_key_observations,
    created_at: keep.created_at,
    is_reportable: keep.is_reportable,
    edited_at: editedAt,
  }

  // Move screenshots from drop to keep
  const { error: moveError } = await admin
    .from('episode_screenshots')
    .update({ episode_id: keep_id })
    .eq('episode_id', drop_id)

  if (moveError) {
    return Response.json({ error: moveError.message }, { status: 500 })
  }

  // Upsert the merged episode
  const { error: upsertError } = await admin.from('episodes').upsert(
    {
      id: returnEpisode.id,
      case_name: returnEpisode.case_name,
      work_type: returnEpisode.work_type,
      issue_worked_on: returnEpisode.issue_worked_on,
      started_at: returnEpisode.started_at,
      ended_at: returnEpisode.ended_at,
      duration_minutes: returnEpisode.duration_minutes,
      key_observations: returnEpisode.key_observations,
      created_at: returnEpisode.created_at,
      is_reportable: returnEpisode.is_reportable,
      edited_at: returnEpisode.edited_at,
      user_id: user.id,
    },
    { onConflict: 'id', ignoreDuplicates: false }
  )

  if (upsertError) {
    return Response.json({ error: upsertError.message }, { status: 500 })
  }

  // Only delete the drop episode after a successful upsert
  const { error: deleteError } = await admin.from('episodes').delete().eq('id', drop_id)

  if (deleteError) {
    return Response.json({ error: deleteError.message }, { status: 500 })
  }

  return Response.json({ ok: true, episode: returnEpisode })
}
