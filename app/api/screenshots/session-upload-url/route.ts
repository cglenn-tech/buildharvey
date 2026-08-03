/**
 * GET /api/screenshots/session-upload-url?episode_id=...&filename=...
 *
 * Session auth (cookie). Returns a signed Supabase Storage upload URL
 * scoped to the authenticated user and the given episode.
 */
import { NextRequest } from 'next/server'
import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'

export async function GET(request: NextRequest) {
  const supabase = await getServerClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const episodeId = request.nextUrl.searchParams.get('episode_id')
  const filename = request.nextUrl.searchParams.get('filename')

  if (!episodeId || !filename) {
    return Response.json(
      { error: 'episode_id and filename are required' },
      { status: 400 }
    )
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

  const storagePath = `${user.id}/${episodeId}/${filename}`

  const { data, error } = await admin.storage
    .from('episode-screenshots')
    .createSignedUploadUrl(storagePath)

  if (error || !data) {
    return Response.json(
      { error: error?.message ?? 'Could not create upload URL' },
      { status: 500 }
    )
  }

  return Response.json({ upload_url: data.signedUrl, path: storagePath })
}
