'use client'

import { useEffect, useRef, useState } from 'react'
import type { RealtimeChannel } from '@supabase/supabase-js'
import { getBrowserClient } from '@/lib/supabase-browser'

type CardState =
  | 'connecting'    // subscribed to channel, waiting for agent presence (≤5 s)
  | 'unavailable'   // no agent in channel after 5 s, or channel error
  | 'idle'          // agent present, not recording
  | 'recording'     // agent present, recording active
  | 'stopping'      // stop sent, waiting for agent confirmation
  | 'sync_pending'  // agent finished recording, syncing episode
  | 'error'         // unexpected failure

const STATE_LABELS: Record<CardState, string> = {
  connecting: 'Connecting',
  unavailable: 'Desktop app unavailable',
  idle: 'Ready to start',
  recording: 'Recording',
  stopping: 'Stopping',
  sync_pending: 'Sync pending',
  error: 'Error',
}

const DOT_COLORS: Record<CardState, string> = {
  connecting: 'bg-neutral-300',
  unavailable: 'bg-neutral-300',
  idle: 'bg-green-400',
  recording: 'bg-red-500 animate-pulse',
  stopping: 'bg-yellow-400',
  sync_pending: 'bg-yellow-400',
  error: 'bg-red-400',
}

type Props = { deviceId: string }

export default function AgentStatusCard({ deviceId }: Props) {
  const [state, setState] = useState<CardState>('connecting')
  const channelRef = useRef<RealtimeChannel | null>(null)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const supabase = getBrowserClient()
    const topic = `buildharvey:device:${deviceId}`

    const channel = supabase.channel(topic, {
      config: {
        broadcast: { ack: false, self: false },
        presence: { key: 'browser' },
        private: true,
      },
    })
    channelRef.current = channel

    // ── 5-second timeout: if no agent appears, show unavailable ──────────────
    timeoutRef.current = setTimeout(() => {
      setState((prev) => (prev === 'connecting' ? 'unavailable' : prev))
    }, 5000)

    function clearConnectingTimeout() {
      if (timeoutRef.current !== null) {
        clearTimeout(timeoutRef.current)
        timeoutRef.current = null
      }
    }

    // ── Status broadcast from agent ───────────────────────────────────────────
    channel.on('broadcast', { event: 'status' }, ({ payload }) => {
      const agentState: string = payload?.state ?? ''
      if (agentState === 'recording') {
        clearConnectingTimeout()
        setState('recording')
      } else if (agentState === 'idle') {
        clearConnectingTimeout()
        setState('idle')
      } else if (agentState === 'stopping') {
        setState('stopping')
      } else if (agentState === 'sync_pending') {
        setState('sync_pending')
      }
    })

    // ── Presence: detect agent ────────────────────────────────────────────────
    channel.on('presence', { event: 'sync' }, () => {
      const presenceState = channel.presenceState<{ type: string }>()
      const agentPresent = Object.values(presenceState)
        .flat()
        .some((p) => p.type === 'agent')

      if (agentPresent) {
        clearConnectingTimeout()
        // Request the agent's current status so we know whether it's idle/recording
        channel.send({ type: 'broadcast', event: 'status_request', payload: {} })
      } else {
        // Agent left or not yet joined
        setState((prev) => {
          if (prev === 'connecting') return prev  // still waiting
          return 'unavailable'
        })
      }
    })

    channel.on('presence', { event: 'join' }, ({ newPresences }) => {
      const agentJoined = (newPresences as Array<{ type: string }>).some(
        (p) => p.type === 'agent'
      )
      if (agentJoined) {
        clearConnectingTimeout()
        // Ask agent for its current state
        channel.send({ type: 'broadcast', event: 'status_request', payload: {} })
      }
    })

    channel.on('presence', { event: 'leave' }, ({ leftPresences }) => {
      const agentLeft = (leftPresences as Array<{ type: string }>).some(
        (p) => p.type === 'agent'
      )
      if (agentLeft) {
        const presenceState = channel.presenceState<{ type: string }>()
        const agentStillPresent = Object.values(presenceState)
          .flat()
          .some((p) => p.type === 'agent')
        if (!agentStillPresent) {
          setState('unavailable')
        }
      }
    })

    // ── Subscribe ─────────────────────────────────────────────────────────────
    channel.subscribe(async (status) => {
      if (status === 'SUBSCRIBED') {
        await channel.track({ type: 'browser' })
        // Check if agent is already in the channel
        const presenceState = channel.presenceState<{ type: string }>()
        const agentPresent = Object.values(presenceState)
          .flat()
          .some((p) => p.type === 'agent')
        if (agentPresent) {
          clearConnectingTimeout()
          channel.send({ type: 'broadcast', event: 'status_request', payload: {} })
        }
      } else if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT') {
        clearConnectingTimeout()
        setState('error')
      }
    })

    return () => {
      clearConnectingTimeout()
      supabase.removeChannel(channel)
      channelRef.current = null
    }
  }, [deviceId])

  function sendStart() {
    setState('connecting')  // wait for agent's recording confirmation
    channelRef.current?.send({ type: 'broadcast', event: 'start', payload: {} })
  }

  function sendStop() {
    setState('stopping')
    channelRef.current?.send({ type: 'broadcast', event: 'stop', payload: {} })
  }

  const label = STATE_LABELS[state]
  const dotColor = DOT_COLORS[state]

  if (state === 'unavailable') {
    return (
      <div className="border border-neutral-200 rounded-xl p-5 mb-6">
        <div className="flex items-center gap-2 mb-1">
          <span className={`w-2 h-2 rounded-full inline-block ${dotColor}`} />
          <p className="text-sm font-medium text-neutral-500">{label}</p>
        </div>
        <p className="text-xs text-neutral-400">
          Open BuildHarvey on your Mac to start recording.{' '}
          <a href="/download" className="underline hover:text-neutral-600">
            Download
          </a>
        </p>
      </div>
    )
  }

  if (state === 'idle') {
    return (
      <div className="border border-neutral-200 rounded-xl p-5 mb-6">
        <div className="flex items-center gap-2 mb-3">
          <span className={`w-2 h-2 rounded-full inline-block ${dotColor}`} />
          <p className="text-sm font-medium text-neutral-700">{label}</p>
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

  if (state === 'recording') {
    return (
      <div className="border border-neutral-200 rounded-xl p-5 mb-6">
        <div className="flex items-center gap-2 mb-3">
          <span className={`w-2 h-2 rounded-full inline-block ${dotColor}`} />
          <p className="text-sm font-medium text-neutral-700">{label}</p>
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

  // connecting / stopping / sync_pending / error — status-only display
  return (
    <div className="border border-neutral-200 rounded-xl p-5 mb-6">
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full inline-block ${dotColor}`} />
        <p className="text-sm text-neutral-500">{label}</p>
      </div>
    </div>
  )
}
