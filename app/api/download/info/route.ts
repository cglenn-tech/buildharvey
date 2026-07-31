import { getAdminClient } from '@/lib/supabase-admin'

export async function GET() {
  const admin = getAdminClient()
  const { data } = await admin
    .from('app_releases')
    .select('version, sha256')
    .eq('active', true)
    .eq('platform', 'macos')
    .limit(1)
    .single()

  if (!data) {
    return Response.json({ error: 'unavailable' }, { status: 404 })
  }

  return Response.json({ version: data.version, sha256: data.sha256 })
}
