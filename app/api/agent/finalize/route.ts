import { createHash } from 'crypto'
import type { NextRequest } from 'next/server'
import Anthropic from '@anthropic-ai/sdk'
import { getAdminClient } from '@/lib/supabase-admin'

const MAX_KEY_OBSERVATIONS = 8
const PROVIDER_TIMEOUT_MS = 25_000

async function getDeviceFromToken(authHeader: string | null) {
  if (!authHeader?.startsWith('Bearer ')) return null
  const rawToken = authHeader.slice(7)
  const tokenHash = createHash('sha256').update(rawToken).digest('hex')

  const admin = getAdminClient()
  const { data: device } = await admin
    .from('devices')
    .select('id, user_id')
    .eq('token_hash', tokenHash)
    .is('revoked_at', null)
    .single()

  if (!device) return null

  // Fire-and-forget last_seen_at update
  admin.from('devices').update({ last_seen_at: new Date().toISOString() }).eq('id', device.id)

  return device
}

type EvidenceItem = {
  timestamp?: string
  app_context?: string
  activity_description?: string
  objective?: string
  actions?: string[]
  entities?: { name?: string; type?: string; evidence_strength?: string }[]
  supporting_evidence?: string[]
}

type FinalizeBody = {
  episode_name?: string
  episode_objective?: string
  started_at?: string
  ended_at?: string
  duration_minutes?: number
  evidence_items?: EvidenceItem[]
  activity_log?: string
}

function formatEvidence(items: EvidenceItem[]): string {
  const lines: string[] = []
  items.forEach((ev, i) => {
    lines.push(`[${i + 1}] ${ev.timestamp ?? ''} | ${ev.app_context ?? ''}`)
    if (ev.activity_description) lines.push(`  Activity: ${ev.activity_description}`)
    if (ev.objective) lines.push(`  Objective: ${ev.objective}`)
    if (ev.actions?.length) lines.push(`  Actions: ${ev.actions.join('; ')}`)
    if (ev.entities?.length) {
      const strs = ev.entities.map(
        (e) => `${e.name ?? '?'} (${e.type ?? '?'}, ${e.evidence_strength ?? '?'})`,
      )
      lines.push(`  Entities: ${strs.join(', ')}`)
    }
    if (ev.supporting_evidence?.length)
      lines.push(`  Evidence: ${ev.supporting_evidence.join('; ')}`)
    lines.push('')
  })
  return lines.join('\n')
}

function synthesisInstructions(): string {
  return (
    `\nWrite up to ${MAX_KEY_OBSERVATIONS} observations that reconstruct the actual work. ` +
    `These will be read as memories one week later.\n\n` +
    `SYNTHESIZE related activity into single observations:\n` +
    `  Good: "Researched luxury hotel options in New York across multiple sources while evaluating relocation costs"\n` +
    `  Bad: "Visited YouTube" / "Visited Aman NYC" / "Searched Google Hotels"\n\n` +
    `DESCRIBE THE WORK, not the tool:\n` +
    `  Good: "Reviewed coverage dispute section of the Smith claim file"\n` +
    `  Bad: "Opened PDF in Preview" / "Used Microsoft Word"\n\n` +
    `CONNECT DELAYED CONTEXT — if a name, project, or subject appears later and clearly explains ` +
    `earlier activity, tie them together.\n\n` +
    `BE SPECIFIC about what was visible: document names, people, companies, topics, amounts, ` +
    `decisions, problems being solved.\n\n` +
    `Return ONLY a JSON array with no surrounding text:\n` +
    `[{"timestamp": "HH:MM", "text": "..."}]`
  )
}

function buildEvidencePrompt(body: FinalizeBody): string {
  const duration = body.duration_minutes ?? 0
  const evidenceText = formatEvidence(body.evidence_items!)
  return (
    `You are an experienced executive assistant synthesizing a work session ` +
    `from structured analysis notes.\n\n` +
    `Work subject: ${body.episode_name ?? ''}\n` +
    `Objective: ${body.episode_objective ?? ''}\n` +
    `Session: ${body.started_at ?? ''} → ${body.ended_at ?? ''} (${Math.round(duration)} minutes)\n\n` +
    `The following are structured observations from ${body.evidence_items!.length} screenshots:\n\n` +
    `${evidenceText}\n` +
    synthesisInstructions()
  )
}

function buildActivityLogPrompt(body: FinalizeBody): string {
  const duration = body.duration_minutes ?? 0
  return (
    `You are an experienced executive assistant reconstructing a work session ` +
    `from activity metadata.\n\n` +
    `Work subject: ${body.episode_name ?? ''}\n` +
    `Session: ${body.started_at ?? ''} → ${body.ended_at ?? ''} (${Math.round(duration)} minutes)\n\n` +
    `Activity log (timestamp | app | window/url/file | entities):\n` +
    `${body.activity_log}\n\n` +
    `Before you write, reason through:\n` +
    `1. What was the user actually trying to accomplish overall?\n` +
    `2. What are the distinct work threads?\n` +
    `3. Does anything later in the log explain earlier activity?\n` +
    `4. Which entries can be synthesized into one meaningful memory?\n\n` +
    synthesisInstructions()
  )
}

function parseObservations(text: string): { timestamp: string; text: string }[] {
  let t = text.trim()
  if (t.startsWith('```')) {
    const parts = t.split('```')
    if (parts.length >= 2) {
      t = parts[1]
      if (t.startsWith('json')) t = t.slice(4)
      t = t.trim()
    }
  }
  const data = JSON.parse(t)
  if (!Array.isArray(data)) throw new Error('expected array')
  return data
    .filter(
      (d): d is { timestamp: string; text: string } =>
        typeof d === 'object' &&
        d !== null &&
        typeof d.timestamp === 'string' &&
        typeof d.text === 'string' &&
        d.timestamp.length > 0 &&
        d.text.length > 0,
    )
    .slice(0, MAX_KEY_OBSERVATIONS)
}

export async function POST(request: NextRequest) {
  // 1. Auth
  const device = await getDeviceFromToken(request.headers.get('authorization'))
  if (!device) {
    return Response.json({ success: false, error: 'unauthorized' }, { status: 401 })
  }

  // 2. Model configuration
  const model = process.env.ANTHROPIC_CAPTURE_MODEL
  if (!model) {
    console.error('[agent/finalize] ANTHROPIC_CAPTURE_MODEL not configured')
    return Response.json({ success: false, error: 'server_misconfigured' }, { status: 500 })
  }

  // 3. Parse body
  let body: FinalizeBody
  try {
    body = await request.json()
  } catch {
    return Response.json({ success: false, error: 'invalid_request' }, { status: 400 })
  }

  const hasEvidence = Array.isArray(body.evidence_items) && body.evidence_items.length > 0
  const hasActivityLog =
    typeof body.activity_log === 'string' && body.activity_log.trim().length > 0

  if (!hasEvidence && !hasActivityLog) {
    return Response.json({ success: false, error: 'invalid_request' }, { status: 400 })
  }

  const prompt = hasEvidence ? buildEvidencePrompt(body) : buildActivityLogPrompt(body)

  // 4. Anthropic call with timeout
  const client = new Anthropic()
  let msg: Anthropic.Message
  try {
    const apiPromise = client.messages.create({
      model,
      max_tokens: 1024,
      messages: [{ role: 'user', content: prompt }],
    })
    const timeoutPromise = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error('timeout')), PROVIDER_TIMEOUT_MS),
    )
    msg = await Promise.race([apiPromise, timeoutPromise])
  } catch (err) {
    if (err instanceof Error && err.message === 'timeout') {
      console.error('[agent/finalize] provider timeout after', PROVIDER_TIMEOUT_MS, 'ms')
      return Response.json({ success: false, error: 'provider_timeout' }, { status: 504 })
    }
    console.error('[agent/finalize] provider error:', (err as Error)?.name ?? 'unknown')
    return Response.json({ success: false, error: 'provider_error' }, { status: 502 })
  }

  // 5. Parse response
  const firstBlock = msg.content[0]
  if (!firstBlock || firstBlock.type !== 'text') {
    console.warn('[agent/finalize] unexpected response shape')
    return Response.json({ success: false, error: 'invalid_model_response' }, { status: 502 })
  }

  let observations: { timestamp: string; text: string }[]
  try {
    observations = parseObservations(firstBlock.text)
  } catch (err) {
    console.warn('[agent/finalize] model response parse failed:', (err as Error)?.message)
    return Response.json({ success: false, error: 'invalid_model_response' }, { status: 502 })
  }

  return Response.json({ success: true, observations })
}
