import type { NextRequest } from 'next/server'
import { getBrowserClient } from '@/lib/supabase-browser'
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

  const blocked = await rateLimit(`resend:${email.toLowerCase()}`, 3, 3600)
  if (blocked) {
    return Response.json({ error: 'Too many requests. Wait before resending.' }, { status: 429 })
  }

  const supabase = getBrowserClient()
  const { error } = await supabase.auth.resend({ type: 'signup', email })

  if (error) {
    return Response.json({ error: error.message }, { status: 500 })
  }

  return Response.json({ ok: true })
}
