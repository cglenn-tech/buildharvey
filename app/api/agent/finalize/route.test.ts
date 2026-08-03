import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { NextRequest } from 'next/server'

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock('@/lib/supabase-admin', () => ({ getAdminClient: vi.fn() }))
vi.mock('@anthropic-ai/sdk', () => {
  const MockAnthropic = vi.fn()
  return { default: MockAnthropic }
})

import { getAdminClient } from '@/lib/supabase-admin'
import Anthropic from '@anthropic-ai/sdk'
import { POST } from './route'

// ── Helpers ───────────────────────────────────────────────────────────────────

const VALID_OBSERVATIONS = [
  { timestamp: '14:30', text: 'Reviewed Smith Corp contract clause 4.2' },
  { timestamp: '14:45', text: 'Flagged indemnification language for partner review' },
]

const VALID_EVIDENCE_ITEMS = [
  {
    timestamp: '14:30',
    app_context: 'Preview | contract.pdf',
    activity_description: 'Reading contract',
    objective: 'Review contract',
    actions: ['Scrolling to clause 4.2'],
    entities: [{ name: 'Smith Corp', type: 'client', evidence_strength: 'strong' }],
    supporting_evidence: ['Contract visible'],
  },
]

function makeRequest(body: unknown, authToken?: string): NextRequest {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (authToken) headers['Authorization'] = `Bearer ${authToken}`
  return new Request('http://localhost/api/agent/finalize', {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  }) as unknown as NextRequest
}

function mockValidDevice() {
  const mockUpdate = vi.fn().mockReturnValue({ eq: vi.fn().mockResolvedValue({}) })
  const mockSingle = vi.fn().mockResolvedValue({ data: { id: 'dev-1', user_id: 'usr-1' } })
  const mockIs = vi.fn().mockReturnValue({ single: mockSingle })
  const mockEq = vi.fn().mockReturnValue({ is: mockIs })
  const mockSelect = vi.fn().mockReturnValue({ eq: mockEq })
  vi.mocked(getAdminClient).mockReturnValue({
    from: vi.fn().mockImplementation((table: string) => {
      if (table === 'devices') return { select: mockSelect, update: mockUpdate }
      return { update: mockUpdate }
    }),
  } as ReturnType<typeof getAdminClient>)
}

function mockNoDevice() {
  const mockSingle = vi.fn().mockResolvedValue({ data: null })
  const mockIs = vi.fn().mockReturnValue({ single: mockSingle })
  const mockEq = vi.fn().mockReturnValue({ is: mockIs })
  const mockSelect = vi.fn().mockReturnValue({ eq: mockEq })
  vi.mocked(getAdminClient).mockReturnValue({
    from: vi.fn().mockReturnValue({ select: mockSelect }),
  } as ReturnType<typeof getAdminClient>)
}

function mockAnthropicSuccess(observations: typeof VALID_OBSERVATIONS) {
  vi.mocked(Anthropic).mockImplementation(
    () =>
      ({
        messages: {
          create: vi.fn().mockResolvedValue({
            content: [{ type: 'text', text: JSON.stringify(observations) }],
            usage: { input_tokens: 300, output_tokens: 80 },
            model: 'claude-haiku-test',
          }),
        },
      }) as unknown as Anthropic,
  )
}

function mockAnthropicError(message = 'API error', isTimeout = false) {
  vi.mocked(Anthropic).mockImplementation(
    () =>
      ({
        messages: {
          create: vi.fn().mockRejectedValue(new Error(isTimeout ? 'timeout' : message)),
        },
      }) as unknown as Anthropic,
  )
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('POST /api/agent/finalize', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    delete process.env.ANTHROPIC_CAPTURE_MODEL
  })

  // ── Auth ──────────────────────────────────────────────────────────────────

  it('returns 401 unauthorized when token is missing', async () => {
    mockNoDevice()
    const res = await POST(makeRequest({ episode_name: 'Test', evidence_items: VALID_EVIDENCE_ITEMS }))
    expect(res.status).toBe(401)
    const body = await res.json()
    expect(body).toEqual({ success: false, error: 'unauthorized' })
  })

  it('returns 401 unauthorized for invalid device token', async () => {
    mockNoDevice()
    const res = await POST(
      makeRequest({ episode_name: 'Test', evidence_items: VALID_EVIDENCE_ITEMS }, 'bad-token'),
    )
    expect(res.status).toBe(401)
    expect((await res.json()).error).toBe('unauthorized')
  })

  // ── Server configuration ──────────────────────────────────────────────────

  it('returns 500 server_misconfigured when ANTHROPIC_CAPTURE_MODEL is absent', async () => {
    mockValidDevice()
    const res = await POST(
      makeRequest({ episode_name: 'Test', evidence_items: VALID_EVIDENCE_ITEMS }, 'token'),
    )
    expect(res.status).toBe(500)
    expect((await res.json()).error).toBe('server_misconfigured')
  })

  // ── Request validation ────────────────────────────────────────────────────

  it('returns 400 invalid_request when no evidence and no activity_log', async () => {
    mockValidDevice()
    process.env.ANTHROPIC_CAPTURE_MODEL = 'claude-haiku-test'
    const res = await POST(makeRequest({ episode_name: 'Test' }, 'token'))
    expect(res.status).toBe(400)
    expect((await res.json()).error).toBe('invalid_request')
  })

  it('returns 400 invalid_request for malformed JSON body', async () => {
    mockValidDevice()
    process.env.ANTHROPIC_CAPTURE_MODEL = 'claude-haiku-test'
    const req = new Request('http://localhost/api/agent/finalize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer token' },
      body: '{broken',
    }) as unknown as NextRequest
    const res = await POST(req)
    expect(res.status).toBe(400)
    expect((await res.json()).error).toBe('invalid_request')
  })

  // ── Provider errors ───────────────────────────────────────────────────────

  it('returns 504 provider_timeout on Anthropic timeout', async () => {
    mockValidDevice()
    mockAnthropicError('Connection reset', false)
    // Simulate timeout by throwing error named 'timeout'
    vi.mocked(Anthropic).mockImplementation(
      () =>
        ({
          messages: {
            create: vi.fn().mockRejectedValue(new Error('timeout')),
          },
        }) as unknown as Anthropic,
    )
    process.env.ANTHROPIC_CAPTURE_MODEL = 'claude-haiku-test'
    const res = await POST(
      makeRequest({ episode_name: 'Test', evidence_items: VALID_EVIDENCE_ITEMS }, 'token'),
    )
    expect(res.status).toBe(504)
    expect((await res.json()).error).toBe('provider_timeout')
  })

  it('returns 502 provider_error on non-timeout Anthropic failure', async () => {
    mockValidDevice()
    mockAnthropicError('Service unavailable')
    process.env.ANTHROPIC_CAPTURE_MODEL = 'claude-haiku-test'
    const res = await POST(
      makeRequest({ episode_name: 'Test', evidence_items: VALID_EVIDENCE_ITEMS }, 'token'),
    )
    expect(res.status).toBe(502)
    expect((await res.json()).error).toBe('provider_error')
  })

  it('returns 502 invalid_model_response when Claude returns non-JSON array', async () => {
    mockAnthropicSuccess([] as typeof VALID_OBSERVATIONS)
    vi.mocked(Anthropic).mockImplementation(
      () =>
        ({
          messages: {
            create: vi.fn().mockResolvedValue({
              content: [{ type: 'text', text: 'Here are my observations:' }],
              usage: { input_tokens: 10, output_tokens: 5 },
              model: 'claude-haiku-test',
            }),
          },
        }) as unknown as Anthropic,
    )
    mockValidDevice()
    process.env.ANTHROPIC_CAPTURE_MODEL = 'claude-haiku-test'
    const res = await POST(
      makeRequest({ episode_name: 'Test', evidence_items: VALID_EVIDENCE_ITEMS }, 'token'),
    )
    expect(res.status).toBe(502)
    expect((await res.json()).error).toBe('invalid_model_response')
  })

  // ── Evidence synthesis path ───────────────────────────────────────────────

  it('returns 200 with observations from evidence_items path', async () => {
    mockValidDevice()
    mockAnthropicSuccess(VALID_OBSERVATIONS)
    process.env.ANTHROPIC_CAPTURE_MODEL = 'claude-haiku-test'
    const body = {
      episode_name: 'Smith Corp — Contract Review',
      episode_objective: 'Review indemnification clauses',
      started_at: '2026-08-03T14:00:00Z',
      ended_at: '2026-08-03T15:00:00Z',
      duration_minutes: 60,
      evidence_items: VALID_EVIDENCE_ITEMS,
    }
    const res = await POST(makeRequest(body, 'token'))
    expect(res.status).toBe(200)
    const responseBody = await res.json()
    expect(responseBody.success).toBe(true)
    expect(Array.isArray(responseBody.observations)).toBe(true)
    expect(responseBody.observations).toHaveLength(2)
    expect(responseBody.observations[0].timestamp).toBe('14:30')
    expect(responseBody.observations[0].text).toContain('Smith Corp')
  })

  // ── Activity log fallback path ────────────────────────────────────────────

  it('returns 200 with observations from activity_log path', async () => {
    mockValidDevice()
    mockAnthropicSuccess([{ timestamp: '14:30', text: 'Worked on contract' }])
    process.env.ANTHROPIC_CAPTURE_MODEL = 'claude-haiku-test'
    const body = {
      episode_name: 'Smith Corp',
      started_at: '2026-08-03T14:00:00Z',
      ended_at: '2026-08-03T15:00:00Z',
      duration_minutes: 60,
      activity_log: '14:00 | Preview | "Smith Contract.pdf"',
    }
    const res = await POST(makeRequest(body, 'token'))
    expect(res.status).toBe(200)
    const responseBody = await res.json()
    expect(responseBody.success).toBe(true)
    expect(responseBody.observations[0].timestamp).toBe('14:30')
  })

  // ── Observations capped at MAX_KEY_OBSERVATIONS ───────────────────────────

  it('caps observations at 8', async () => {
    mockValidDevice()
    const tooMany = Array.from({ length: 15 }, (_, i) => ({
      timestamp: `${String(i + 8).padStart(2, '0')}:00`,
      text: `Observation ${i + 1}`,
    }))
    mockAnthropicSuccess(tooMany as typeof VALID_OBSERVATIONS)
    process.env.ANTHROPIC_CAPTURE_MODEL = 'claude-haiku-test'
    const res = await POST(
      makeRequest(
        { episode_name: 'Long Session', evidence_items: VALID_EVIDENCE_ITEMS },
        'token',
      ),
    )
    expect(res.status).toBe(200)
    const responseBody = await res.json()
    expect(responseBody.observations.length).toBeLessThanOrEqual(8)
  })

  // ── Local observation is preserved on failure ─────────────────────────────
  // (The agent's finalizer.py falls back to _template_observations when
  //  this endpoint returns success:false. No episode data is discarded.)
  it('agent receives failure response and can fall back to template observations', async () => {
    mockValidDevice()
    mockAnthropicError('API error')
    process.env.ANTHROPIC_CAPTURE_MODEL = 'claude-haiku-test'
    const res = await POST(
      makeRequest({ episode_name: 'Test', evidence_items: VALID_EVIDENCE_ITEMS }, 'token'),
    )
    // Server returns structured failure
    expect(res.status).toBeGreaterThanOrEqual(500)
    const responseBody = await res.json()
    expect(responseBody.success).toBe(false)
    expect(responseBody.error).toBeDefined()
    // The agent's _generate_observations() returns _template_observations() on None
    // — verified by finalizer.py code: result is None → template fallback → episode saved
  })
})
