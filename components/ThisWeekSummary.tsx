export type MatterTotal = { title: string; isAdmin: boolean; minutes: number }

export type WeekSummaryData = {
  matters: MatterTotal[]
  caseMinutes: number
  adminMinutes: number
  totalMinutes: number
}

function fmtDur(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = Math.round(minutes % 60)
  if (h === 0) return `${m} min`
  if (m === 0) return `${h} hr`
  return `${h} hr ${m} min`
}

export default function ThisWeekSummary({ data }: { data: WeekSummaryData }) {
  if (data.totalMinutes === 0) return null

  return (
    <div className="border border-neutral-200 rounded-xl p-5 mb-6">
      <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-4">
        This Week
      </p>
      <table className="w-full text-sm">
        <tbody>
          {data.matters.map((m) => (
            <tr key={m.title}>
              <td className="text-neutral-800 py-1">{m.title}</td>
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
    </div>
  )
}
