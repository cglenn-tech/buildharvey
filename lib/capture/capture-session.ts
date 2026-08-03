'use client'

import { useRef, useState, useEffect, useCallback } from 'react'
import { createWorker } from 'tesseract.js'
import { EpisodeEngine } from './episode-engine'
import type { AnalyzeResult, EpisodeCandidate, FinalizedEpisode } from './episode-engine'
import { drainSyncQueue } from './sync-queue'
import type { DrainResult } from './sync-queue'
import {
  putPendingEpisode,
  setSessionMeta,
  clearSessionMeta,
  setActiveEpisodeSnapshot,
  clearActiveEpisodeSnapshot,
} from './idb-buffer'
import { frameDiff, textJaccard } from './frame-differ'
import {
  FRAME_INTERVAL_MS,
  MIN_ANALYSIS_INTERVAL_MS,
  DIFF_THRESHOLD,
  OCR_DIFF_THRESHOLD,
  STRONG_CHANGE_THRESHOLD,
  CANVAS_WIDTH,
  CANVAS_HEIGHT,
  ANALYSIS_TIMEOUT_MS,
  OCR_TEXT_MAX_CHARS,
  MAX_CONTEXT_OBSERVATIONS,
  MAX_EVIDENCE_SCREENSHOTS,
} from './constants'
import type { Episode, KeyObservation } from '@/lib/types'

// Suppress unused-import warnings for types that are part of the public contract
// but not directly referenced in this file's value-level expressions.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
type _SuppressUnused = Episode | KeyObservation | typeof OCR_DIFF_THRESHOLD | typeof MAX_EVIDENCE_SCREENSHOTS

// ---------------------------------------------------------------------------
// Exported types
// ---------------------------------------------------------------------------

export type CaptureState =
  | 'ready'
  | 'requesting'
  | 'loading_ocr'
  | 'recording'
  | 'stopping'
  | 'stopped'
  | 'permission_denied'
  | 'capture_unavailable'
  | 'error'

export type SyncStatus = 'idle' | 'syncing' | 'queued' | 'error'

export type UseCaptureSession = {
  state: CaptureState
  elapsedSeconds: number
  syncStatus: SyncStatus
  queuedCount: number
  permanentlyFailedCount: number
  surfaceWarning: string | null
  analysisBacklogged: boolean
  startCapture: () => Promise<void>
  stopCapture: () => Promise<void>
  isSupported: boolean
}

// ---------------------------------------------------------------------------
// isSupported
// ---------------------------------------------------------------------------

const isSupported =
  typeof navigator !== 'undefined' &&
  'mediaDevices' in navigator &&
  'getDisplayMedia' in (navigator.mediaDevices as unknown as Record<string, unknown>)

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useCaptureSession(
  onEpisodeSaved: (ep: Episode) => void,
): UseCaptureSession {
  // Refs
  const streamRef = useRef<MediaStream | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const canvasCtxRef = useRef<CanvasRenderingContext2D | null>(null)
  const workerRef = useRef<Awaited<ReturnType<typeof createWorker>> | null>(null)
  const engineRef = useRef(new EpisodeEngine())
  const shutdownPromiseRef = useRef<Promise<void> | null>(null)
  const isProcessingRef = useRef(false)
  const captureSeqRef = useRef(0)
  const sessionSeqRef = useRef(0)
  const sessionIdRef = useRef('')
  const prevImageDataRef = useRef<ImageData | null>(null)
  const prevOcrTextRef = useRef('')
  const prevMeaningfulOcrRef = useRef('')
  const lastAnalysisAtRef = useRef(0)
  const lastCaptureAtRef = useRef(0)
  const schedulerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const startTimeRef = useRef(0)
  const isMountedRef = useRef(true)
  const pendingAnalysisCountRef = useRef(0)

  // Use a ref to track current state for use inside closures/cleanup
  const stateRef = useRef<CaptureState>('ready')

  // State
  const [state, setState] = useState<CaptureState>('ready')
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [syncStatus, setSyncStatus] = useState<SyncStatus>('idle')
  const [queuedCount, setQueuedCount] = useState(0)
  const [permanentlyFailedCount, setPermanentlyFailedCount] = useState(0)
  const [surfaceWarning, setSurfaceWarning] = useState<string | null>(null)
  const [analysisBacklogged, setAnalysisBacklogged] = useState(false)

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function safeSetState(s: CaptureState) {
    stateRef.current = s
    if (isMountedRef.current) setState(s)
  }

  function updateSyncUI(result: DrainResult) {
    setQueuedCount(result.remainingCount)
    setPermanentlyFailedCount(result.permanentlyFailedCount)
    setSyncStatus(
      result.permanentlyFailedCount > 0
        ? 'error'
        : result.remainingCount > 0
          ? 'queued'
          : 'idle',
    )
  }

  // ---------------------------------------------------------------------------
  // ensureWorker
  // ---------------------------------------------------------------------------

  async function ensureWorker() {
    if (workerRef.current) return workerRef.current
    // createWorker types vary across tesseract.js versions — cast to any to
    // allow the (lang, oem, options) overload used by the self-hosted build.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const worker = await (createWorker as any)('eng', 1, {
      workerPath: '/tesseract/worker.min.js',
      corePath: '/tesseract/tesseract-core.wasm.js',
      langPath: '/tesseract/',
      logger:
        process.env.NODE_ENV === 'development'
          ? (m: unknown) => console.log('[tesseract]', m)
          : undefined,
    }) as Awaited<ReturnType<typeof createWorker>>
    workerRef.current = worker
    return worker
  }

  // ---------------------------------------------------------------------------
  // saveEpisodeToQueue
  // ---------------------------------------------------------------------------

  async function saveEpisodeToQueue(finalized: FinalizedEpisode) {
    const { episode, selectedScreenshots, evidenceFilenames } = finalized
    await putPendingEpisode({
      episodeId: episode.id,
      episode,
      evidenceBlobs: selectedScreenshots.map((dataUrl, i) => ({
        dataUrl,
        filename: evidenceFilenames[i],
        storagePath: null,
        uploaded: false,
        storageConfirmed: false,
      })),
      episodeSaved: false,
      allScreenshotsSaved: selectedScreenshots.length === 0,
      retryCount: 0,
      lastRetryAt: null,
      failedPermanently: false,
    })
    if (isMountedRef.current) setSyncStatus('syncing')
    try {
      const result = await drainSyncQueue()
      if (isMountedRef.current) {
        updateSyncUI(result)
        onEpisodeSaved(episode)
      }
    } catch {
      if (isMountedRef.current) setSyncStatus('error')
    }
  }

  // ---------------------------------------------------------------------------
  // processFrame
  // ---------------------------------------------------------------------------

  async function processFrame(mySession: number, seq: number) {
    if (mySession !== sessionSeqRef.current) return
    if (!videoRef.current || !canvasCtxRef.current || !canvasRef.current) return

    const now = new Date().toISOString()
    const ctx = canvasCtxRef.current
    const canvas = canvasRef.current
    const video = videoRef.current

    if (process.env.NODE_ENV === 'development') {
      const actualInterval = Date.now() - lastCaptureAtRef.current
      console.log('[capture] tick', {
        seq,
        actualIntervalMs: actualInterval,
        pageHidden: document.hidden,
      })
    }
    lastCaptureAtRef.current = Date.now()

    // 1. Draw frame
    ctx.drawImage(video, 0, 0, CANVAS_WIDTH, CANVAS_HEIGHT)
    const imageData = ctx.getImageData(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT)

    // 2. Pixel diff
    const diffScore = prevImageDataRef.current
      ? frameDiff(prevImageDataRef.current, imageData)
      : 1
    if (diffScore < DIFF_THRESHOLD) return
    prevImageDataRef.current = imageData

    // 3. OCR
    const worker = workerRef.current
    if (!worker) return
    const ocrStart = Date.now()
    let ocrText: string
    try {
      const {
        data: { text },
      } = await worker.recognize(canvas)
      ocrText = text.trim()
    } catch {
      return
    }
    const ocrMs = Date.now() - ocrStart

    const textDiff = textJaccard(prevOcrTextRef.current, ocrText)
    prevOcrTextRef.current = ocrText

    // 4. Analysis gate
    const timeSinceAnalysis = Date.now() - lastAnalysisAtRef.current
    const shouldAnalyze =
      timeSinceAnalysis >= MIN_ANALYSIS_INTERVAL_MS ||
      textDiff >= STRONG_CHANGE_THRESHOLD
    if (!shouldAnalyze) return

    // 5. Screenshot for this analysis frame
    const screenshotDataUrl = canvas.toDataURL('image/jpeg', 0.7)

    // 6. Build analysis request
    const currentEp = engineRef.current.getCurrentEpisode()
    const lastMeaningfulAt = engineRef.current.getLastMeaningfulAt()
    const timeSinceMeaningful = lastMeaningfulAt
      ? (Date.now() - Date.parse(lastMeaningfulAt)) / 1000
      : null

    const body = {
      ocr_text: ocrText.slice(0, OCR_TEXT_MAX_CHARS),
      prev_ocr_text: prevMeaningfulOcrRef.current.slice(0, 500),
      timestamp: now,
      episode_context: currentEp
        ? {
            title: currentEp.case_name,
            work_type: currentEp.work_type,
            started_at: currentEp.started_at,
            recent_observations: currentEp.key_observations.slice(
              -MAX_CONTEXT_OBSERVATIONS,
            ),
            time_since_last_meaningful_seconds: timeSinceMeaningful,
          }
        : null,
    }

    // 7. Call analyze endpoint with timeout
    const ac = new AbortController()
    const timer = setTimeout(() => ac.abort(), ANALYSIS_TIMEOUT_MS)
    let res: Response
    const analyzeStart = Date.now()
    try {
      res = await fetch('/api/capture/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: ac.signal,
      })
    } catch (e: unknown) {
      pendingAnalysisCountRef.current++
      if (isMountedRef.current)
        setAnalysisBacklogged(pendingAnalysisCountRef.current > 0)
      return
    } finally {
      clearTimeout(timer)
    }
    const analyzeMs = Date.now() - analyzeStart

    // 8. Stale check
    if (seq !== captureSeqRef.current) return
    if (mySession !== sessionSeqRef.current) return

    if (!res.ok) {
      if (res.status === 429) {
        pendingAnalysisCountRef.current++
        if (isMountedRef.current) setAnalysisBacklogged(true)
      }
      return
    }

    // Clear backlog on success
    if (pendingAnalysisCountRef.current > 0) {
      pendingAnalysisCountRef.current = 0
      if (isMountedRef.current) setAnalysisBacklogged(false)
    }

    let result: AnalyzeResult
    try {
      result = await res.json()
    } catch {
      return
    }

    if (process.env.NODE_ENV === 'development') {
      console.log('[capture] analyzed', {
        seq,
        diffScore: diffScore.toFixed(3),
        ocrLen: ocrText.length,
        textDiff: textDiff.toFixed(3),
        ocrMs,
        analyzeMs,
        meaningful: result.meaningful,
        work_type: result.work_type,
        episode_action: result.episode_action,
      })
    }

    // 9. Build candidate
    const candidate: EpisodeCandidate = {
      timestamp: now,
      ocrText,
      screenshot: screenshotDataUrl,
      taskDescription: result.task_description,
      suggestedEpisodeName: result.suggested_episode_name,
      workType: result.work_type,
      issueWorkedOn: result.issue_worked_on,
      diffScore,
    }
    prevMeaningfulOcrRef.current = ocrText

    // 10. Feed engine
    const finalized = engineRef.current.handleAnalysis(result, candidate)
    if (finalized) await saveEpisodeToQueue(finalized)

    lastAnalysisAtRef.current = Date.now()

    // 11. Persist active episode snapshot for crash recovery
    const snap = engineRef.current.getRecoverySnapshot(sessionIdRef.current)
    if (snap) await setActiveEpisodeSnapshot(snap)
    else await clearActiveEpisodeSnapshot()

    // 12. Update session meta
    try {
      await setSessionMeta({
        sessionId: sessionIdRef.current,
        startedAt: new Date(startTimeRef.current).toISOString(),
        lastFrameAt: now,
        lastMeaningfulAt: engineRef.current.getLastMeaningfulAt(),
      })
    } catch {
      /* non-fatal */
    }
  }

  // ---------------------------------------------------------------------------
  // scheduleTick
  // ---------------------------------------------------------------------------

  async function scheduleTick() {
    // ALWAYS check inactivity first — before any early return
    const nowIso = new Date().toISOString()
    const inactiveFinalized = engineRef.current.checkInactivity(nowIso)
    if (inactiveFinalized) {
      await saveEpisodeToQueue(inactiveFinalized)
      await clearActiveEpisodeSnapshot()
    }

    // Single-flight guard
    if (isProcessingRef.current) return
    const mySession = sessionSeqRef.current
    isProcessingRef.current = true
    const captureSeq = ++captureSeqRef.current

    try {
      await processFrame(mySession, captureSeq)
    } finally {
      isProcessingRef.current = false
    }
  }

  // ---------------------------------------------------------------------------
  // doStop
  // ---------------------------------------------------------------------------

  async function doStop() {
    safeSetState('stopping')

    // Stop scheduler immediately
    if (schedulerRef.current) {
      clearInterval(schedulerRef.current)
      schedulerRef.current = null
    }
    if (elapsedTimerRef.current) {
      clearInterval(elapsedTimerRef.current)
      elapsedTimerRef.current = null
    }

    // Wait for in-flight frame (max 8s)
    const deadline = Date.now() + 8_000
    while (isProcessingRef.current && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 100))
    }

    // Final frame best-effort
    if (!isProcessingRef.current) {
      const mySession = sessionSeqRef.current
      const seq = ++captureSeqRef.current
      isProcessingRef.current = true
      try {
        await processFrame(mySession, seq)
      } catch {
        /* ignore */
      } finally {
        isProcessingRef.current = false
      }
    }

    // Close active episode
    const finalEp = engineRef.current.closeSession(new Date().toISOString())
    if (finalEp) await saveEpisodeToQueue(finalEp)

    // Flush queue
    try {
      const result = await drainSyncQueue()
      if (isMountedRef.current) updateSyncUI(result)
    } catch {
      /* non-fatal */
    }

    // NULL onended BEFORE stopping tracks (prevents re-triggering shutdown)
    const tracks = streamRef.current?.getTracks() ?? []
    tracks.forEach((t) => {
      t.onended = null
    })
    tracks.forEach((t) => t.stop())
    streamRef.current = null
    videoRef.current = null

    // Terminate OCR worker
    if (workerRef.current) {
      try {
        await workerRef.current.terminate()
      } catch {
        /* ignore */
      }
      workerRef.current = null
    }

    prevImageDataRef.current = null
    prevOcrTextRef.current = ''

    // Clear IDB session state
    try {
      await clearSessionMeta()
      await clearActiveEpisodeSnapshot()
    } catch {
      /* non-fatal */
    }

    safeSetState('stopped')
    shutdownPromiseRef.current = null
  }

  // ---------------------------------------------------------------------------
  // stopCapture — idempotent
  // ---------------------------------------------------------------------------

  const stopCapture = useCallback((): Promise<void> => {
    if (shutdownPromiseRef.current) return shutdownPromiseRef.current
    shutdownPromiseRef.current = doStop()
    return shutdownPromiseRef.current
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ---------------------------------------------------------------------------
  // startCapture
  // ---------------------------------------------------------------------------

  const startCapture = useCallback(async (): Promise<void> => {
    if (!isSupported) {
      safeSetState('capture_unavailable')
      return
    }
    if (stateRef.current === 'recording' || stateRef.current === 'stopping') return

    safeSetState('requesting')
    setSurfaceWarning(null)

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({
        video: { width: CANVAS_WIDTH, height: CANVAS_HEIGHT, frameRate: 1 },
        audio: false,
      })
    } catch {
      safeSetState('permission_denied')
      return
    }

    const track = stream.getVideoTracks()[0]
    if (!track) {
      safeSetState('error')
      return
    }

    // Surface warning if not full screen
    const settings = track.getSettings()
    if ((settings as Record<string, unknown>).displaySurface !== 'monitor') {
      if (isMountedRef.current)
        setSurfaceWarning(
          'Select "Entire Screen" for best results. Window capture may miss some activity.',
        )
    }

    // Hidden video element
    const video = document.createElement('video')
    video.muted = true
    video.playsInline = true
    video.srcObject = stream
    await video.play()
    videoRef.current = video

    // Offscreen canvas
    const canvas = document.createElement('canvas')
    canvas.width = CANVAS_WIDTH
    canvas.height = CANVAS_HEIGHT
    canvasRef.current = canvas
    canvasCtxRef.current = canvas.getContext('2d')!

    // Session state
    const sid = crypto.randomUUID()
    sessionIdRef.current = sid
    sessionSeqRef.current++
    engineRef.current.reset()
    prevImageDataRef.current = null
    prevOcrTextRef.current = ''
    prevMeaningfulOcrRef.current = ''
    lastAnalysisAtRef.current = 0
    pendingAnalysisCountRef.current = 0
    streamRef.current = stream

    // track.onended — null it before stopping to avoid re-triggering shutdown
    track.onended = () => {
      stopCapture()
    }

    // Persist session meta
    try {
      await setSessionMeta({
        sessionId: sid,
        startedAt: new Date().toISOString(),
        lastFrameAt: '',
        lastMeaningfulAt: null,
      })
    } catch {
      /* non-fatal */
    }

    // Load OCR worker
    safeSetState('loading_ocr')
    try {
      await ensureWorker()
    } catch {
      safeSetState('error')
      stream.getTracks().forEach((t) => t.stop())
      return
    }

    safeSetState('recording')
    startTimeRef.current = Date.now()
    setElapsedSeconds(0)

    elapsedTimerRef.current = setInterval(() => {
      if (isMountedRef.current)
        setElapsedSeconds(Math.floor((Date.now() - startTimeRef.current) / 1000))
    }, 1000)

    schedulerRef.current = setInterval(() => {
      scheduleTick()
    }, FRAME_INTERVAL_MS)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stopCapture])

  // ---------------------------------------------------------------------------
  // Page lifecycle effect
  // ---------------------------------------------------------------------------

  useEffect(() => {
    isMountedRef.current = true

    const handlePageHide = () => {
      // Best-effort — IDB is already persisted after each meaningful frame.
      // Cannot reliably await async on pagehide.
    }

    const handleOnline = () => {
      drainSyncQueue()
        .then((result) => {
          if (isMountedRef.current) updateSyncUI(result)
        })
        .catch(() => {})
    }

    window.addEventListener('pagehide', handlePageHide)
    window.addEventListener('online', handleOnline)

    return () => {
      isMountedRef.current = false
      window.removeEventListener('pagehide', handlePageHide)
      window.removeEventListener('online', handleOnline)
      // Best-effort stop on unmount
      if (
        shutdownPromiseRef.current === null &&
        (stateRef.current === 'recording' || stateRef.current === 'loading_ocr')
      ) {
        stopCapture().catch(() => {})
      }
    }
  }, []) // run once on mount — stopCapture is stable

  // ---------------------------------------------------------------------------
  // Return
  // ---------------------------------------------------------------------------

  return {
    state,
    elapsedSeconds,
    syncStatus,
    queuedCount,
    permanentlyFailedCount,
    surfaceWarning,
    analysisBacklogged,
    startCapture,
    stopCapture,
    isSupported,
  }
}
