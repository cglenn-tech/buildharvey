import { getAdminClient } from '@/lib/supabase-admin'
import { getDeviceFromToken } from '@/lib/device-auth'

export async function POST(request: Request) {
  const device = await getDeviceFromToken(request.headers.get('authorization'))
  if (!device) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const admin = getAdminClient()
  await admin
    .from('devices')
    .update({ revoked_at: new Date().toISOString() })
    .eq('id', device.id)

  return Response.json({ ok: true })
}
