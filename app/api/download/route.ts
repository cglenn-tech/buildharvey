import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'

export async function POST() {
  const supabase = await getServerClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 })
  }

  if (!user.email_confirmed_at) {
    return Response.json({ error: 'Email not verified' }, { status: 403 })
  }

  const admin = getAdminClient()

  const { data: release } = await admin
    .from('app_releases')
    .select('*')
    .eq('active', true)
    .eq('platform', 'macos')
    .limit(1)
    .single()

  if (!release) {
    return Response.json({ error: 'unavailable' }, { status: 404 })
  }

  const { data: signedData, error: signError } = await admin.storage
    .from('releases')
    .createSignedUrl(release.storage_path, 300)

  if (signError || !signedData) {
    return Response.json({ error: 'Failed to generate download link' }, { status: 500 })
  }

  await admin.from('download_events').insert({
    user_id: user.id,
    release_id: release.id,
  })

  return Response.json({
    url: signedData.signedUrl,
    version: release.version,
    sha256: release.sha256,
  })
}
