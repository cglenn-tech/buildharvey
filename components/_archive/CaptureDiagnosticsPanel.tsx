'use client'

import { useState } from 'react'
import type { CaptureDiagnostics } from '@/lib/capture/capture-session'

type TestResult = {
  status: number
  body: unknown
} | null

type Props = {
  diagnostics: CaptureDiagnostics
}

export default function CaptureDiagnosticsPanel({ diagnostics: diag }: Props) {
  const [analyzeResult, setAnalyzeResult] = useState<TestResult>(null)
  const [analyzeRunning, setAnalyzeRunning] = useState(false)
  const [episodeResult, setEpisodeResult] = useState<TestResult>(null)
  const [episodeRunning, setEpisodeRunning] = useState(false)

  async function testAnalyze() {
    setAnalyzeRunning(true)
    setAnalyzeResult(null)
    try {
      const res = await fetch('/api/capture/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ocr_text: 'Martinez Valuation — reviewing real estate appraisal adjustments',
          prev_ocr_text: '',
          timestamp: new Date().toISOString(),
          episode_context: null,
        }),
      })
      const body = await res.json().catch(() => null)
      setAnalyzeResult({ status: res.status, body })
    } catch (err) {
      setAnalyzeResult({ status: 0, body: String(err) })
    } finally {
      setAnalyzeRunning(false)
    }
  }

  async function testEpisodeSave() {
    setEpisodeRunning(true)
    setEpisodeResult(null)
    const testId = crypto.randomUUID()
    const now = new Date().toISOString()
    const episode = {
      id: testId,
      case_name: '[BuildHarvey Diagnostic Test Episode]',
      work_type: 'project' as const,
      issue_worked_on: null,
      started_at: now,
      ended_at: now,
      duration_minutes: 0,
      key_observations: [],
      created_at: now,
      is_reportable: false,
    }
    try {
      const saveRes = await fetch('/api/episodes/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(episode),
      })
      const saveBody = await saveRes.json().catch(() => null)
      if (saveRes.ok) {
        // Clean up test episode
        await fetch(`/api/episodes/${testId}`, { method: 'DELETE' }).catch(() => {})
      }
      setEpisodeResult({ status: saveRes.status, body: saveBody })
    } catch (err) {
      setEpisodeResult({ status: 0, body: String(err) })
    } finally {
      setEpisodeRunning(false)
    }
  }

  const rows: [string, string][] = [
    ['streamStatus', diag.streamStatus],
    ['videoReadyState', String(diag.videoReadyState)],
    ['videoWidth × height', `${diag.videoWidth} × ${diag.videoHeight}`],
    ['framesSampled', String(diag.framesSampled)],
    ['framesSkippedByDiff', String(diag.framesSkippedByDiff)],
    ['lastFrameAt', diag.lastFrameAt ?? '—'],
    ['blobsCreated', String(diag.blobsCreated)],
    ['lastBlobSizeBytes', diag.lastBlobSizeBytes ? `${(diag.lastBlobSizeBytes / 1024).toFixed(1)} KB` : '—'],
    ['ocrWorkerStatus', diag.ocrWorkerStatus],
    ['ocrAttempts', String(diag.ocrAttempts)],
    ['ocrSuccesses', String(diag.ocrSuccesses)],
    ['ocrFailures', String(diag.ocrFailures)],
    ['latestOcrCharCount', String(diag.latestOcrCharCount)],
    ['latestOcrPreview', diag.latestOcrPreview ? `"${diag.latestOcrPreview.slice(0, 80)}…"` : '—'],
    ['analyzeAttempts', String(diag.analyzeAttempts)],
    ['lastAnalyzeHttpStatus', diag.lastAnalyzeHttpStatus !== null ? String(diag.lastAnalyzeHttpStatus) : '—'],
    ['episodesOpened', String(diag.episodesOpened)],
    ['episodesFinalized', String(diag.episodesFinalized)],
    ['episodesSaved', String(diag.episodesSaved)],
    ['queuedEpisodes', String(diag.queuedEpisodes)],
    ['lastPipelineError', diag.lastPipelineError ? `[${diag.lastPipelineError.stage}] ${diag.lastPipelineError.error}` : '—'],
  ]

  return (
    <div className="border border-amber-300 bg-amber-50 rounded-xl p-4 mb-4 text-xs font-mono">
      <div className="font-semibold text-amber-800 mb-2">Capture Diagnostics</div>

      <table className="w-full border-collapse mb-3">
        <tbody>
          {rows.map(([key, val]) => (
            <tr key={key} className="border-b border-amber-200">
              <td className="py-0.5 pr-4 text-amber-700 whitespace-nowrap align-top">{key}</td>
              <td className="py-0.5 text-neutral-800 break-all">{val}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {diag.thumbnailDataUrl && (
        <div className="mb-3">
          <div className="text-amber-700 mb-1">thumbnail</div>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={diag.thumbnailDataUrl}
            alt="latest capture frame"
            className="max-w-full border border-amber-200 rounded"
            style={{ maxHeight: 120 }}
          />
        </div>
      )}

      <div className="flex flex-wrap gap-2 mt-2">
        <button
          onClick={testAnalyze}
          disabled={analyzeRunning}
          className="px-3 py-1 bg-amber-200 hover:bg-amber-300 text-amber-900 rounded disabled:opacity-50"
        >
          {analyzeRunning ? 'Testing…' : 'Test analysis with sample text'}
        </button>
        <button
          onClick={testEpisodeSave}
          disabled={episodeRunning}
          className="px-3 py-1 bg-amber-200 hover:bg-amber-300 text-amber-900 rounded disabled:opacity-50"
        >
          {episodeRunning ? 'Testing…' : 'Test episode save'}
        </button>
      </div>

      {analyzeResult && (
        <pre className="mt-2 p-2 bg-white border border-amber-200 rounded text-xs overflow-x-auto whitespace-pre-wrap">
          {`HTTP ${analyzeResult.status}\n${JSON.stringify(analyzeResult.body, null, 2)}`}
        </pre>
      )}
      {episodeResult && (
        <pre className="mt-2 p-2 bg-white border border-amber-200 rounded text-xs overflow-x-auto whitespace-pre-wrap">
          {`HTTP ${episodeResult.status}\n${JSON.stringify(episodeResult.body, null, 2)}`}
        </pre>
      )}
    </div>
  )
}
