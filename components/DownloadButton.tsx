'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'

type State =
  | { status: 'idle' }
  | { status: 'preparing' }
  | { status: 'started'; url: string }
  | { status: 'failed'; message: string }
  | { status: 'unavailable' }
  | { status: 'auth_required' }

const ERROR_MESSAGES: Record<string, string> = {
  authentication_required:       'Sign in to download BuildHarvey.',
  email_verification_required:   'Verify your email before downloading.',
  release_unavailable:           'The BuildHarvey installer is unavailable right now. Please try again shortly.',
  invalid_release_configuration: 'The BuildHarvey installer is unavailable right now. Please try again shortly.',
  too_many_requests:             'Too many download attempts. Please try again shortly.',
  download_failed:               'Download failed. Please try again.',
}

function triggerDownload(url: string) {
  const a = document.createElement('a')
  a.href = url
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

function detectPlatform(): 'macos' | 'windows' | 'other' {
  if (typeof navigator === 'undefined') return 'other'
  const ua = navigator.userAgent.toLowerCase()
  if (ua.includes('win')) return 'windows'
  if (ua.includes('mac')) return 'macos'
  return 'other'
}

interface Props {
  label?: string
}

export default function DownloadButton({ label }: Props) {
  const router = useRouter()
  const [state, setState] = useState<State>({ status: 'idle' })
  const [platform, setPlatform] = useState<'macos' | 'windows' | 'other'>('other')

  useEffect(() => {
    setPlatform(detectPlatform())
  }, [])

  async function handleDownload() {
    if (state.status === 'preparing') return
    setState({ status: 'preparing' })

    const endpoint = platform === 'windows' ? '/api/download/windows' : '/api/download'

    try {
      const res = await fetch(endpoint, { method: 'POST' })
      const json = await res.json()

      if (res.status === 401) {
        setState({ status: 'auth_required' })
        router.push('/')
        return
      }

      if (res.status === 403) {
        setState({ status: 'auth_required' })
        router.push('/')
        return
      }

      if (res.status === 404 || res.status === 409) {
        setState({ status: 'unavailable' })
        return
      }

      if (!res.ok || json.error) {
        const msg = json.error
          ? (ERROR_MESSAGES[json.error] ?? ERROR_MESSAGES.download_failed)
          : ERROR_MESSAGES.download_failed
        setState({ status: 'failed', message: msg })
        return
      }

      triggerDownload(json.url)
      setState({ status: 'started', url: json.url })
    } catch {
      setState({ status: 'failed', message: ERROR_MESSAGES.download_failed })
    }
  }

  const buttonLabel =
    state.status === 'preparing' ? 'Preparing download…'
    : state.status === 'failed'  ? 'Try again'
    : label ?? 'Download BuildHarvey'

  const buttonDisabled =
    state.status === 'preparing' || state.status === 'unavailable'

  return (
    <div>
      <button
        onClick={handleDownload}
        disabled={buttonDisabled}
        className="w-full bg-neutral-900 text-white rounded px-4 py-2 text-sm font-medium disabled:opacity-40"
      >
        {state.status === 'unavailable' ? 'Unavailable' : buttonLabel}
      </button>

      {state.status === 'failed' && (
        <p className="text-sm text-red-600 mt-3">{state.message}</p>
      )}

      {state.status === 'started' && (
        <div className="mt-4 text-sm text-neutral-700 space-y-1">
          <p>Your download has started.</p>
          {platform === 'windows' ? (
            <>
              <p>Run <strong>BuildHarveySetup.exe</strong> to install BuildHarvey.</p>
              <p className="text-neutral-500 text-xs mt-1">
                If Windows shows a SmartScreen warning, click{' '}
                <strong>More info</strong> then <strong>Run anyway</strong>.
              </p>
            </>
          ) : (
            <>
              <p>Open the DMG, drag BuildHarvey to Applications.</p>
              <p className="text-neutral-500 text-xs mt-1">
                On first open: right-click BuildHarvey → <strong>Open</strong> →{' '}
                <strong>Open</strong> to bypass Gatekeeper.
              </p>
            </>
          )}
          <p className="mt-2 text-neutral-500 text-xs">
            If your download didn&apos;t start:{' '}
            <a href={state.url} className="underline text-neutral-900">
              Download BuildHarvey
            </a>
          </p>
        </div>
      )}
    </div>
  )
}
