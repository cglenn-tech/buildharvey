'use client'

import { useEffect, useRef, useState } from 'react'
import { getBrowserClient } from '@/lib/supabase-browser'

const AGENT_WS_URL = 'ws://localhost:39291'
const RECONNECT_INTERVAL = 5_000

type ConnState = 'connecting' | 'idle' | 'recording' | 'disconnected'

export default function AgentStatusCard() {
  const [connState, setConnState] = useState<ConnState>('connecting')
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    let destroyed = false
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    function scheduleReconnect() {
      if (!destroyed) {
        setConnState('disconnected')
        retryTimer = setTimeout(connect, RECONNECT_INTERVAL)
      }
    }

    async function connect() {
      if (destroyed) return

      let userId: string | null = null
      try {
        const supabase = getBrowserClient()
        const { data: { session } } = await supabase.auth.getSession()
        userId = session?.user?.id ?? null
      } catch {
        scheduleReconnect()
        return
      }

      if (!userId) {
        scheduleReconnect()
        return
      }

      try {
        const ws = new WebSocket(AGENT_WS_URL)
        wsRef.current = ws

        ws.onopen = () => {
          ws.send(JSON.stringify({ type: 'auth', user_id: userId }))
        }

        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data as string)
            if (msg.type === 'status') {
              setConnState(msg.state === 'recording' ? 'recording' : 'idle')
            }
          } catch {
            // ignore malformed messages
          }
        }

        ws.onclose = () => {
          wsRef.current = null
          scheduleReconnect()
        }

        ws.onerror = () => ws.close()
      } catch {
        scheduleReconnect()
      }
    }

    connect()

    return () => {
      destroyed = true
      if (retryTimer !== null) clearTimeout(retryTimer)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [])

  function sendStart() {
    wsRef.current?.send(JSON.stringify({ type: 'start' }))
  }

  function sendStop() {
    wsRef.current?.send(JSON.stringify({ type: 'stop' }))
  }

  if (connState === 'connecting') {
    return (
      <div className="border border-neutral-200 rounded-xl p-5 mb-6">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-neutral-300 inline-block" />
          <p className="text-sm text-neutral-400">Connecting…</p>
        </div>
      </div>
    )
  }

  if (connState === 'disconnected') {
    return (
      <div className="border border-neutral-200 rounded-xl p-5 mb-6">
        <div className="flex items-center gap-2 mb-1">
          <span className="w-2 h-2 rounded-full bg-neutral-300 inline-block" />
          <p className="text-sm font-medium text-neutral-500">Agent not running</p>
        </div>
        <p className="text-xs text-neutral-400">
          Open BuildHarvey on your Mac to start recording.
        </p>
      </div>
    )
  }

  if (connState === 'idle') {
    return (
      <div className="border border-neutral-200 rounded-xl p-5 mb-6">
        <div className="flex items-center gap-2 mb-3">
          <span className="w-2 h-2 rounded-full bg-green-400 inline-block" />
          <p className="text-sm font-medium text-neutral-700">Agent connected · Idle</p>
        </div>
        <button
          onClick={sendStart}
          className="text-sm font-medium bg-neutral-900 text-white px-4 py-1.5 rounded
                     hover:bg-neutral-700 transition-colors"
        >
          Start Work Session
        </button>
      </div>
    )
  }

  // recording
  return (
    <div className="border border-neutral-200 rounded-xl p-5 mb-6">
      <div className="flex items-center gap-2 mb-3">
        <span className="w-2 h-2 rounded-full bg-red-500 inline-block animate-pulse" />
        <p className="text-sm font-medium text-neutral-700">Recording</p>
      </div>
      <button
        onClick={sendStop}
        className="text-sm text-neutral-600 border border-neutral-200 px-4 py-1.5 rounded
                   hover:bg-neutral-50 transition-colors"
      >
        Stop Work Session
      </button>
    </div>
  )
}
