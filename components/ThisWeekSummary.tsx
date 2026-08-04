'use client'

import { useState, useMemo, useEffect } from 'react'
import Link from 'next/link'
import type { Episode } from '@/lib/types'

export type MatterTotal = { title: string; isAdmin: boolean; minutes: number }

export type WeekSummaryData = {
  matters: MatterTotal[]
  caseMinutes: number
  adminMinutes: number
  totalMinutes: number
}

type Period = 'today' | 'week' | 'month' | 'custom'

type Props = {
  episodes: Episode[]
  onEpisodeUpdate?: (ep: Episode) => void
  supabase?: import('@supabase/supabase-js').SupabaseClient | null
}

function fmtDur(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = Math.round(minutes % 60)
  if (h === 0) return `${m} min`
  if (m === 0) return `${h} hr`
  return `${h} hr ${m} min`
}

function localIsoDate(d: Date): string {
  const y = d.getFullYear()
  const mo = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${mo}-${day}`
}

function isoMonday(d: Date): string {
  const day = d.getDay()
  const diff = day === 0 ? -6 : 1 - day
  const mon = new Date(d)
  mon.setDate(d.getDate() + diff)
  return localIsoDate(mon)
}

function periodLabel(period: Period, customStart: string, customEnd: string): string {
  switch (period) {
    case 'today': return 'Today'
    case 'week': return 'This Week'
    case 'month': return 'This Month'
    case 'custom': return `${customStart} – ${customEnd}`
  }
}

function computeSummary(episodes: Episode[], period: Period, customStart: string, customEnd: string): WeekSummaryData {
  const now = new Date()
  const today = localIsoDate(now)

  let from: string
  let to: string

  switch (period) {
    case 'today':
      from = today
      to = today
      break
    case 'week':
      from = isoMonday(now)
      to = today
      break
    case 'month':
      from = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`
      to = today
      break
    case 'custom':
      from = customStart
      to = customEnd
      break
  }

  const filtered = episodes.filter((ep) => {
    const d = localIsoDate(new Date(ep.started_at))
    return d >= from && d <= to && ep.is_reportable !== false
  })

  const projectMap: Record<string, { minutes: number; displayName: string }> = {}
  let adminMinutes = 0

  for (const ep of filtered) {
    if (ep.work_type === 'administrative') {
      adminMinutes += ep.duration_minutes ?? 0
    } else {
      const k = (ep.case_name?.trim() || 'Unknown').toLowerCase().replace(/\s+/g, ' ')
      if (projectMap[k]) {
        projectMap[k].minutes += ep.duration_minutes ?? 0
      } else {
        projectMap[k] = {
          minutes: ep.duration_minutes ?? 0,
          displayName: ep.case_name?.trim() || 'Unknown',
        }
      }
    }
  }

  const matters = Object.values(projectMap)
    .sort((a, b) => b.minutes - a.minutes)
    .map((v) => ({ title: v.displayName, isAdmin: false, minutes: v.minutes }))

  if (adminMinutes > 0) {
    matters.push({ title: 'Administrative', isAdmin: true, minutes: adminMinutes })
  }

  const caseMinutes = matters.filter((m) => !m.isAdmin).reduce((s, m) => s + m.minutes, 0)

  return { matters, caseMinutes, adminMinutes, totalMinutes: caseMinutes + adminMinutes }
}

const PERIODS: { id: Period; label: string }[] = [
  { id: 'today', label: 'Today' },
  { id: 'week', label: 'This Week' },
  { id: 'month', label: 'This Month' },
  { id: 'custom', label: 'Custom' },
]

export default function ThisWeekSummary({ episodes: initEpisodes, onEpisodeUpdate, supabase }: Props) {
  const [episodes, setEpisodes] = useState<Episode[]>(initEpisodes)
  const [period, setPeriod] = useState<Period>('week')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')
  const [showCustom, setShowCustom] = useState(false)

  // Sync when parent updates episodes (e.g. from manual entry or other realtime)
  useEffect(() => {
    setEpisodes(initEpisodes)
  }, [initEpisodes])

  // Supabase Realtime subscription for live episode updates
  useEffect(() => {
    if (!supabase) return

    const channel = supabase
      .channel('episodes-summary')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'episodes' },
        (payload) => {
          const incoming = payload.new as Episode | undefined
          if (!incoming) return
          setEpisodes((prev) => {
            const exists = prev.some((e) => e.id === incoming.id)
            const updated = exists
              ? prev.map((e) => (e.id === incoming.id ? incoming : e))
              : [incoming, ...prev]
            if (onEpisodeUpdate) onEpisodeUpdate(incoming)
            return updated
          })
        }
      )
      .subscribe()

    return () => {
      supabase.removeChannel(channel)
    }
  }, [supabase, onEpisodeUpdate])

  const data = useMemo(
    () => computeSummary(episodes, period, customStart, customEnd),
    [episodes, period, customStart, customEnd]
  )

  if (data.totalMinutes === 0 && period !== 'custom') {
    // Still render tabs even when empty (but hide the table)
  }

  return (
    <div className="border border-neutral-200 rounded-xl p-5 mb-6">
      {/* Tab bar */}
      <div className="flex gap-1 mb-4">
        {PERIODS.map((p) => (
          <button
            key={p.id}
            onClick={() => {
              setPeriod(p.id)
              if (p.id === 'custom') setShowCustom(true)
              else setShowCustom(false)
            }}
            className={
              `px-3 py-1 rounded-full text-xs font-medium transition-colors ` +
              (period === p.id
                ? 'bg-neutral-900 text-white'
                : 'text-neutral-500 hover:text-neutral-800')
            }
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Custom date range inputs */}
      {showCustom && (
        <div className="flex gap-2 mb-4 items-center">
          <input
            type="date"
            value={customStart}
            onChange={(e) => setCustomStart(e.target.value)}
            className="text-xs border border-neutral-200 rounded px-2 py-1"
          />
          <span className="text-xs text-neutral-400">to</span>
          <input
            type="date"
            value={customEnd}
            onChange={(e) => setCustomEnd(e.target.value)}
            className="text-xs border border-neutral-200 rounded px-2 py-1"
          />
        </div>
      )}

      <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-4">
        {periodLabel(period, customStart, customEnd)}
      </p>

      {data.totalMinutes === 0 ? (
        <p className="text-sm text-neutral-400">No recorded time for this period.</p>
      ) : (
        <table className="w-full text-sm">
          <tbody>
            {data.matters.map((m) => (
              <tr key={m.title}>
                <td className="text-neutral-800 py-1">
                  {m.isAdmin ? (
                    <span className="text-neutral-500 italic">{m.title}</span>
                  ) : (
                    <Link
                      href={`/project?name=${encodeURIComponent(m.title)}`}
                      className="hover:underline hover:text-neutral-600 transition-colors"
                    >
                      {m.title}
                    </Link>
                  )}
                </td>
                <td className="text-neutral-500 text-right py-1 pl-4 whitespace-nowrap">
                  {fmtDur(m.minutes)}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t border-neutral-200">
              <td className="text-neutral-900 font-medium py-2">Total recorded time</td>
              <td className="text-neutral-900 font-medium text-right py-2 pl-4 whitespace-nowrap">
                {fmtDur(data.totalMinutes)}
              </td>
            </tr>
          </tfoot>
        </table>
      )}
    </div>
  )
}
