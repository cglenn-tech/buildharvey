import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock('@/lib/supabase-server', () => ({ getServerClient: vi.fn() }))
vi.mock('@/lib/supabase-admin', () => ({ getAdminClient: vi.fn() }))
vi.mock('@/lib/rate-limit', () => ({ rateLimit: vi.fn() }))

import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'
import { rateLimit } from '@/lib/rate-limit'
import { GET, POST } from './route'

// ── Helpers ───────────────────────────────────────────────────────────────────

const GH_URL = 'https://github.com/cglenn-tech/buildharvey/releases/download/v1.0.1/BuildHarveySetup-1.0.1.exe'
const GH_VERSION = '1.0.1'

const VALID_RELEASE = {
  id: 'rel-1',
  version: '1.0.1',
  storage_path: 'windows/BuildHarveySetup-1.0.1.exe',
  sha256: 'a'.repeat(64),
}

const SUPABASE_SIGNED_URL = 'https://storage.example.com/signed?token=abc'

type UserStub = { id: string; email: string; email_confirmed_at: string | null }

function mockAuth(user: UserStub | null = { id: 'usr-1', email: 'test@example.com', email_confirmed_at: '2024-01-01' }) {
  vi.mocked(getServerClient).mockResolvedValue({
    auth: {
      getUser: vi.fn().mockResolvedValue({
        data: { user },
        error: user ? null : { message: 'no session' },
      }),
    },
  } as ReturnType<Awaited<ReturnType<typeof getServerClient>>>)
}

function mockAdmin(options: {
  releases?: typeof VALID_RELEASE[] | null
  releasesError?: { message: string } | null
  fileExists?: boolean
  signedUrl?: string | null
} = {}) {
  const {
    releases = [VALID_RELEASE],
    releasesError = null,
    fileExists = true,
    signedUrl = SUPABASE_SIGNED_URL,
  } = options

  const mockLimit = vi.fn().mockResolvedValue({ data: releases, error: releasesError })
  const mockEq2 = vi.fn().mockReturnValue({ limit: mockLimit })
  const mockEq1 = vi.fn().mockReturnValue({ eq: mockEq2 })
  const mockSelect = vi.fn().mockReturnValue({ eq: mockEq1 })
  const mockInsert = vi.fn().mockResolvedValue({ error: null })
  const mockExists = vi.fn().mockResolvedValue({ data: fileExists, error: null })
  const mockCreateSignedUrl = vi.fn().mockResolvedValue({
    data: signedUrl ? { signedUrl } : null,
    error: null,
  })

  vi.mocked(getAdminClient).mockReturnValue({
    from: vi.fn().mockImplementation((table: string) => {
      if (table === 'app_releases') return { select: mockSelect }
      if (table === 'download_events') return { insert: mockInsert }
      return {}
    }),
    storage: { from: vi.fn().mockReturnValue({ exists: mockExists, createSignedUrl: mockCreateSignedUrl }) },
  } as unknown as ReturnType<typeof getAdminClient>)
}

// ── GET /api/download/windows — GitHub release redirect ───────────────────────

describe('GET /api/download/windows', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    process.env.WINDOWS_INSTALLER_URL = GH_URL
    process.env.WINDOWS_INSTALLER_VERSION = GH_VERSION
  })

  afterEach(() => {
    delete process.env.WINDOWS_INSTALLER_URL
    delete process.env.WINDOWS_INSTALLER_VERSION
  })

  // ── Auth ────────────────────────────────────────────────────────────────

  it('returns 401 for unauthenticated user', async () => {
    mockAuth(null)
    const res = await GET()
    expect(res.status).toBe(401)
    expect((await res.json()).error).toBe('authentication_required')
  })

  it('returns 403 for unverified user', async () => {
    mockAuth({ id: 'usr-1', email: 'test@example.com', email_confirmed_at: null })
    const res = await GET()
    expect(res.status).toBe(403)
    expect((await res.json()).error).toBe('email_verification_required')
  })

  // ── Missing env vars ─────────────────────────────────────────────────────

  it('returns 404 release_unavailable when WINDOWS_INSTALLER_URL is missing', async () => {
    mockAuth()
    delete process.env.WINDOWS_INSTALLER_URL
    const res = await GET()
    expect(res.status).toBe(404)
    expect((await res.json()).error).toBe('release_unavailable')
  })

  it('returns 404 release_unavailable when WINDOWS_INSTALLER_VERSION is missing', async () => {
    mockAuth()
    delete process.env.WINDOWS_INSTALLER_VERSION
    const res = await GET()
    expect(res.status).toBe(404)
    expect((await res.json()).error).toBe('release_unavailable')
  })

  it('returns 404 release_unavailable when both env vars are missing', async () => {
    mockAuth()
    delete process.env.WINDOWS_INSTALLER_URL
    delete process.env.WINDOWS_INSTALLER_VERSION
    const res = await GET()
    expect(res.status).toBe(404)
    expect((await res.json()).error).toBe('release_unavailable')
  })

  // ── URL validation ───────────────────────────────────────────────────────

  it('returns 409 for non-HTTPS URL (http://)', async () => {
    mockAuth()
    process.env.WINDOWS_INSTALLER_URL = 'http://github.com/owner/repo/releases/download/v1/Setup.exe'
    const res = await GET()
    expect(res.status).toBe(409)
    expect((await res.json()).error).toBe('invalid_release_configuration')
  })

  it('returns 409 for unapproved host', async () => {
    mockAuth()
    process.env.WINDOWS_INSTALLER_URL = 'https://example.com/releases/Setup-1.0.1.exe'
    const res = await GET()
    expect(res.status).toBe(409)
    expect((await res.json()).error).toBe('invalid_release_configuration')
  })

  it('returns 409 for non-.exe URL', async () => {
    mockAuth()
    process.env.WINDOWS_INSTALLER_URL = 'https://github.com/owner/repo/releases/download/v1/Setup.dmg'
    const res = await GET()
    expect(res.status).toBe(409)
    expect((await res.json()).error).toBe('invalid_release_configuration')
  })

  // ── Success: redirect ────────────────────────────────────────────────────

  it('returns 302 redirect to GitHub release URL for configured release', async () => {
    mockAuth()
    const res = await GET()
    expect(res.status).toBe(302)
    expect(res.headers.get('Location')).toBe(GH_URL)
  })

  it('sets Cache-Control: no-store on the redirect', async () => {
    mockAuth()
    const res = await GET()
    expect(res.headers.get('Cache-Control')).toBe('no-store')
  })

  it('accepts objects.githubusercontent.com as an approved host', async () => {
    mockAuth()
    process.env.WINDOWS_INSTALLER_URL =
      'https://objects.githubusercontent.com/github-production-release-asset/123/BuildHarveySetup-1.0.1.exe'
    const res = await GET()
    expect(res.status).toBe(302)
  })
})

// ── POST /api/download/windows — Supabase Storage fallback ───────────────────

describe('POST /api/download/windows (Supabase fallback)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(rateLimit).mockResolvedValue(false)
  })

  it('returns 401 when unauthenticated', async () => {
    mockAuth(null)
    mockAdmin()
    expect((await POST()).status).toBe(401)
  })

  it('returns 403 when email is unverified', async () => {
    mockAuth({ id: 'usr-1', email: 'test@example.com', email_confirmed_at: null })
    mockAdmin()
    expect((await POST()).status).toBe(403)
  })

  it('returns 404 release_unavailable when no active release exists', async () => {
    mockAuth()
    mockAdmin({ releases: [] })
    const res = await POST()
    expect(res.status).toBe(404)
    expect((await res.json()).error).toBe('release_unavailable')
  })

  it('returns 409 when multiple active releases exist', async () => {
    mockAuth()
    mockAdmin({ releases: [VALID_RELEASE, { ...VALID_RELEASE, id: 'rel-2' }] })
    expect((await POST()).status).toBe(409)
  })

  it('returns 200 with signed URL for valid Supabase release', async () => {
    mockAuth()
    mockAdmin()
    const res = await POST()
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.url).toBe(SUPABASE_SIGNED_URL)
    expect(body.version).toBe('1.0.1')
    expect(body.sha256).toBe('a'.repeat(64))
  })
})
