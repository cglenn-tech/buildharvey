import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock('@/lib/supabase-admin', () => ({ getAdminClient: vi.fn() }))
vi.mock('@/lib/device-auth', () => ({ getDeviceFromToken: vi.fn() }))

import { getAdminClient } from '@/lib/supabase-admin'
import { getDeviceFromToken } from '@/lib/device-auth'
import { GET } from './route'

// ── Helpers ───────────────────────────────────────────────────────────────────

const DEVICE = { id: 'dev-1', user_id: 'usr-1', installation_id: 'inst-uuid-1234' }

function makeRequest(authHeader?: string): Request {
  const headers: Record<string, string> = {}
  if (authHeader) headers['authorization'] = authHeader
  return new Request('http://localhost/api/realtime/token', { headers })
}

function mockUpdateChain() {
  const eqFn = vi.fn().mockResolvedValue({})
  const updateFn = vi.fn().mockReturnValue({ eq: eqFn })
  vi.mocked(getAdminClient).mockReturnValue({
    from: vi.fn().mockReturnValue({ update: updateFn }),
  } as ReturnType<typeof getAdminClient>)
  return { updateFn, eqFn }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('GET /api/realtime/token', () => {
  const originalSecret = process.env.SUPABASE_JWT_SECRET
  const originalSupabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
  const originalAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

  beforeEach(() => {
    vi.clearAllMocks()
    process.env.SUPABASE_JWT_SECRET = 'test-secret-32-chars-long-xxxxxxxx'
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co'
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'test-anon-key'
  })

  afterEach(() => {
    process.env.SUPABASE_JWT_SECRET = originalSecret
    process.env.NEXT_PUBLIC_SUPABASE_URL = originalSupabaseUrl
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = originalAnonKey
  })

  it('returns 401 when no auth header is provided', async () => {
    vi.mocked(getDeviceFromToken).mockResolvedValue(null)
    mockUpdateChain()
    const res = await GET(makeRequest())
    expect(res.status).toBe(401)
    expect((await res.json()).error).toBe('Unauthorized')
  })

  it('returns 401 for a revoked or unknown device token', async () => {
    vi.mocked(getDeviceFromToken).mockResolvedValue(null)
    mockUpdateChain()
    const res = await GET(makeRequest('Bearer invalid-token'))
    expect(res.status).toBe(401)
  })

  it('returns 500 when SUPABASE_JWT_SECRET is not set', async () => {
    vi.mocked(getDeviceFromToken).mockResolvedValue(DEVICE)
    mockUpdateChain()
    delete process.env.SUPABASE_JWT_SECRET
    const res = await GET(makeRequest('Bearer valid-token'))
    expect(res.status).toBe(500)
    expect((await res.json()).error).toBe('Server misconfiguration')
  })

  it('returns 200 with device_id and installation_id for a valid token', async () => {
    vi.mocked(getDeviceFromToken).mockResolvedValue(DEVICE)
    mockUpdateChain()

    const res = await GET(makeRequest('Bearer valid-token'))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.device_id).toBe(DEVICE.id)
    expect(body.installation_id).toBe(DEVICE.installation_id)
    expect(typeof body.access_token).toBe('string')
    expect(body.expires_in).toBe(86400)
    expect(body.supabase_url).toBe('https://test.supabase.co')
    expect(body.anon_key).toBe('test-anon-key')
  })

  it('calls last_seen_at update on successful token fetch', async () => {
    vi.mocked(getDeviceFromToken).mockResolvedValue(DEVICE)
    const { updateFn, eqFn } = mockUpdateChain()

    await GET(makeRequest('Bearer valid-token'))

    expect(updateFn).toHaveBeenCalledWith(
      expect.objectContaining({ last_seen_at: expect.any(String) })
    )
    expect(eqFn).toHaveBeenCalledWith('id', DEVICE.id)
  })

  it('returns installation_id as null when device has none', async () => {
    vi.mocked(getDeviceFromToken).mockResolvedValue({ ...DEVICE, installation_id: null })
    mockUpdateChain()

    const res = await GET(makeRequest('Bearer valid-token'))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.installation_id).toBeNull()
  })
})
