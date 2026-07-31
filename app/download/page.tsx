'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'

interface ReleaseInfo {
  version: string
  sha256: string | null
}

export default function DownloadPage() {
  const router = useRouter()
  const [release, setRelease] = useState<ReleaseInfo | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch('/api/download/info')
      .then((r) => r.json())
      .then((d) => {
        if (d.version) setRelease(d)
      })
      .catch(() => {})
  }, [])

  async function handleDownload() {
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/download', { method: 'POST' })
      const json = await res.json()
      if (!res.ok || json.error) {
        setError(json.error ?? 'Download unavailable')
        return
      }
      window.location.href = json.url
    } catch {
      setError('Download failed. Try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-white">
      <div className="max-w-sm px-6 w-full">
        <h1 className="text-lg font-semibold text-neutral-900 mb-2">
          Download BuildHarvey
        </h1>

        {release && (
          <p className="text-sm text-neutral-500 mb-1">Version {release.version}</p>
        )}
        {release?.sha256 && (
          <p className="text-xs text-neutral-400 mb-6 break-all font-mono">
            SHA-256: {release.sha256}
          </p>
        )}

        <button
          onClick={handleDownload}
          disabled={loading}
          className="w-full bg-neutral-900 text-white rounded px-4 py-2 text-sm font-medium disabled:opacity-40 mb-4"
        >
          {loading ? 'Preparing…' : 'Download for Mac'}
        </button>

        {error && <p className="text-sm text-red-600 mb-4">{error}</p>}

        <p className="text-sm text-neutral-500">
          After installing, open BuildHarvey and connect your account.
        </p>
      </div>
    </div>
  )
}
