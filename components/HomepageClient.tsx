'use client'

import AgentStatusCard from './AgentStatusCard'
import ReportGenerator from './ReportGenerator'
import EpisodeList from './EpisodeList'
import ThisWeekSummary from './ThisWeekSummary'
import type { WeekSummaryData } from './ThisWeekSummary'
import type { Episode } from '@/lib/types'

type Props = {
  episodes: Episode[]
  weekSummary: WeekSummaryData
  deviceId: string
}

export default function HomepageClient({ episodes, weekSummary, deviceId }: Props) {
  return (
    <>
      <AgentStatusCard deviceId={deviceId} />
      <ThisWeekSummary data={weekSummary} />
      <div className="mb-10">
        <ReportGenerator />
      </div>
      <EpisodeList initialEpisodes={episodes} />
    </>
  )
}
