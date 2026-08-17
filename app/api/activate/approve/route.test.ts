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
  existingDevice = null,
  updateDeviceId = DEVICE_ID,
  insertDeviceId = DEVICE_ID,
  updateSpy,
  insertSpy,
}: {
  activation: ActivationRow | null
  existingDevice?: { id: string } | null
  updateDeviceId?: string
  insertDeviceId?: string
  updateSpy?: ReturnType<typeof vi.fn>
  insertSpy?: ReturnType<typeof vi.fn>
}) {
  const _updateSpy = updateSpy ?? vi.fn()
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

  // devices: .select('id').eq('user_id', ...).eq('installation_id', ...).single() — lookup existing
  const devSelectSingle = vi.fn().mockResolvedValue({ data: existingDevice, error: null })
  const devSelectEq2 = vi.fn().mockReturnValue({ single: devSelectSingle })
  const devSelectEq1 = vi.fn().mockReturnValue({ eq: devSelectEq2 })
  const devSelect = vi.fn().mockReturnValue({ eq: devSelectEq1 })

  // devices: .update({...}).eq('id', ...).select('id').single() — reconnect path
  const updateSingle = vi.fn().mockResolvedValue({ data: { id: updateDeviceId }, error: null })
  const updateSelect = vi.fn().mockReturnValue({ single: updateSingle })
  const updateEq = vi.fn().mockReturnValue({ select: updateSelect })
  _updateSpy.mockReturnValue({ eq: updateEq })

  // devices: .insert({...}).select('id').single() — first activation or legacy
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
          select: devSelect,
          update: _updateSpy,
          insert: _insertSpy,
        }
      }
      return {}
    }),
  } as ReturnType<typeof getAdminClient>)

  return { updateSpy: _updateSpy, insertSpy: _insertSpy }
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

  it('inserts device when activation has installation_id and no existing device', async () => {
    mockAuthUser(USER_ID)
    const { updateSpy, insertSpy } = buildAdminMock({
      activation: {
        id: ACTIVATION_ID,
        token_hash: 'abc123',
        device_name: 'My Mac',
        platform: 'macos',
        installation_id: INSTALLATION_ID,
      },
      existingDevice: null,
    })

    const res = await POST(makeRequest({ activation_id: ACTIVATION_ID }))
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ ok: true })

    // Select-then-insert path: no existing device → insert, not update
    expect(insertSpy).toHaveBeenCalledOnce()
    expect(updateSpy).not.toHaveBeenCalled()

    // Insert must include installation_id and user_id
    const insertArg = insertSpy.mock.calls[0][0]
    expect(insertArg.installation_id).toBe(INSTALLATION_ID)
    expect(insertArg.user_id).toBe(USER_ID)
  })

  it('clears revoked_at when updating existing device on reconnect', async () => {
    mockAuthUser(USER_ID)
    const { updateSpy } = buildAdminMock({
      activation: {
        id: ACTIVATION_ID,
        token_hash: 'newhash',
        platform: 'macos',
        installation_id: INSTALLATION_ID,
      },
      existingDevice: { id: DEVICE_ID },
    })

    await POST(makeRequest({ activation_id: ACTIVATION_ID }))

    // Existing device found → update path, must clear revoked_at
    const updateArg = updateSpy.mock.calls[0][0]
    expect(updateArg.revoked_at).toBeNull()
  })

  it('inserts device (legacy) when activation has no installation_id', async () => {
    mockAuthUser(USER_ID)
    const { updateSpy, insertSpy } = buildAdminMock({
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

    // Legacy path (no installation_id) → plain insert, no select/update
    expect(insertSpy).toHaveBeenCalledOnce()
    expect(updateSpy).not.toHaveBeenCalled()
  })

  it('two new activations with different installation_ids insert independently', async () => {
    mockAuthUser(USER_ID)
    const INSTALLATION_ID_2 = 'b2c3d4e5-f6a7-8901-bcde-f12345678901'

    // First activation — no existing device
    const { insertSpy } = buildAdminMock({
      activation: {
        id: 'act-1',
        token_hash: 'hash1',
        platform: 'macos',
        installation_id: INSTALLATION_ID,
      },
      existingDevice: null,
    })
    const res1 = await POST(makeRequest({ activation_id: 'act-1' }))
    expect(res1.status).toBe(200)
    const firstArg = insertSpy.mock.calls[0][0]
    expect(firstArg.installation_id).toBe(INSTALLATION_ID)

    vi.clearAllMocks()

    // Second activation with different installation_id — also no existing device
    const { insertSpy: insertSpy2 } = buildAdminMock({
      activation: {
        id: 'act-2',
        token_hash: 'hash2',
        platform: 'macos',
        installation_id: INSTALLATION_ID_2,
      },
      existingDevice: null,
    })
    mockAuthUser(USER_ID)
    const res2 = await POST(makeRequest({ activation_id: 'act-2' }))
    expect(res2.status).toBe(200)
    const secondArg = insertSpy2.mock.calls[0][0]
    expect(secondArg.installation_id).toBe(INSTALLATION_ID_2)
    // Different installation_ids → separate insert calls
    expect(firstArg.installation_id).not.toBe(secondArg.installation_id)
  })
})
