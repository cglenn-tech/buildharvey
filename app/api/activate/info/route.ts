import type { NextRequest } from 'next/server'
import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'

export async function GET(request: NextRequest) {
  const supabase = await getServerClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const { searchParams } = new URL(request.url)
  const id = searchParams.get('id')

  if (!id) {
    return Response.json({ error: 'Missing id' }, { status: 400 })
  }

  const admin = getAdminClient()
  const { data } = await admin
    .from('device_activations')
    .select('device_name, platform, expires_at')
    .eq('id', id)
    .gt('expires_at', new Date().toISOString())
    .is('approved_at', null)
    .single()

  if (!data) {
    return Response.json({ error: 'Not found or expired' }, { status: 404 })
  }

  return Response.json({ device_name: data.device_name, platform: data.platform })
}
