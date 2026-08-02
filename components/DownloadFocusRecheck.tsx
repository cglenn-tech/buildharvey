'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

/**
 * Mounted on /download. When the tab regains focus or becomes visible,
 * re-runs the server component (which checks for a connected device and
 * redirects to / if one exists). No polling — fires only on focus/visibility.
 */
export default function DownloadFocusRecheck() {
  const router = useRouter()

  useEffect(() => {
    function recheck() {
      if (document.visibilityState === 'visible') {
        router.refresh()
      }
    }

    document.addEventListener('visibilitychange', recheck)
    window.addEventListener('focus', recheck)

    return () => {
      document.removeEventListener('visibilitychange', recheck)
      window.removeEventListener('focus', recheck)
    }
  }, [router])

  return null
}
