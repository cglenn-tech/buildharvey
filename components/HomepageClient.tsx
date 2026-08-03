'use client'

import { useState, useMemo } from 'react'
import DesktopAgentCard from './DesktopAgentCard'
import ReportGenerator from './ReportGenerator'
import EpisodeList from './EpisodeList'
import ThisWeekSummary from './ThisWeekSummary'
import ManualEntryForm from './ManualEntryForm'
import type { WeekSummaryData } from './ThisWeekSummary'
import type { Episode } from '@/lib/types'

type Props = { episodes: Episode[] }

function localIsoDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function isoMonday(d: Date): string {
  const day = d.getDay()
  const diff = day === 0 ? -6 : 1 - day
  const mon = new Date(d)
  mon.setDate(d.getDate() + diff)
  return localIsoDate(mon)
}

function normalizeProjectKey(title: string): string {
  return title.trim().replace(/\s+/g, ' ').toLowerCase()
}

function computeWeekSummary(episodes: Episode[]): WeekSummaryData {
  const now = new Date()
  const today = localIsoDate(now)
  const monday = isoMonday(now)

  const weekEps = episodes.filter((ep) => {
    const d = new Date(ep.started_at)
    const epDate = localIsoDate(d)
    return epDate >= monday && epDate <= today && ep.is_reportable !== false
  })

  const projectMap: Record<string, { minutes: number; displayName: string }> = {}
  let adminMinutes = 0

  for (const ep of weekEps) {
    if (ep.work_type === 'administrative') {
      adminMinutes += ep.duration_minutes
    } else {
      const k = normalizeProjectKey(ep.case_name?.trim() || 'Unknown')
      if (projectMap[k]) {
        projectMap[k].minutes += ep.duration_minutes
      } else {
        projectMap[k] = {
          minutes: ep.duration_minutes,
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

  const caseMinutes = matters
    .filter((m) => !m.isAdmin)
    .reduce((s, m) => s + m.minutes, 0)

  return { matters, caseMinutes, adminMinutes, totalMinutes: caseMinutes + adminMinutes }
}

export default function HomepageClient({ episodes: init }: Props) {
  const [episodes, setEpisodes] = useState<Episode[]>(init)

  function handleEpisodeSaved(ep: Episode) {
    setEpisodes((prev) => {
      const exists = prev.some((e) => e.id === ep.id)
      return exists
        ? prev.map((e) => (e.id === ep.id ? ep : e))
        : [ep, ...prev]
    })
  }

  function handleDelete(id: string) {
    setEpisodes((prev) => prev.filter((e) => e.id !== id))
  }

  function handleUpdate(ep: Episode) {
    setEpisodes((prev) => prev.map((e) => (e.id === ep.id ? ep : e)))
  }

  function handleMerge(keepId: string, dropId: string, merged: Episode) {
    setEpisodes((prev) =>
      prev
        .filter((e) => e.id !== dropId)
        .map((e) => (e.id === keepId ? merged : e)),
    )
  }

  const weekSummary = useMemo(() => computeWeekSummary(episodes), [episodes])

  return (
    <>
      <DesktopAgentCard />
      <ThisWeekSummary data={weekSummary} />
      <div className="mb-10">
        <ReportGenerator />
      </div>
      <ManualEntryForm onEpisodeSaved={handleEpisodeSaved} />
      <EpisodeList
        episodes={episodes}
        onDelete={handleDelete}
        onUpdate={handleUpdate}
        onMerge={handleMerge}
      />
    </>
  )
}
