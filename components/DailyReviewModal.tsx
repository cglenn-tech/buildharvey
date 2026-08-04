'use client'

import type { Episode } from '@/lib/types'

type Props = {
  episodes: Episode[]
  onDismiss: () => void
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

export default function DailyReviewModal({ episodes, onDismiss }: Props) {
  const today = localIsoDate(new Date())

  const todayEps = episodes.filter((ep) => {
    const d = new Date(ep.started_at)
    return localIsoDate(d) === today && ep.is_reportable !== false
  })

  const projectMap: Record<string, { minutes: number; displayName: string }> = {}
  let adminMinutes = 0

  for (const ep of todayEps) {
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

  const projectEntries = Object.values(projectMap).sort((a, b) => b.minutes - a.minutes)
  const caseMinutes = projectEntries.reduce((s, v) => s + v.minutes, 0)
  const grandTotal = caseMinutes + adminMinutes

  const needsReview = todayEps.filter((ep) => ep.key_observations.length === 0)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => { if (e.target === e.currentTarget) onDismiss() }}
    >
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
        <h2 className="text-base font-semibold text-neutral-900 mb-1">
          Today&apos;s Work Summary
        </h2>
        <p className="text-xs text-neutral-400 mb-5">
          {new Date().toLocaleDateString('en-US', {
            weekday: 'long', month: 'long', day: 'numeric',
          })}
        </p>

        {todayEps.length === 0 ? (
          <p className="text-sm text-neutral-500 mb-6">No sessions recorded today.</p>
        ) : (
          <table className="w-full text-sm mb-6">
            <tbody>
              {projectEntries.map((v) => (
                <tr key={v.displayName}>
                  <td className="text-neutral-800 py-1">{v.displayName}</td>
                  <td className="text-neutral-500 text-right py-1 pl-4 whitespace-nowrap">
                    {fmtDur(v.minutes)}
                  </td>
                </tr>
              ))}
              {adminMinutes > 0 && (
                <tr>
                  <td className="text-neutral-500 py-1 italic">Administrative</td>
                  <td className="text-neutral-500 text-right py-1 pl-4 whitespace-nowrap">
                    {fmtDur(adminMinutes)}
                  </td>
                </tr>
              )}
            </tbody>
            <tfoot>
              <tr className="border-t border-neutral-200">
                <td className="text-neutral-900 font-medium py-2">Total</td>
                <td className="text-neutral-900 font-medium text-right py-2 pl-4 whitespace-nowrap">
                  {fmtDur(grandTotal)}
                </td>
              </tr>
            </tfoot>
          </table>
        )}

        {needsReview.length > 0 && (
          <p className="text-xs text-amber-600 mb-4">
            {needsReview.length} session{needsReview.length > 1 ? 's' : ''} may need review
            — no observations recorded.
          </p>
        )}

        <button
          onClick={onDismiss}
          className="w-full bg-neutral-900 text-white text-sm font-medium py-2.5 rounded-lg hover:bg-neutral-700 transition-colors"
        >
          Done
        </button>
      </div>
    </div>
  )
}
