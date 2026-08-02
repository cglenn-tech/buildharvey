'use client'

import AgentConnection from './AgentConnection'
import ReportGenerator from './ReportGenerator'
import EpisodeList from './EpisodeList'
import ThisWeekSummary from './ThisWeekSummary'
import type { WeekSummaryData } from './ThisWeekSummary'
import type { Episode } from '@/lib/types'

type Props = {
  episodes: Episode[]
  weekSummary: WeekSummaryData
}

export default function HomepageClient({ episodes, weekSummary }: Props) {
  return (
    <>
      <AgentConnection />
      <ThisWeekSummary data={weekSummary} />
      <div className="mb-10">
        <ReportGenerator />
      </div>
      <EpisodeList initialEpisodes={episodes} />
    </>
  )
}
