import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { NextRequest } from 'next/server'

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock('@/lib/supabase-admin', () => ({ getAdminClient: vi.fn() }))
vi.mock('@/lib/supabase-server', () => ({ getServerClient: vi.fn() }))
vi.mock('@/lib/rate-limit', () => ({ rateLimit: vi.fn().mockResolvedValue(false) }))

import { getAdminClient } from '@/lib/supabase-admin'
import { getServerClient } from '@/lib/supabase-server'
import { POST } from './route'

// ── Helpers ───────────────────────────────────────────────────────────────────

const USER_ID = 'user-abc-123'
const ACTIVATION_ID = 'act-111'
const DEVICE_ID = 'dev-999'
const INSTALLATION_ID = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'

function makeRequest(body: unknown): NextRequest {
  return new Request('http://localhost/api/activate/approve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }) as unknown as NextRequest
}

function mockAuthUser(userId: string | null) {
  vi.mocked(getServerClient).mockResolvedValue({
    auth: {
      getUser: vi.fn().mockResolvedValue({ data: { user: userId ? { id: userId } : null } }),
    },
  } as ReturnType<typeof getServerClient>)
}

type ActivationRow = {
  id: string
  token_hash: string
  device_name?: string
  platform?: string
  installation_id?: string | null
}

function buildAdminMock({
  activation,
  upsertDeviceId = DEVICE_ID,
  insertDeviceId = DEVICE_ID,
  upsertSpy,
  insertSpy,
}: {
  activation: ActivationRow | null
  upsertDeviceId?: string
  insertDeviceId?: string
  upsertSpy?: ReturnType<typeof vi.fn>
  insertSpy?: ReturnType<typeof vi.fn>
}) {
  const _upsertSpy = upsertSpy ?? vi.fn()
  const _insertSpy = insertSpy ?? vi.fn()

  // device_activations: .select('*').eq().gt().is().single()
  const activationSingle = vi.fn().mockResolvedValue({ data: activation, error: activation ? null : 'not-found' })
  const activationIs = vi.fn().mockReturnValue({ single: activationSingle })
  const activationGt = vi.fn().mockReturnValue({ is: activationIs })
  const activationEq = vi.fn().mockReturnValue({ gt: activationGt })
  const activationSelect = vi.fn().mockReturnValue({ eq: activationEq })

  // device_activations: .update().eq()
  const activationUpdateEq = vi.fn().mockResolvedValue({})
  const activationUpdate = vi.fn().mockReturnValue({ eq: activationUpdateEq })

  // devices: .upsert().select('id').single()
  const upsertSingle = vi.fn().mockResolvedValue({ data: { id: upsertDeviceId }, error: null })
  const upsertSelect = vi.fn().mockReturnValue({ single: upsertSingle })
  _upsertSpy.mockReturnValue({ select: upsertSelect })

  // devices: .insert().select('id').single()
  const insertSingle = vi.fn().mockResolvedValue({ data: { id: insertDeviceId }, error: null })
  const insertSelect = vi.fn().mockReturnValue({ single: insertSingle })
  _insertSpy.mockReturnValue({ select: insertSelect })

  vi.mocked(getAdminClient).mockReturnValue({
    from: vi.fn().mockImplementation((table: string) => {
      if (table === 'device_activations') {
        return {
          select: activationSelect,
          update: activationUpdate,
        }
      }
      if (table === 'devices') {
        return {
          upsert: _upsertSpy,
          insert: _insertSpy,
        }
      }
      return {}
    }),
  } as ReturnType<typeof getAdminClient>)

  return { upsertSpy: _upsertSpy, insertSpy: _insertSpy }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('POST /api/activate/approve', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns 401 when user is not authenticated', async () => {
    mockAuthUser(null)
    const res = await POST(makeRequest({ activation_id: ACTIVATION_ID }))
    expect(res.status).toBe(401)
    expect((await res.json()).error).toBe('Unauthorized')
  })

  it('returns 400 when activation_id is missing', async () => {
    mockAuthUser(USER_ID)
    buildAdminMock({ activation: null })
    const res = await POST(makeRequest({}))
    expect(res.status).toBe(400)
    expect((await res.json()).error).toBe('Missing activation_id')
  })

  it('returns 404 when activation is not found', async () => {
    mockAuthUser(USER_ID)
    buildAdminMock({ activation: null })
    const res = await POST(makeRequest({ activation_id: ACTIVATION_ID }))
    expect(res.status).toBe(404)
  })

  it('upserts device when activation has installation_id', async () => {
    mockAuthUser(USER_ID)
    const { upsertSpy, insertSpy } = buildAdminMock({
      activation: {
        id: ACTIVATION_ID,
        token_hash: 'abc123',
        device_name: 'My Mac',
        platform: 'macos',
        installation_id: INSTALLATION_ID,
      },
    })

    const res = await POST(makeRequest({ activation_id: ACTIVATION_ID }))
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ ok: true })

    // Should have called upsert, not insert
    expect(upsertSpy).toHaveBeenCalledOnce()
    expect(insertSpy).not.toHaveBeenCalled()

    // Upsert should include the installation_id and clear revoked_at
    const upsertArg = upsertSpy.mock.calls[0][0]
    expect(upsertArg.installation_id).toBe(INSTALLATION_ID)
    expect(upsertArg.user_id).toBe(USER_ID)
    expect(upsertArg.revoked_at).toBeNull()
  })

  it('clears revoked_at when upserting existing device on reconnect', async () => {
    mockAuthUser(USER_ID)
    const { upsertSpy } = buildAdminMock({
      activation: {
        id: ACTIVATION_ID,
        token_hash: 'newhash',
        platform: 'macos',
        installation_id: INSTALLATION_ID,
      },
    })

    await POST(makeRequest({ activation_id: ACTIVATION_ID }))

    const upsertArg = upsertSpy.mock.calls[0][0]
    expect(upsertArg.revoked_at).toBeNull()
  })

  it('inserts device (legacy) when activation has no installation_id', async () => {
    mockAuthUser(USER_ID)
    const { upsertSpy, insertSpy } = buildAdminMock({
      activation: {
        id: ACTIVATION_ID,
        token_hash: 'abc123',
        platform: 'macos',
        installation_id: null,
      },
    })

    const res = await POST(makeRequest({ activation_id: ACTIVATION_ID }))
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ ok: true })

    // Should have called insert, not upsert
    expect(insertSpy).toHaveBeenCalledOnce()
    expect(upsertSpy).not.toHaveBeenCalled()
  })

  it('two activations with different installation_ids call upsert twice independently', async () => {
    mockAuthUser(USER_ID)
    const INSTALLATION_ID_2 = 'b2c3d4e5-f6a7-8901-bcde-f12345678901'

    // First activation
    const { upsertSpy } = buildAdminMock({
      activation: {
        id: 'act-1',
        token_hash: 'hash1',
        platform: 'macos',
        installation_id: INSTALLATION_ID,
      },
    })
    const res1 = await POST(makeRequest({ activation_id: 'act-1' }))
    expect(res1.status).toBe(200)
    const firstArg = upsertSpy.mock.calls[0][0]
    expect(firstArg.installation_id).toBe(INSTALLATION_ID)

    vi.clearAllMocks()

    // Second activation with different installation_id
    const { upsertSpy: upsertSpy2 } = buildAdminMock({
      activation: {
        id: 'act-2',
        token_hash: 'hash2',
        platform: 'macos',
        installation_id: INSTALLATION_ID_2,
      },
    })
    mockAuthUser(USER_ID)
    const res2 = await POST(makeRequest({ activation_id: 'act-2' }))
    expect(res2.status).toBe(200)
    const secondArg = upsertSpy2.mock.calls[0][0]
    expect(secondArg.installation_id).toBe(INSTALLATION_ID_2)
    // Different installation_ids → different upsert calls
    expect(firstArg.installation_id).not.toBe(secondArg.installation_id)
  })
})
