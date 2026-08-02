'use client'
import { useEffect } from 'react'
import { getBrowserClient } from '@/lib/supabase-browser'

const AGENT_WS_URL = 'ws://localhost:39291'
const RECONNECT_INTERVAL = 5_000

/**
 * Maintains a WebSocket connection to the local BuildHarvey agent.
 * Sends an auth message with the Supabase user_id on connect so the agent
 * can reject connections from mismatched accounts.
 * Connection presence signals to the agent that a browser tab is open and
 * recording should be active. Absence for >10 minutes causes the agent to idle.
 * Renders nothing — purely a side-effect component.
 */
export default function AgentConnection() {
  useEffect(() => {
    let ws: WebSocket | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let destroyed = false

    async function connect() {
      if (destroyed) return

      // Get Supabase user_id before opening the socket
      let userId: string | null = null
      try {
        const supabase = getBrowserClient()
        const { data: { session } } = await supabase.auth.getSession()
        userId = session?.user?.id ?? null
      } catch {
        // If we can't identify the user, don't connect
        if (!destroyed) {
          retryTimer = setTimeout(connect, RECONNECT_INTERVAL)
        }
        return
      }

      if (!userId) {
        if (!destroyed) {
          retryTimer = setTimeout(connect, RECONNECT_INTERVAL)
        }
        return
      }

      try {
        ws = new WebSocket(AGENT_WS_URL)

        ws.onopen = () => {
          console.log('[agent] connected to local agent')
          ws?.send(JSON.stringify({ type: 'auth', user_id: userId }))
        }

        ws.onclose = () => {
          ws = null
          if (!destroyed) {
            retryTimer = setTimeout(connect, RECONNECT_INTERVAL)
          }
        }

        ws.onerror = () => ws?.close()
      } catch {
        if (!destroyed) {
          retryTimer = setTimeout(connect, RECONNECT_INTERVAL)
        }
      }
    }

    connect()

    return () => {
      destroyed = true
      if (retryTimer !== null) clearTimeout(retryTimer)
      ws?.close()
    }
  }, [])

  return null
}
