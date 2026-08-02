'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useSearchParams } from 'next/navigation'
import { Suspense } from 'react'

function ActivateContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const activationId = searchParams.get('id') ?? ''

  const [deviceName, setDeviceName] = useState<string | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'connected' | 'cancelled' | 'error'>('loading')
  const [errorMsg, setErrorMsg] = useState('')

  useEffect(() => {
    if (!activationId) {
      setStatus('error')
      setErrorMsg('Invalid activation link.')
      return
    }
    fetch(`/api/activate/info?id=${encodeURIComponent(activationId)}`)
      .then((r) => {
        if (!r.ok) throw new Error('Not found or expired')
        return r.json()
      })
      .then((d) => {
        setDeviceName(d.device_name ?? 'Unknown device')
        setStatus('ready')
      })
      .catch(() => {
        setStatus('error')
        setErrorMsg('This activation link is expired or invalid.')
      })
  }, [activationId])

  async function handleConnect() {
    setStatus('loading')
    try {
      const res = await fetch('/api/activate/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ activation_id: activationId }),
      })
      if (!res.ok) {
        const json = await res.json()
        setErrorMsg(json.error ?? 'Failed to connect.')
        setStatus('error')
        return
      }
      router.push('/')
    } catch {
      setErrorMsg('Request failed. Try again.')
      setStatus('ready')
    }
  }

  if (status === 'loading') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <p className="text-sm text-neutral-500">Loading…</p>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <p className="text-sm text-neutral-600">{errorMsg}</p>
      </div>
    )
  }

  if (status === 'connected') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <div className="text-center">
          <p className="text-neutral-900 font-medium mb-1">Connected.</p>
          <p className="text-sm text-neutral-500">You can close this tab.</p>
        </div>
      </div>
    )
  }

  if (status === 'cancelled') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <p className="text-sm text-neutral-600">Connection cancelled.</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-white">
      <div className="max-w-sm px-6 w-full">
        <h1 className="text-base font-semibold text-neutral-900 mb-4">
          Connect this computer?
        </h1>
        <div className="text-sm text-neutral-700 mb-6 space-y-1">
          <p>Device: {deviceName}</p>
          <p>System: macOS</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={handleConnect}
            className="flex-1 bg-neutral-900 text-white rounded px-4 py-2 text-sm font-medium"
          >
            Connect
          </button>
          <button
            onClick={() => setStatus('cancelled')}
            className="flex-1 border border-neutral-200 text-neutral-700 rounded px-4 py-2 text-sm"
          >
            Cancel
          </button>
        </div>
        {errorMsg && <p className="mt-3 text-sm text-red-600">{errorMsg}</p>}
      </div>
    </div>
  )
}

export default function ActivatePage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center bg-white">
        <p className="text-sm text-neutral-500">Loading…</p>
      </div>
    }>
      <ActivateContent />
    </Suspense>
  )
}
