'use client'

import { useEffect, useState } from 'react'
import { getBrowserClient } from '@/lib/supabase-browser'
import AgentStatusCard from './AgentStatusCard'
import DownloadButton from './DownloadButton'

type DeviceRow = { id: string; last_seen_at: string | null }

type FetchState =
  | { status: 'loading' }
  | { status: 'no_device' }
  | { status: 'ready'; deviceId: string }
  | { status: 'error' }

export default function DesktopAgentCard() {
  const [fetchState, setFetchState] = useState<FetchState>({ status: 'loading' })

  useEffect(() => {
    const supabase = getBrowserClient()
    supabase
      .from('devices')
      .select('id, last_seen_at')
      .is('revoked_at', null)
      .order('last_seen_at', { ascending: false, nullsFirst: false })
      .limit(1)
      .then(({ data, error }) => {
        if (error || !data || data.length === 0) {
          setFetchState({ status: 'no_device' })
          return
        }
        const device = data[0] as DeviceRow
        setFetchState({ status: 'ready', deviceId: device.id })
      })
  }, [])

  if (fetchState.status === 'loading') {
    return (
      <div className="border border-neutral-200 rounded-xl p-5 mb-6">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full inline-block bg-neutral-200" />
          <span className="text-sm text-neutral-400">Connecting…</span>
        </div>
      </div>
    )
  }

  if (fetchState.status === 'no_device' || fetchState.status === 'error') {
    return (
      <div className="border border-neutral-200 rounded-xl p-5 mb-6">
        <p className="text-sm text-neutral-600 mb-3">
          Install the BuildHarvey desktop app to start capturing your work.
          Your browser does not need to stay open while recording.
        </p>
        <DownloadButton />
      </div>
    )
  }

  return (
    <div>
      <AgentStatusCard deviceId={fetchState.deviceId} />
      <p className="text-xs text-neutral-400 -mt-4 mb-6 px-1">
        You may close this page. The BuildHarvey desktop app will continue recording.
      </p>
    </div>
  )
}
