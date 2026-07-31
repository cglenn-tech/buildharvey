import { redirect } from 'next/navigation'
import { getServerClient } from '@/lib/supabase-server'
import { getAdminClient } from '@/lib/supabase-admin'
import DownloadButton from '@/components/DownloadButton'

export const dynamic = 'force-dynamic'

interface ReleaseProps {
  version: string
  sha256: string
}

export default async function DownloadPage() {
  const supabase = await getServerClient()
  const { data: { user }, error: authError } = await supabase.auth.getUser()

  if (authError || !user) {
    redirect('/')
  }

  if (!user.email_confirmed_at) {
    redirect(`/verify?email=${encodeURIComponent(user.email ?? '')}`)
  }

  const admin = getAdminClient()
  const { data: releases } = await admin
    .from('app_releases')
    .select('version, sha256')
    .eq('active', true)
    .eq('platform', 'macos')
    .limit(1)

  const release: ReleaseProps | null =
    releases && releases.length > 0 ? releases[0] : null

  return (
    <div className="min-h-screen flex items-center justify-center bg-white">
      <div className="max-w-sm px-6 w-full">
        <h1 className="text-lg font-semibold text-neutral-900 mb-1">BuildHarvey</h1>
        <h2 className="text-base font-medium text-neutral-900 mb-2">
          Download BuildHarvey
        </h2>
        <p className="text-sm text-neutral-500 mb-4">
          Install BuildHarvey on the Mac you use for work.
        </p>

        {release ? (
          <>
            <p className="text-sm text-neutral-500 mb-6">
              Version: {release.version} · System: macOS
            </p>

            <DownloadButton version={release.version} sha256={release.sha256} />

            <details className="mt-6">
              <summary className="text-xs text-neutral-400 cursor-pointer">
                Verify download
              </summary>
              <p className="text-xs font-mono text-neutral-400 mt-1 break-all">
                SHA-256: {release.sha256}
              </p>
            </details>
          </>
        ) : (
          <p className="text-sm text-neutral-500">
            The installer is currently unavailable. Please check back shortly.
          </p>
        )}
      </div>
    </div>
  )
}
