import { redirect } from 'next/navigation'
import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'
import type { Episode } from '@/lib/types'
import EpisodeList from '@/components/EpisodeList'
import ReportGenerator from '@/components/ReportGenerator'
import AuthForm from '@/components/AuthForm'

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

  // Verified but no active device → redirect to download
  const admin = getAdminClient()
  const { data: devices, error: devicesError } = await admin
    .from('devices')
    .select('id')
    .eq('user_id', user.id)
    .is('revoked_at', null)
    .limit(1)

  if (devicesError) {
    console.error('[home] device lookup failed', { message: devicesError.message })
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-sm text-neutral-500">
          Something went wrong.{' '}
          <a href="/" className="underline text-neutral-900">Retry</a>
        </p>
      </div>
    )
  }

  if (!devices || devices.length === 0) {
    redirect('/download')
  }

  // Authenticated with device → show homepage
  const { data } = await admin
    .from('episodes')
    .select('*')
    .eq('user_id', user.id)
    .order('started_at', { ascending: false })

  const episodes = (data as Episode[]) ?? []

  return (
    <main className="max-w-2xl mx-auto px-6 py-10">
      <div className="mb-8">
        <h1 className="text-lg font-semibold text-neutral-900">BuildHarvey</h1>
        <p className="text-sm text-neutral-500 mt-1">
          Work captured by case. Generate a report when you&apos;re ready.
        </p>
      </div>

      <div className="mb-10">
        <ReportGenerator />
      </div>

      <EpisodeList initialEpisodes={episodes} />
    </main>
  )
}
