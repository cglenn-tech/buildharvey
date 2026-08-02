'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { getBrowserClient } from '@/lib/supabase-browser'

export default function AppNav() {
  const router = useRouter()

  async function signOut() {
    const supabase = getBrowserClient()
    await supabase.auth.signOut()
    router.push('/')
  }

  return (
    <nav className="border-b border-neutral-100 mb-8">
      <div className="max-w-2xl mx-auto px-6 py-4 flex items-center justify-between">
        <Link href="/" className="text-sm font-semibold text-neutral-900">
          BuildHarvey
        </Link>
        <div className="flex items-center gap-6">
          <Link
            href="/files"
            className="text-sm text-neutral-500 hover:text-neutral-900 transition-colors"
          >
            My Files
          </Link>
          <button
            onClick={signOut}
            className="text-sm text-neutral-500 hover:text-neutral-900 transition-colors"
          >
            Sign out
          </button>
        </div>
      </div>
    </nav>
  )
}
