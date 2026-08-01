import type { NextRequest } from 'next/server'
import { getServerClient } from '@/lib/supabase-server'
import { rateLimit } from '@/lib/rate-limit'

export async function POST(request: NextRequest) {
  let body: { email?: string }
  try {
    body = await request.json()
  } catch {
    return Response.json({ error: 'Invalid JSON' }, { status: 400 })
  }

  const { email } = body
  if (!email) {
    return Response.json({ error: 'Missing email' }, { status: 400 })
  }

  const t0 = Date.now()
  console.log('[resend] requested', { email, t: t0 })

  const blocked = await rateLimit(`resend:${email.toLowerCase()}`, 3, 3600)
  if (blocked) {
    console.log('[resend] rate limited', { email })
    return Response.json({ error: 'Too many verification emails requested. Please wait before trying again.' }, { status: 429 })
  }

  const supabase = await getServerClient()
  const { error } = await supabase.auth.resend({ type: 'signup', email })
  const elapsed = Date.now() - t0

  if (error) {
    console.error('[resend] supabase error', { elapsed, message: error.message, status: error.status })
    const msg = error.status === 429 || error.message.toLowerCase().includes('rate')
      ? 'Too many verification emails requested. Please wait before trying again.'
      : "We couldn't send the verification email. Please try again shortly."
    return Response.json({ error: msg }, { status: error.status ?? 500 })
  }

  console.log('[resend] succeeded', { elapsed })
  return Response.json({ ok: true })
}
