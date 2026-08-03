'use client'

import { useState } from 'react'
import type { Episode } from '@/lib/types'

type Props = {
  onEpisodeSaved: (ep: Episode) => void
}

type WorkType = 'project' | 'administrative'

function todayLocal(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export default function ManualEntryForm({ onEpisodeSaved }: Props) {
  const [expanded, setExpanded] = useState(false)

  // Form fields
  const [caseName, setCaseName] = useState('')
  const [workType, setWorkType] = useState<WorkType>('project')
  const [issue, setIssue] = useState('')
  const [taskDescription, setTaskDescription] = useState('')
  const [notes, setNotes] = useState('')
  const [date, setDate] = useState(todayLocal)
  const [startTime, setStartTime] = useState('')
  const [endTime, setEndTime] = useState('')
  const [reportable, setReportable] = useState(true)

  // UI state
  const [submitting, setSubmitting] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  function reset() {
    setCaseName('')
    setWorkType('project')
    setIssue('')
    setTaskDescription('')
    setNotes('')
    setDate(todayLocal())
    setStartTime('')
    setEndTime('')
    setReportable(true)
    setServerError(null)
    setFieldErrors({})
  }

  function validate(): Record<string, string> {
    const errors: Record<string, string> = {}
    if (!caseName.trim()) errors.caseName = 'Project title is required.'
    if (!taskDescription.trim()) errors.taskDescription = 'Task description is required.'
    if (!date) errors.date = 'Date is required.'
    if (!startTime) errors.startTime = 'Start time is required.'
    if (!endTime) errors.endTime = 'End time is required.'
    if (date && startTime && endTime) {
      const start = new Date(`${date}T${startTime}:00`)
      const end = new Date(`${date}T${endTime}:00`)
      if (end <= start) {
        errors.endTime = 'End time must be after start time.'
      }
    }
    return errors
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setServerError(null)
    const errors = validate()
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) return

    setSubmitting(true)
    try {
      const res = await fetch('/api/episodes/manual', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          case_name: caseName.trim(),
          work_type: workType,
          issue_worked_on: issue.trim() || null,
          task_description: taskDescription.trim(),
          notes: notes.trim() || null,
          started_at: new Date(`${date}T${startTime}:00`).toISOString(),
          ended_at: new Date(`${date}T${endTime}:00`).toISOString(),
          is_reportable: reportable,
        }),
      })
      const json = await res.json()
      if (!res.ok) {
        setServerError(json?.error ?? `Error ${res.status}`)
        return
      }
      onEpisodeSaved(json.episode)
      reset()
      setExpanded(false)
    } catch (err: unknown) {
      setServerError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setSubmitting(false)
    }
  }

  if (!expanded) {
    return (
      <div className="border border-neutral-200 rounded-xl p-5 mb-6">
        <button
          onClick={() => setExpanded(true)}
          className="text-sm text-neutral-500 hover:text-neutral-900 transition-colors"
        >
          + Add manual entry
        </button>
      </div>
    )
  }

  return (
    <div className="border border-neutral-200 rounded-xl p-5 mb-6">
      <div className="flex items-center justify-between mb-4">
        <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400">
          Manual Entry
        </p>
        <button
          onClick={() => { setExpanded(false); reset() }}
          className="text-xs text-neutral-400 hover:text-neutral-700 transition-colors"
        >
          Cancel
        </button>
      </div>

      <form onSubmit={handleSubmit} noValidate className="space-y-3">
        {/* Project title */}
        <div>
          <label className="block text-xs text-neutral-500 mb-1">
            Project title <span className="text-red-400">*</span>
          </label>
          <input
            type="text"
            value={caseName}
            onChange={(e) => setCaseName(e.target.value)}
            className="w-full text-sm border border-neutral-200 rounded px-2.5 py-1.5 text-neutral-800
                       focus:outline-none focus:ring-1 focus:ring-neutral-400"
          />
          {fieldErrors.caseName && (
            <p className="mt-1 text-xs text-red-500">{fieldErrors.caseName}</p>
          )}
        </div>

        {/* Work type */}
        <div>
          <label className="block text-xs text-neutral-500 mb-1">Work type</label>
          <select
            value={workType}
            onChange={(e) => setWorkType(e.target.value as WorkType)}
            className="w-full text-sm border border-neutral-200 rounded px-2.5 py-1.5 text-neutral-800
                       focus:outline-none focus:ring-1 focus:ring-neutral-400 bg-white"
          >
            <option value="project">Project work</option>
            <option value="administrative">Administrative</option>
          </select>
        </div>

        {/* Issue worked on */}
        <div>
          <label className="block text-xs text-neutral-500 mb-1">Issue worked on</label>
          <input
            type="text"
            value={issue}
            onChange={(e) => setIssue(e.target.value)}
            className="w-full text-sm border border-neutral-200 rounded px-2.5 py-1.5 text-neutral-800
                       focus:outline-none focus:ring-1 focus:ring-neutral-400"
          />
        </div>

        {/* Task description */}
        <div>
          <label className="block text-xs text-neutral-500 mb-1">
            Task description <span className="text-red-400">*</span>
          </label>
          <textarea
            value={taskDescription}
            onChange={(e) => setTaskDescription(e.target.value)}
            placeholder="What specific work was done?"
            rows={3}
            className="w-full text-sm border border-neutral-200 rounded px-2.5 py-1.5 text-neutral-800
                       focus:outline-none focus:ring-1 focus:ring-neutral-400 resize-y"
          />
          {fieldErrors.taskDescription && (
            <p className="mt-1 text-xs text-red-500">{fieldErrors.taskDescription}</p>
          )}
        </div>

        {/* Notes */}
        <div>
          <label className="block text-xs text-neutral-500 mb-1">Notes</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className="w-full text-sm border border-neutral-200 rounded px-2.5 py-1.5 text-neutral-800
                       focus:outline-none focus:ring-1 focus:ring-neutral-400 resize-y"
          />
        </div>

        {/* Date */}
        <div>
          <label className="block text-xs text-neutral-500 mb-1">
            Date <span className="text-red-400">*</span>
          </label>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="text-sm border border-neutral-200 rounded px-2.5 py-1.5 text-neutral-800
                       focus:outline-none focus:ring-1 focus:ring-neutral-400"
          />
          {fieldErrors.date && (
            <p className="mt-1 text-xs text-red-500">{fieldErrors.date}</p>
          )}
        </div>

        {/* Time range */}
        <div className="flex gap-3 flex-wrap">
          <div>
            <label className="block text-xs text-neutral-500 mb-1">
              Start time <span className="text-red-400">*</span>
            </label>
            <input
              type="time"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              className="text-sm border border-neutral-200 rounded px-2.5 py-1.5 text-neutral-800
                         focus:outline-none focus:ring-1 focus:ring-neutral-400"
            />
            {fieldErrors.startTime && (
              <p className="mt-1 text-xs text-red-500">{fieldErrors.startTime}</p>
            )}
          </div>
          <div>
            <label className="block text-xs text-neutral-500 mb-1">
              End time <span className="text-red-400">*</span>
            </label>
            <input
              type="time"
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
              className="text-sm border border-neutral-200 rounded px-2.5 py-1.5 text-neutral-800
                         focus:outline-none focus:ring-1 focus:ring-neutral-400"
            />
            {fieldErrors.endTime && (
              <p className="mt-1 text-xs text-red-500">{fieldErrors.endTime}</p>
            )}
          </div>
        </div>

        {/* Reportable */}
        <div className="flex items-center gap-2">
          <input
            id="reportable"
            type="checkbox"
            checked={reportable}
            onChange={(e) => setReportable(e.target.checked)}
            className="rounded border-neutral-300"
          />
          <label htmlFor="reportable" className="text-xs text-neutral-600">
            Reportable
          </label>
        </div>

        {serverError && (
          <p className="text-xs text-red-500">{serverError}</p>
        )}

        <div className="pt-1">
          <button
            type="submit"
            disabled={submitting}
            className="text-sm font-medium bg-neutral-900 text-white px-4 py-1.5 rounded
                       hover:bg-neutral-700 transition-colors disabled:opacity-40"
          >
            {submitting ? 'Saving\u2026' : 'Save Entry'}
          </button>
        </div>
      </form>
    </div>
  )
}
