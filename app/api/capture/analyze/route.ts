import { NextRequest } from 'next/server'
import Anthropic from '@anthropic-ai/sdk'
import { getServerClient } from '@/lib/supabase-server'
import { rateLimit } from '@/lib/rate-limit'
import type { KeyObservation } from '@/lib/types'

type EpisodeContext = {
  title: string
  work_type: string
  started_at: string
  recent_observations: KeyObservation[]
  time_since_last_meaningful_seconds: number | null
} | null

type AnalyzeBody = {
  ocr_text?: string
  prev_ocr_text?: string
  timestamp?: string
  episode_context?: EpisodeContext
}

type AnalyzeResult = {
  meaningful: boolean
  work_type: 'project' | 'administrative' | 'not_work'
  task_description: string | null
  issue_worked_on: string | null
  episode_action: 'continue' | 'end_and_start' | 'end'
  suggested_episode_name: string | null
}

function buildPrompt(
  ocr_text: string,
  prev_ocr_text: string,
  timestamp: string,
  episode_context: EpisodeContext
): string {
  const contextBlock = episode_context
    ? `CURRENT EPISODE:
- Title: "${episode_context.title}"
- Type: ${episode_context.work_type}
- Started: ${episode_context.started_at}
- Recent activity:
${episode_context.recent_observations.map((o) => `  ${o.timestamp} — ${o.text}`).join('\n')}
- Seconds since last activity: ${episode_context.time_since_last_meaningful_seconds ?? 'unknown'}`
    : `No Episode is currently open.`

  return `You are BuildHarvey, tracking professional work activity from screen capture.

CURRENT SCREEN TEXT (OCR):
<current>
${ocr_text}
</current>

PREVIOUS SCREEN TEXT:
<previous>
${prev_ocr_text}
</previous>

TIMESTAMP: ${timestamp}

${contextBlock}

Respond with ONLY valid JSON, no markdown:
{
  "meaningful": true,
  "work_type": "project",
  "task_description": "Drafted motion to compel discovery, Peterson v. Ortega",
  "issue_worked_on": "Case No. 24-CV-1234",
  "episode_action": "continue",
  "suggested_episode_name": "Peterson v. Ortega"
}

Rules:
- meaningful: false for lock screens, idle browsers, screensavers, personal/entertainment content, blank screens, this app's own UI, file pickers, notification popups.
- work_type: "project" = client/case/matter work; "administrative" = firm overhead, billing, calendaring, HR, training, internal email; "not_work" = personal, entertainment, idle.
- If meaningful is false: set work_type="not_work", task_description=null, issue_worked_on=null, episode_action="continue", suggested_episode_name=null.
- episode_action: "continue" (same subject), "end_and_start" (confident switch to distinctly different matter), "end" (work clearly stopped).
- suggested_episode_name: specific name from visible text only. Never: "Legal Work", "Case Management", "Document Review", "Miscellaneous", "General Work".
- task_description: specific. "Drafted motion to compel" not "Worked on document". Null if not meaningful.
- Do not calculate durations or mention timestamps.`
}

function validateResult(raw: unknown): AnalyzeResult {
  if (typeof raw !== 'object' || raw === null) throw new Error('invalid shape')
  const r = raw as Record<string, unknown>

  if (typeof r.meaningful !== 'boolean') throw new Error('invalid shape')
  if (!['project', 'administrative', 'not_work'].includes(r.work_type as string))
    throw new Error('invalid work_type')
  if (!['continue', 'end_and_start', 'end'].includes(r.episode_action as string))
    throw new Error('invalid episode_action')
  if (r.meaningful && !r.task_description) throw new Error('missing task_description')

  return {
    meaningful: r.meaningful,
    work_type: r.work_type as AnalyzeResult['work_type'],
    task_description: (r.task_description as string | null | undefined) ?? null,
    issue_worked_on: (r.issue_worked_on as string | null | undefined) ?? null,
    episode_action: r.episode_action as AnalyzeResult['episode_action'],
    suggested_episode_name: (r.suggested_episode_name as string | null | undefined) ?? null,
  }
}

export async function POST(request: NextRequest) {
  const supabase = await getServerClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const over = await rateLimit(`capture:${user.id}`, 240, 3600)
  if (over) {
    return Response.json({ error: 'rate_limited' }, { status: 429 })
  }

  const model = process.env.ANTHROPIC_CAPTURE_MODEL
  if (!model) {
    return Response.json({ error: 'server_misconfigured' }, { status: 500 })
  }

  let body: AnalyzeBody
  try {
    body = (await request.json()) as AnalyzeBody
  } catch {
    return Response.json({ error: 'Invalid JSON' }, { status: 400 })
  }

  const ocr_text = body.ocr_text ?? ''
  const prev_ocr_text = body.prev_ocr_text ?? ''
  const timestamp = body.timestamp ?? new Date().toISOString()
  const episode_context = body.episode_context ?? null

  const promptText = buildPrompt(ocr_text, prev_ocr_text, timestamp, episode_context)

  try {
    const client = new Anthropic()

    const msgPromise = client.messages.create({
      model,
      max_tokens: 512,
      messages: [{ role: 'user', content: promptText }],
    })

    const timeoutPromise = new Promise<never>((_, reject) => {
      const id = setTimeout(() => {
        clearTimeout(id)
        reject(new Error('timeout'))
      }, 10_000)
    })

    let msg: Anthropic.Message
    try {
      msg = await Promise.race([msgPromise, timeoutPromise])
    } catch (err) {
      const isTimeout =
        err instanceof Error && err.message === 'timeout'
      if (isTimeout) {
        return Response.json({ error: 'timeout' }, { status: 504 })
      }
      throw err
    }

    const firstBlock = msg.content[0]
    if (!firstBlock || firstBlock.type !== 'text') {
      return Response.json({ error: 'parse_error' }, { status: 500 })
    }

    let rawText = firstBlock.text.trim()
    // Strip markdown fences if present
    rawText = rawText.replace(/^```(?:json)?\s*/i, '').replace(/\s*```\s*$/, '')

    let parsed: unknown
    try {
      parsed = JSON.parse(rawText)
    } catch {
      return Response.json({ error: 'parse_error' }, { status: 500 })
    }

    let result: AnalyzeResult
    try {
      result = validateResult(parsed)
    } catch (err) {
      return Response.json({ error: 'parse_error' }, { status: 500 })
    }

    return Response.json(result)
  } catch (err) {
    const message = err instanceof Error ? err.message : 'unknown error'
    return Response.json({ error: message }, { status: 500 })
  }
}
