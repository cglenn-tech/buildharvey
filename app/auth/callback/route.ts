import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { createServerClient } from '@supabase/ssr'
import { getAdminClient } from '@/lib/supabase-admin'

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url)
  const token_hash = searchParams.get('token_hash')
  const type = searchParams.get('type')

  const t0 = Date.now()
  console.log('[verify] callback received', { type, has_token_hash: !!token_hash, t: t0 })

  if (type !== 'email' || !token_hash) {
    return NextResponse.redirect(new URL('/auth/callback/error?reason=invalid', request.url))
  }

  // Build the success redirect first so we can attach session cookies to it.
  // Using NextResponse.redirect (not next/navigation redirect) is critical:
  // next/navigation's redirect() throws before cookies written via cookieStore
  // are committed, so on a fresh browser (mobile, different device) the session
  // is lost even though OTP verification succeeds in Supabase's DB.
  const response = NextResponse.redirect(new URL('/', request.url))

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll: (cookiesToSet) => {
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options)
          )
        },
      },
    }
  )

  const { data, error } = await supabase.auth.verifyOtp({
    token_hash,
    type: 'email',
  })

  if (error || !data.user) {
    console.error('[verify] OTP failed', { elapsed: Date.now() - t0, message: error?.message })
    return NextResponse.redirect(new URL('/auth/callback/error?reason=expired', request.url))
  }

  console.log('[verify] OTP success', { elapsed: Date.now() - t0, user_id: data.user.id })

  const admin = getAdminClient()
  await admin.from('profiles').upsert({
    id: data.user.id,
    email: data.user.email!,
  })

  return response
}
