import { redirect } from 'next/navigation'
import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'
import type { Episode } from '@/lib/types'
import HomepageClient from '@/components/HomepageClient'
import type { WeekSummaryData } from '@/components/ThisWeekSummary'
import AuthForm from '@/components/AuthForm'
import AppNav from '@/components/AppNav'

export const dynamic = 'force-dynamic'

function isoMonday(d: Date): string {
  const day = d.getDay()
  const diff = day === 0 ? -6 : 1 - day
  const mon = new Date(d)
  mon.setDate(d.getDate() + diff)
  return mon.toISOString().slice(0, 10)
}

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

  // Authenticated with device → fetch episodes
  const { data } = await admin
    .from('episodes')
    .select('*')
    .eq('user_id', user.id)
    .order('started_at', { ascending: false })

  const episodes = (data as Episode[]) ?? []

  // Calculate this-week running totals (deterministic — no LLM)
  const today = new Date().toISOString().slice(0, 10)
  const monday = isoMonday(new Date())

  const weekEpisodes = episodes.filter((ep) => {
    const epDate = ep.started_at.slice(0, 10)
    return epDate >= monday && epDate <= today
  })

  const matterMap: Record<string, number> = {}
  for (const ep of weekEpisodes) {
    const key = ep.case_name?.trim() || 'Unknown'
    matterMap[key] = (matterMap[key] ?? 0) + ep.duration_minutes
  }

  const matterTotals = Object.entries(matterMap)
    .sort((a, b) => b[1] - a[1])
    .map(([title, minutes]) => ({ title, isAdmin: false, minutes }))

  const totalMinutes = matterTotals.reduce((s, m) => s + m.minutes, 0)

  const weekSummary: WeekSummaryData = {
    matters: matterTotals,
    caseMinutes: totalMinutes,
    adminMinutes: 0,
    totalMinutes,
  }

  return (
    <>
      <AppNav />
      <main className="max-w-2xl mx-auto px-6 py-10">
        <div className="mb-8">
          <p className="text-sm text-neutral-500">
            Work captured by case. Generate a report when you&apos;re ready.
          </p>
        </div>
        <HomepageClient episodes={episodes} weekSummary={weekSummary} />
      </main>
    </>
  )
}
