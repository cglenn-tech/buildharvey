import { redirect } from 'next/navigation'
import type { NextRequest } from 'next/server'
import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url)
  const token_hash = searchParams.get('token_hash')
  const type = searchParams.get('type')

  if (type !== 'email' || !token_hash) {
    redirect('/auth/callback/error?reason=invalid')
  }

  const supabase = await getServerClient()
  const { data, error } = await supabase.auth.verifyOtp({
    token_hash,
    type: 'email',
  })

  if (error || !data.user) {
    redirect('/auth/callback/error?reason=expired')
  }

  const admin = getAdminClient()
  await admin.from('profiles').upsert({
    id: data.user.id,
    email: data.user.email!,
  })

  redirect('/')
}
