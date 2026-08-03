import { redirect } from 'next/navigation'
import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'
import Link from 'next/link'
import type { Episode, KeyObservation } from '@/lib/types'
import PrintButton from '@/components/PrintButton'

export const dynamic = 'force-dynamic'

// Suppress unused-import warning for KeyObservation which is part of the
// public contract via Episode.key_observations.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
type _Suppress = KeyObservation

function fmtDur(minutes: number): string {
  if (!minutes || minutes < 1) return '< 1m'
  const h = Math.floor(minutes / 60)
  const m = Math.round(minutes % 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

function fmtUtcTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZone: 'UTC',
  })
}

function fmtUtcDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    timeZone: 'UTC',
  })
}

function getDateKey(iso: string): string {
  // "2026-08-03" from UTC
  return new Date(iso).toISOString().slice(0, 10)
}

export default async function ProjectPage({
  searchParams,
}: {
  searchParams: Promise<{ name?: string }>
}) {
  const params = await searchParams

  const supabase = await getServerClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) redirect('/')

  const projectName = decodeURIComponent(params?.name ?? '')
  if (!projectName) redirect('/')

  const admin = getAdminClient()
  const { data } = await admin
    .from('episodes')
    .select('*')
    .eq('user_id', user.id)
    .eq('case_name', projectName)
    .eq('is_reportable', true)
    .order('started_at', { ascending: true })

  const episodes: Episode[] = (data as Episode[]) ?? []

  if (episodes.length === 0) {
    return (
      <main className="max-w-2xl mx-auto px-6 py-10 print:px-0">
        <Link
          href="/"
          className="text-sm text-neutral-400 hover:text-neutral-700 transition-colors print:hidden"
        >
          &larr; Back
        </Link>
        <h1 className="mt-4 text-xl font-semibold text-neutral-900">{projectName}</h1>
        <p className="mt-6 text-sm text-neutral-500">No episodes found for this project.</p>
      </main>
    )
  }

  const totalMinutes = episodes.reduce((sum, ep) => sum + (ep.duration_minutes ?? 0), 0)

  // Group by day (UTC date key)
  const dayMap = new Map<string, Episode[]>()
  for (const ep of episodes) {
    const key = getDateKey(ep.started_at)
    const group = dayMap.get(key) ?? []
    group.push(ep)
    dayMap.set(key, group)
  }
  const days = Array.from(dayMap.entries()).sort(([a], [b]) => a.localeCompare(b))

  return (
    <main className="max-w-2xl mx-auto px-6 py-10 print:px-0 print:py-4">
      {/* Header row */}
      <div className="flex items-start justify-between mb-6 print:mb-4">
        <div>
          <Link
            href="/"
            className="text-sm text-neutral-400 hover:text-neutral-700 transition-colors print:hidden"
          >
            &larr; Back
          </Link>
          <h1 className="mt-2 text-xl font-semibold text-neutral-900 print:mt-0">
            {projectName}
          </h1>
          <p className="mt-1 text-sm text-neutral-500">
            Total: {fmtDur(totalMinutes)}
          </p>
        </div>
        <div className="print:hidden">
          <PrintButton />
        </div>
      </div>

      {/* Day groups */}
      <div className="space-y-8">
        {days.map(([dateKey, dayEpisodes]) => (
          <section key={dateKey}>
            <h2 className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-3 print:text-neutral-600">
              {fmtUtcDate(dateKey + 'T12:00:00Z')}
            </h2>
            <div className="space-y-4">
              {dayEpisodes.map((ep) => (
                <div
                  key={ep.id}
                  className="border border-neutral-100 rounded-lg p-4 print:border-neutral-300 print:rounded-none print:border-0 print:border-b print:pb-4"
                >
                  {/* Time range + duration */}
                  <p className="text-xs text-neutral-400 mb-1">
                    {fmtUtcTime(ep.started_at)} &ndash; {fmtUtcTime(ep.ended_at)}{' '}
                    &middot; {fmtDur(ep.duration_minutes)}
                  </p>

                  {/* Issue worked on */}
                  {ep.issue_worked_on && (
                    <p className="text-sm font-medium text-neutral-700 mb-2">
                      {ep.issue_worked_on}
                    </p>
                  )}

                  {/* Key observations */}
                  {ep.key_observations.length > 0 && (
                    <ul className="space-y-1">
                      {ep.key_observations.map((obs, i) => (
                        <li key={i} className="flex gap-3 text-sm text-neutral-600">
                          <span className="font-mono text-xs text-neutral-300 shrink-0 mt-0.5 print:text-neutral-400">
                            {obs.timestamp}
                          </span>
                          <span>{obs.text}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </main>
  )
}
