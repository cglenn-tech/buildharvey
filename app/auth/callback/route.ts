import { redirect } from 'next/navigation'
import type { NextRequest } from 'next/server'
import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url)
  const token_hash = searchParams.get('token_hash')
  const type = searchParams.get('type')

  const t0 = Date.now()
  console.log('[verify] callback received', { type, has_token_hash: !!token_hash, t: t0 })

  if (type !== 'email' || !token_hash) {
    redirect('/auth/callback/error?reason=invalid')
  }

  const supabase = await getServerClient()
  const { data, error } = await supabase.auth.verifyOtp({
    token_hash,
    type: 'email',
  })

  if (error || !data.user) {
    console.error('[verify] OTP failed', { elapsed: Date.now() - t0, message: error?.message })
    redirect('/auth/callback/error?reason=expired')
  }

  console.log('[verify] OTP success', { elapsed: Date.now() - t0, user_id: data.user.id })

  const admin = getAdminClient()
  await admin.from('profiles').upsert({
    id: data.user.id,
    email: data.user.email!,
  })

  redirect('/')
}
