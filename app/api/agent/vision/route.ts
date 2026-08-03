import { createHash } from 'crypto'
import type { NextRequest } from 'next/server'
import Anthropic from '@anthropic-ai/sdk'
import { getAdminClient } from '@/lib/supabase-admin'

// Maximum accepted base64 payload size: 4 MB (≈ 3 MB raw image).
// The agent compresses to 3 MB, so this guard catches bypasses or bugs.
const SERVER_MAX_B64_BYTES = 4 * 1024 * 1024

// Anthropic call timeout in milliseconds
const PROVIDER_TIMEOUT_MS = 20_000

const REQUIRED_FIELDS = [
  'meaningful',
  'personal_or_irrelevant',
  'activity_description',
  'objective',
  'entities',
  'actions',
  'continue_current_episode',
  'start_new_episode',
  'suggested_episode_name',
  'supporting_evidence',
]

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

type VisionContext = {
  current_episode_name?: string
  current_objective?: string
  episode_duration_minutes?: number
  recent_actions?: (string | string[])[]
  known_entities?: string[]
}

function buildContent(
  b64: string,
  context: VisionContext,
  appContext: string,
): Anthropic.MessageParam['content'] {
  const currentEp = context.current_episode_name ?? ''
  const currentObj = context.current_objective ?? ''
  const duration = context.episode_duration_minutes ?? 0
  const recentActions = context.recent_actions ?? []
  const knownEntities = context.known_entities ?? []

  let contextBlock = ''
  if (currentEp) {
    contextBlock =
      `\nCurrent episode: ${currentEp}\n` +
      `Current objective: ${currentObj}\n` +
      `Duration so far: ${Math.round(duration)} minutes\n`

    const flat: string[] = []
    for (const item of recentActions) {
      if (Array.isArray(item)) flat.push(...item)
      else if (item) flat.push(item)
    }
    if (flat.length > 0) contextBlock += `Recent actions: ${flat.slice(-6).join('; ')}\n`
    if (knownEntities.length > 0)
      contextBlock += `Known entities: ${knownEntities.slice(0, 10).join(', ')}\n`
  }

  const prompt =
    `You are analyzing a screenshot to determine what work is being done.\n` +
    `App context: ${appContext}${contextBlock}\n\n` +
    `Analyze the screenshot carefully and respond with ONLY valid JSON matching this exact schema:\n\n` +
    `{\n` +
    `  "meaningful": true,\n` +
    `  "personal_or_irrelevant": false,\n` +
    `  "activity_description": "Specific description of what is visible and what work is being done",\n` +
    `  "objective": "What the user is trying to accomplish overall",\n` +
    `  "entities": [{"name": "EntityName", "type": "project|client|case|person|company|tool", "evidence_strength": "strong|moderate|weak"}],\n` +
    `  "actions": ["Specific action 1", "Specific action 2"],\n` +
    `  "continue_current_episode": true,\n` +
    `  "start_new_episode": false,\n` +
    `  "suggested_episode_name": "Descriptive Name — Specific Task",\n` +
    `  "supporting_evidence": ["Visual evidence item 1", "Visual evidence item 2"]\n` +
    `}\n\n` +
    `Rules for meaningful:\n` +
    `- Set meaningful=false for: loading screens, blank screens, idle desktops, screensavers, ` +
    `login prompts, menus with no work context, reset states\n` +
    `- Set meaningful=true for any actual work activity\n\n` +
    `Rules for personal_or_irrelevant:\n` +
    `- Set personal_or_irrelevant=true ONLY for clearly non-work activity (entertainment, ` +
    `personal social media browsing unrelated to work)\n` +
    `- Do NOT set personal_or_irrelevant=true for: email, scheduling, admin tasks, ` +
    `research, meetings, overhead work\n\n` +
    `Rules for episode boundaries:\n` +
    `- continue_current_episode=true when work relates to the same objective — switching ` +
    `apps does NOT split episodes (GitHub → terminal → Vercel → Supabase for the same project is ONE episode)\n` +
    `- start_new_episode=true ONLY when the objective has clearly shifted to unrelated work\n` +
    `- continue_current_episode and start_new_episode must NOT both be true\n\n` +
    `Rules for suggested_episode_name:\n` +
    `- Must be specific and descriptive: "BuildHarvey — Deployment Debugging" NOT just "BuildHarvey"\n` +
    `- Must NOT be empty or a placeholder if meaningful=true\n` +
    `- Must NOT be empty if start_new_episode=true\n\n` +
    `Respond with ONLY the JSON object. No explanation, no markdown.`

  return [
    { type: 'text', text: prompt },
    {
      type: 'image',
      source: { type: 'base64', media_type: 'image/jpeg', data: b64 },
    },
  ]
}

function validateEvidence(data: Record<string, unknown>): string | null {
  for (const f of REQUIRED_FIELDS) {
    if (!(f in data)) return `missing field '${f}'`
  }
  if (typeof data.meaningful !== 'boolean') return 'meaningful must be bool'
  if (typeof data.personal_or_irrelevant !== 'boolean') return 'personal_or_irrelevant must be bool'
  if (typeof data.continue_current_episode !== 'boolean')
    return 'continue_current_episode must be bool'
  if (typeof data.start_new_episode !== 'boolean') return 'start_new_episode must be bool'
  if (!Array.isArray(data.entities)) return 'entities must be list'
  if (!Array.isArray(data.actions)) return 'actions must be list'
  if (!Array.isArray(data.supporting_evidence)) return 'supporting_evidence must be list'
  if (data.continue_current_episode && data.start_new_episode)
    return 'continue_current_episode and start_new_episode are both true'
  if (!data.meaningful && Array.isArray(data.actions) && data.actions.length > 0)
    return 'meaningful=false but actions is non-empty'
  if (data.meaningful) {
    if (!String(data.objective ?? '').trim()) return 'meaningful=true but objective is empty'
    if (!String(data.suggested_episode_name ?? '').trim())
      return 'meaningful=true but suggested_episode_name is empty'
  }
  if (data.start_new_episode) {
    if (!String(data.suggested_episode_name ?? '').trim())
      return 'start_new_episode=true but suggested_episode_name is empty'
  }
  return null
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
    console.error('[agent/vision] ANTHROPIC_CAPTURE_MODEL not configured')
    return Response.json({ success: false, error: 'server_misconfigured' }, { status: 500 })
  }

  // 3. Parse body
  let body: { screenshot_b64?: unknown; context?: VisionContext; app_context?: string }
  try {
    body = await request.json()
  } catch {
    return Response.json({ success: false, error: 'invalid_request' }, { status: 400 })
  }

  const b64 = body.screenshot_b64
  if (!b64 || typeof b64 !== 'string') {
    return Response.json({ success: false, error: 'invalid_request' }, { status: 400 })
  }

  // 4. Payload size guard
  if (b64.length > SERVER_MAX_B64_BYTES) {
    return Response.json({ success: false, error: 'payload_too_large' }, { status: 413 })
  }

  const context = body.context ?? {}
  const appContext = body.app_context ?? 'Unknown'

  // 5. Anthropic call with timeout
  const client = new Anthropic()
  let msg: Anthropic.Message
  try {
    const apiPromise = client.messages.create({
      model,
      max_tokens: 512,
      messages: [{ role: 'user', content: buildContent(b64, context, appContext) }],
    })
    const timeoutPromise = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error('timeout')), PROVIDER_TIMEOUT_MS),
    )
    msg = await Promise.race([apiPromise, timeoutPromise])
  } catch (err) {
    if (err instanceof Error && err.message === 'timeout') {
      console.error('[agent/vision] provider timeout after', PROVIDER_TIMEOUT_MS, 'ms')
      return Response.json({ success: false, error: 'provider_timeout' }, { status: 504 })
    }
    // Log error type only — no customer content in logs
    console.error('[agent/vision] provider error:', (err as Error)?.name ?? 'unknown')
    return Response.json({ success: false, error: 'provider_error' }, { status: 502 })
  }

  // 6. Parse response
  const firstBlock = msg.content[0]
  if (!firstBlock || firstBlock.type !== 'text') {
    console.warn('[agent/vision] unexpected response shape')
    return Response.json({ success: false, error: 'invalid_model_response' }, { status: 502 })
  }

  let rawText = firstBlock.text.trim()
  if (rawText.startsWith('```')) {
    const parts = rawText.split('```')
    if (parts.length >= 2) {
      rawText = parts[1]
      if (rawText.startsWith('json')) rawText = rawText.slice(4)
      rawText = rawText.trim()
    }
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(rawText)
  } catch {
    console.warn('[agent/vision] model returned non-JSON')
    return Response.json({ success: false, error: 'invalid_model_response' }, { status: 502 })
  }

  if (typeof parsed !== 'object' || parsed === null) {
    return Response.json({ success: false, error: 'invalid_model_response' }, { status: 502 })
  }

  const data = parsed as Record<string, unknown>
  const validationError = validateEvidence(data)
  if (validationError) {
    console.warn('[agent/vision] schema validation failed:', validationError)
    return Response.json({ success: false, error: 'invalid_model_response' }, { status: 502 })
  }

  return Response.json({
    success: true,
    evidence: {
      meaningful: data.meaningful,
      personal_or_irrelevant: data.personal_or_irrelevant,
      activity_description: data.activity_description,
      objective: data.objective,
      entities: data.entities,
      actions: data.actions,
      continue_current_episode: data.continue_current_episode,
      start_new_episode: data.start_new_episode,
      suggested_episode_name: data.suggested_episode_name,
      supporting_evidence: data.supporting_evidence,
      input_tokens: msg.usage.input_tokens,
      output_tokens: msg.usage.output_tokens,
      model: msg.model,
    },
  })
}
