'use client'

import { useEffect, useState } from 'react'
import { useCaptureSession } from '@/lib/capture/capture-session'
import CaptureDiagnosticsPanel from './CaptureDiagnosticsPanel'
import type { Episode } from '@/lib/types'

type Props = {
  onEpisodeSaved: (ep: Episode) => void
}

const DISCLOSURE_KEY = 'bh-capture-disclosed'

const DISCLOSURE_TEXT =
  'BuildHarvey analyzes selected text visible on your shared screen to identify work activities and organize them into Episodes. Raw video is never uploaded. Only selected evidence screenshots are saved with finalized Episodes.'

function fmtElapsed(s: number): string {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}h ${m}m ${sec}s`
  if (m > 0) return `${m}m ${sec}s`
  return `${sec}s`
}

export default function WebCaptureCard({ onEpisodeSaved }: Props) {
  const {
    state,
    elapsedSeconds,
    syncStatus,
    queuedCount,
    permanentlyFailedCount,
    surfaceWarning,
    analysisBacklogged,
    diagnostics,
    startCapture,
    stopCapture,
    retryOcr,
  } = useCaptureSession(onEpisodeSaved)

  const [isMobile, setIsMobile] = useState(false)
  const [disclosed, setDisclosed] = useState(false)
  const [mounted, setMounted] = useState(false)
  const [showDiagnostics, setShowDiagnostics] = useState(false)

  useEffect(() => {
    setMounted(true)
    setIsMobile(window.matchMedia?.('(pointer: coarse)').matches ?? false)
    setDisclosed(localStorage.getItem(DISCLOSURE_KEY) === 'true')
    setShowDiagnostics(
      process.env.NEXT_PUBLIC_CAPTURE_DEBUG === 'true' ||
        window.location.search.includes('captureDebug=1'),
    )
  }, [])

  function handleUnderstood() {
    localStorage.setItem(DISCLOSURE_KEY, 'true')
    setDisclosed(true)
    startCapture()
  }

  // Config flag check
  if (process.env.NEXT_PUBLIC_REMOTE_ANALYSIS === 'false') {
    return (
      <div className="border border-neutral-200 rounded-xl p-5 mb-6">
        <p className="text-sm text-neutral-500">
          Remote analysis is disabled. Contact your administrator.
        </p>
      </div>
    )
  }

  // Mobile check (only after mount to avoid SSR mismatch)
  if (mounted && isMobile) {
    return (
      <div className="border border-neutral-200 rounded-xl p-5 mb-6">
        <p className="text-sm text-neutral-500">
          Screen capture requires a desktop computer with Chrome, Edge, or Safari.
        </p>
      </div>
    )
  }

  // Sync badge — only shown during recording; never shows "Synced" while actively capturing
  function renderSyncBadge() {
    if (analysisBacklogged) return null
    if (syncStatus === 'syncing') {
      return (
        <span className="text-xs text-neutral-400 ml-2">Syncing\u2026</span>
      )
    }
    if (syncStatus === 'error' || permanentlyFailedCount > 0) {
      return <span className="text-xs text-red-500 ml-2">Sync error</span>
    }
    if (syncStatus === 'queued' || queuedCount > 0) {
      return (
        <span className="text-xs text-neutral-400 ml-2">
          {queuedCount} queued
        </span>
      )
    }
    // Omit "Synced" badge while actively recording — it would be misleading
    if (syncStatus === 'idle' && queuedCount === 0 && state !== 'recording') {
      return <span className="text-xs text-neutral-400 ml-2">Synced</span>
    }
    return null
  }

  function renderContent() {
    if (state === 'capture_unavailable') {
      return (
        <p className="text-sm text-neutral-500">
          Screen capture is not available in this browser. Use the latest
          Chrome, Edge, or Safari on a desktop computer.
        </p>
      )
    }

    if (state === 'error') {
      return (
        <div>
          <p className="text-sm text-neutral-500 mb-3">
            Something went wrong. Try again.
          </p>
          <button
            onClick={startCapture}
            className="text-sm font-medium bg-neutral-900 text-white px-4 py-1.5 rounded
                       hover:bg-neutral-700 transition-colors"
          >
            Retry
          </button>
        </div>
      )
    }

    if (state === 'requesting') {
      return (
        <p className="text-sm text-neutral-400">
          Waiting for screen sharing permission\u2026
        </p>
      )
    }

    if (state === 'screen_connected' || state === 'loading_ocr') {
      return (
        <p className="text-sm text-neutral-400">
          Screen connected \u2014 preparing text recognition\u2026
        </p>
      )
    }

    if (state === 'ocr_error') {
      return (
        <div>
          <p className="text-sm text-neutral-700 mb-1">
            Screen sharing is active, but BuildHarvey cannot read the screen.
          </p>
          {diagnostics.lastPipelineError && (
            <p className="text-xs text-neutral-400 mb-3 font-mono">
              [{diagnostics.lastPipelineError.stage}]{' '}
              {diagnostics.lastPipelineError.error.slice(0, 120)}
            </p>
          )}
          <button
            onClick={retryOcr}
            className="text-sm font-medium bg-neutral-900 text-white px-4 py-1.5 rounded
                       hover:bg-neutral-700 transition-colors"
          >
            Retry OCR
          </button>
        </div>
      )
    }

    if (state === 'recording') {
      const hasOcrSuccess = diagnostics.ocrSuccesses > 0
      return (
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span
              className="w-2 h-2 rounded-full inline-block bg-red-500 animate-pulse"
            />
            <span className="text-sm font-medium text-neutral-800">
              {hasOcrSuccess
                ? 'BuildHarvey is actively reading your shared screen'
                : 'Screen connected \u2014 reading your screen'}
            </span>
          </div>
          <div className="flex items-center">
            <span className="text-sm text-neutral-500 font-mono">
              {fmtElapsed(elapsedSeconds)}
            </span>
            {renderSyncBadge()}
          </div>
          {surfaceWarning && (
            <p className="mt-2 text-xs text-amber-600">{surfaceWarning}</p>
          )}
          <button
            onClick={stopCapture}
            className="mt-4 text-sm font-medium bg-neutral-900 text-white px-4 py-1.5 rounded
                       hover:bg-neutral-700 transition-colors"
          >
            Stop Work Session
          </button>
        </div>
      )
    }

    if (state === 'stopping') {
      return (
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full inline-block bg-yellow-400" />
          <span className="text-sm text-neutral-500">Finishing session\u2026</span>
        </div>
      )
    }

    if (state === 'stopped') {
      return (
        <div>
          <p className="text-sm text-neutral-700 mb-3">
            Session complete. Your work has been captured.
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={startCapture}
              className="text-sm font-medium bg-neutral-900 text-white px-4 py-1.5 rounded
                         hover:bg-neutral-700 transition-colors"
            >
              Start New Session
            </button>
            {renderSyncBadge()}
          </div>
        </div>
      )
    }

    if (state === 'permission_denied') {
      return (
        <div>
          <p className="text-sm text-amber-600 mb-3">
            Screen sharing was cancelled.
          </p>
          <button
            onClick={startCapture}
            className="text-sm font-medium bg-neutral-900 text-white px-4 py-1.5 rounded
                       hover:bg-neutral-700 transition-colors"
          >
            Start Work Session
          </button>
        </div>
      )
    }

    // state === 'ready'
    // Show disclosure panel if not yet disclosed and not mobile
    if (mounted && !disclosed && !isMobile) {
      return (
        <div>
          <p className="text-sm text-neutral-600 mb-4 leading-relaxed">
            {DISCLOSURE_TEXT}
          </p>
          <button
            onClick={handleUnderstood}
            className="text-sm font-medium bg-neutral-900 text-white px-4 py-1.5 rounded
                       hover:bg-neutral-700 transition-colors"
          >
            Understood, Start Session
          </button>
        </div>
      )
    }

    return (
      <div>
        <p className="text-xs text-neutral-400 mb-3">
          Select Entire Screen for best results.
        </p>
        <button
          onClick={startCapture}
          className="text-sm font-medium bg-neutral-900 text-white px-4 py-1.5 rounded
                     hover:bg-neutral-700 transition-colors"
        >
          Start Work Session
        </button>
      </div>
    )
  }

  return (
    <div>
      {mounted && showDiagnostics && (
        <CaptureDiagnosticsPanel diagnostics={diagnostics} />
      )}
      <div className="border border-neutral-200 rounded-xl p-5 mb-6">
        {renderContent()}
      </div>
      {analysisBacklogged && (
        <p className="text-xs text-neutral-500 -mt-4 mb-4 px-1">
          Capture is continuing locally. Some activity is waiting to be
          organized.
        </p>
      )}
    </div>
  )
}
