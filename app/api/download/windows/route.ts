import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'
import { rateLimit } from '@/lib/rate-limit'

export async function POST() {
  // 1. Auth check
  const supabase = await getServerClient()
  const {
    data: { user },
    error: authError,
  } = await supabase.auth.getUser()

  if (authError || !user) {
    return Response.json({ error: 'authentication_required' }, { status: 401 })
  }

  // 2. Email confirmation check
  if (!user.email_confirmed_at) {
    return Response.json({ error: 'email_verification_required' }, { status: 403 })
  }

  // 3. Rate limit: 10 requests per hour per user
  const limited = await rateLimit(`download:windows:${user.id}`, 10, 3600)
  if (limited) {
    return Response.json({ error: 'too_many_requests' }, { status: 429 })
  }

  const admin = getAdminClient()

  // 4. Query active Windows release (LIMIT 2 to detect corrupt state)
  const { data: releases, error: releasesError } = await admin
    .from('app_releases')
    .select('id, version, storage_path, sha256')
    .eq('active', true)
    .eq('platform', 'windows')
    .limit(2)

  if (releasesError) {
    console.error('[download/windows] release query failed', { message: releasesError.message })
    return Response.json({ error: 'download_failed' }, { status: 500 })
  }

  if (!releases || releases.length === 0) {
    return Response.json({ error: 'release_unavailable' }, { status: 404 })
  }
  if (releases.length === 2) {
    return Response.json({ error: 'invalid_release_configuration' }, { status: 409 })
  }

  const release = releases[0]

  // 5. Validate storage_path
  if (
    !release.version ||
    !release.storage_path ||
    !release.storage_path.startsWith('windows/') ||
    !release.storage_path.endsWith('.exe') ||
    release.storage_path.includes('..') ||
    release.storage_path.startsWith('/')
  ) {
    return Response.json({ error: 'invalid_release_configuration' }, { status: 409 })
  }

  // 6. Validate sha256
  const sha256 = release.sha256?.trim().toLowerCase() ?? ''
  if (!/^[a-f0-9]{64}$/.test(sha256)) {
    return Response.json({ error: 'invalid_release_configuration' }, { status: 409 })
  }

  // 7. Reject development versions in production
  if (process.env.NODE_ENV === 'production' && release.version.includes('development')) {
    return Response.json({ error: 'invalid_release_configuration' }, { status: 409 })
  }

  // 8. Verify file exists in storage
  const { data: fileExists, error: existsError } = await admin.storage
    .from('releases')
    .exists(release.storage_path)

  if (existsError) {
    console.error('[download/windows] storage exists check failed', {
      message: existsError.message,
    })
    return Response.json({ error: 'download_failed' }, { status: 500 })
  }
  if (!fileExists) {
    return Response.json({ error: 'release_unavailable' }, { status: 404 })
  }

  // 9. Create signed URL
  const safeVersion = release.version.replace(/[^a-zA-Z0-9.\-_]/g, '_')
  const downloadName = `BuildHarveySetup-${safeVersion}.exe`

  const { data: signedData, error: signError } = await admin.storage
    .from('releases')
    .createSignedUrl(release.storage_path, 300, { download: downloadName })

  if (signError || !signedData) {
    console.error('[download/windows] signed URL creation failed', {
      message: signError?.message,
    })
    return Response.json({ error: 'download_failed' }, { status: 500 })
  }

  // 10. Log download event (best-effort)
  const { error: eventError } = await admin
    .from('download_events')
    .insert({ user_id: user.id, release_id: release.id })
  if (eventError) {
    console.error('[download/windows] event log failed', { message: eventError.message })
  }

  return Response.json({
    url: signedData.signedUrl,
    version: release.version,
    sha256,
  })
}
