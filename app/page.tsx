import { redirect } from 'next/navigation'
import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'
import type { Episode } from '@/lib/types'
import HomepageClient from '@/components/HomepageClient'
import AuthForm from '@/components/AuthForm'
import AppNav from '@/components/AppNav'

export const dynamic = 'force-dynamic'

export default async function Home() {
  const supabase = await getServerClient()
  const { data: { user } } = await supabase.auth.getUser()

  // No session → show auth form
  if (!user) {
    return <AuthForm />
  }

  // Session but email not confirmed → redirect to verify
  if (!user.email_confirmed_at) {
    redirect(`/verify?email=${encodeURIComponent(user.email ?? '')}`)
  }

  const admin = getAdminClient()
  const { data } = await admin
    .from('episodes')
    .select('*')
    .eq('user_id', user.id)
    .order('started_at', { ascending: false })

  const episodes = (data as Episode[]) ?? []

  return (
    <>
      <AppNav />
      <main className="max-w-2xl mx-auto px-6 py-10">
        <p className="text-sm text-neutral-500 mb-8">
          Work captured by case. Generate a report when you&apos;re ready.
        </p>
        <HomepageClient episodes={episodes} />
      </main>
    </>
  )
}
