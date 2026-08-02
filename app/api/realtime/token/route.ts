import { createHash, createHmac } from 'crypto'
import { getAdminClient } from '@/lib/supabase-admin'

function signSupabaseJwt(userId: string, secret: string, expiresInSeconds: number): string {
  const now = Math.floor(Date.now() / 1000)
  const header = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url')
  const payload = Buffer.from(JSON.stringify({
    role: 'authenticated',
    sub: userId,
    aud: 'authenticated',
    iat: now,
    exp: now + expiresInSeconds,
  })).toString('base64url')
  const sig = createHmac('sha256', secret).update(`${header}.${payload}`).digest('base64url')
  return `${header}.${payload}.${sig}`
}

async function getDeviceFromToken(authHeader: string | null) {
  if (!authHeader?.startsWith('Bearer ')) return null
  const rawToken = authHeader.slice(7)
  const tokenHash = createHash('sha256').update(rawToken).digest('hex')
  const admin = getAdminClient()
  const { data: device } = await admin
    .from('devices')
    .select('id, user_id')
    .eq('token_hash', tokenHash)
    .is('revoked_at', null)
    .single()
  return device ?? null
}

export async function GET(request: Request) {
  const device = await getDeviceFromToken(request.headers.get('authorization'))
  if (!device) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const jwtSecret = process.env.SUPABASE_JWT_SECRET
  if (!jwtSecret) {
    return Response.json({ error: 'Server misconfiguration' }, { status: 500 })
  }

  const expiresIn = 86400 // 24 hours
  const accessToken = signSupabaseJwt(device.user_id, jwtSecret, expiresIn)

  return Response.json({
    supabase_url: process.env.NEXT_PUBLIC_SUPABASE_URL,
    anon_key: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    access_token: accessToken,
    device_id: device.id,
    expires_in: expiresIn,
  })
}
