import { describe, it, expect, vi, beforeEach } from 'vitest'

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock('@/lib/supabase-server', () => ({ getServerClient: vi.fn() }))
vi.mock('@/lib/supabase-admin', () => ({ getAdminClient: vi.fn() }))
vi.mock('@/lib/rate-limit', () => ({ rateLimit: vi.fn() }))

import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'
import { rateLimit } from '@/lib/rate-limit'
import { POST } from './route'

// ── Helpers ───────────────────────────────────────────────────────────────────

const VALID_RELEASE = {
  id: 'rel-1',
  version: '1.0.1',
  storage_path: 'windows/BuildHarveySetup-1.0.1.exe',
  sha256: 'a'.repeat(64),
}

const SIGNED_URL = 'https://storage.example.com/signed?token=abc'

function mockAuth(options: {
  user?: { id: string; email: string; email_confirmed_at: string | null } | null
  error?: { message: string } | null
}) {
  const { user = { id: 'usr-1', email: 'test@example.com', email_confirmed_at: '2024-01-01' }, error = null } = options
  vi.mocked(getServerClient).mockResolvedValue({
    auth: {
      getUser: vi.fn().mockResolvedValue({ data: { user }, error }),
    },
  } as ReturnType<Awaited<ReturnType<typeof getServerClient>>>)
}

function mockAdmin(options: {
  releases?: typeof VALID_RELEASE[] | null
  releasesError?: { message: string } | null
  fileExists?: boolean
  existsError?: { message: string } | null
  signedUrl?: string | null
  signError?: { message: string } | null
  insertError?: { message: string } | null
} = {}) {
  const {
    releases = [VALID_RELEASE],
    releasesError = null,
    fileExists = true,
    existsError = null,
    signedUrl = SIGNED_URL,
    signError = null,
    insertError = null,
  } = options

  const mockLimit = vi.fn().mockResolvedValue({ data: releases, error: releasesError })
  const mockEq2 = vi.fn().mockReturnValue({ limit: mockLimit })
  const mockEq1 = vi.fn().mockReturnValue({ eq: mockEq2 })
  const mockSelect = vi.fn().mockReturnValue({ eq: mockEq1 })

  const mockInsert = vi.fn().mockResolvedValue({ error: insertError })

  const mockExists = vi.fn().mockResolvedValue({ data: fileExists, error: existsError })
  const mockCreateSignedUrl = vi.fn().mockResolvedValue({
    data: signedUrl ? { signedUrl } : null,
    error: signError,
  })
  const mockStorageFrom = vi.fn().mockReturnValue({
    exists: mockExists,
    createSignedUrl: mockCreateSignedUrl,
  })

  vi.mocked(getAdminClient).mockReturnValue({
    from: vi.fn().mockImplementation((table: string) => {
      if (table === 'app_releases') return { select: mockSelect }
      if (table === 'download_events') return { insert: mockInsert }
      return {}
    }),
    storage: { from: mockStorageFrom },
  } as unknown as ReturnType<typeof getAdminClient>)

  return { mockExists, mockCreateSignedUrl, mockStorageFrom }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('POST /api/download/windows', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(rateLimit).mockResolvedValue(false)
  })

  // ── Auth ──────────────────────────────────────────────────────────────────

  it('returns 401 when unauthenticated', async () => {
    mockAuth({ user: null, error: { message: 'no session' } })
    mockAdmin()
    const res = await POST()
    expect(res.status).toBe(401)
    const body = await res.json()
    expect(body.error).toBe('authentication_required')
  })

  it('returns 403 when email is unverified', async () => {
    mockAuth({ user: { id: 'usr-1', email: 'test@example.com', email_confirmed_at: null } })
    mockAdmin()
    const res = await POST()
    expect(res.status).toBe(403)
    const body = await res.json()
    expect(body.error).toBe('email_verification_required')
  })

  // ── Release availability ──────────────────────────────────────────────────

  it('returns 404 release_unavailable when no active release exists', async () => {
    mockAuth({})
    mockAdmin({ releases: [] })
    const res = await POST()
    expect(res.status).toBe(404)
    const body = await res.json()
    expect(body.error).toBe('release_unavailable')
  })

  it('returns 409 invalid_release_configuration when multiple active releases exist', async () => {
    mockAuth({})
    mockAdmin({ releases: [VALID_RELEASE, { ...VALID_RELEASE, id: 'rel-2' }] })
    const res = await POST()
    expect(res.status).toBe(409)
    const body = await res.json()
    expect(body.error).toBe('invalid_release_configuration')
  })

  // ── Storage path validation ───────────────────────────────────────────────

  it('returns 409 when storage_path does not start with windows/', async () => {
    mockAuth({})
    mockAdmin({ releases: [{ ...VALID_RELEASE, storage_path: 'macos/BuildHarveySetup-1.0.1.exe' }] })
    const res = await POST()
    expect(res.status).toBe(409)
    const body = await res.json()
    expect(body.error).toBe('invalid_release_configuration')
  })

  it('returns 409 when storage_path does not end with .exe', async () => {
    mockAuth({})
    mockAdmin({ releases: [{ ...VALID_RELEASE, storage_path: 'windows/BuildHarveySetup-1.0.1.dmg' }] })
    const res = await POST()
    expect(res.status).toBe(409)
    const body = await res.json()
    expect(body.error).toBe('invalid_release_configuration')
  })

  // ── SHA-256 validation ────────────────────────────────────────────────────

  it('returns 409 when sha256 is not 64 hex chars', async () => {
    mockAuth({})
    mockAdmin({ releases: [{ ...VALID_RELEASE, sha256: 'tooshort' }] })
    const res = await POST()
    expect(res.status).toBe(409)
    const body = await res.json()
    expect(body.error).toBe('invalid_release_configuration')
  })

  it('returns 409 when sha256 contains non-hex characters', async () => {
    mockAuth({})
    mockAdmin({ releases: [{ ...VALID_RELEASE, sha256: 'z'.repeat(64) }] })
    const res = await POST()
    expect(res.status).toBe(409)
    const body = await res.json()
    expect(body.error).toBe('invalid_release_configuration')
  })

  // ── Storage presence ──────────────────────────────────────────────────────

  it('returns 404 release_unavailable when file does not exist in storage', async () => {
    mockAuth({})
    mockAdmin({ fileExists: false })
    const res = await POST()
    expect(res.status).toBe(404)
    const body = await res.json()
    expect(body.error).toBe('release_unavailable')
  })

  // ── Success path ──────────────────────────────────────────────────────────

  it('returns 200 with url, version, sha256 for a valid release', async () => {
    mockAuth({})
    mockAdmin()
    const res = await POST()
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.url).toBe(SIGNED_URL)
    expect(body.version).toBe('1.0.1')
    expect(body.sha256).toBe('a'.repeat(64))
  })

  it('uses BuildHarveySetup-{version}.exe as the download filename in the signed URL', async () => {
    mockAuth({})
    const { mockCreateSignedUrl } = mockAdmin()
    await POST()
    expect(mockCreateSignedUrl).toHaveBeenCalledWith(
      VALID_RELEASE.storage_path,
      300,
      { download: 'BuildHarveySetup-1.0.1.exe' },
    )
  })
})
