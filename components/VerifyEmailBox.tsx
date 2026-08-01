'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { getBrowserClient } from '@/lib/supabase-browser'

type ResendState = 'idle' | 'sending' | 'sent' | 'error'

interface Props {
  email: string
  expired?: boolean
}

export default function VerifyEmailBox({ email, expired }: Props) {
  const router = useRouter()
  const [resendState, setResendState] = useState<ResendState>('idle')
  const [resendError, setResendError] = useState('')
  const [showSlowWarning, setShowSlowWarning] = useState(false)

  // Slow email warning — fires 8s after mount
  useEffect(() => {
    const t = setTimeout(() => setShowSlowWarning(true), 8000)
    return () => clearTimeout(t)
  }, [])

  // Poll for email verification every 3 seconds
  useEffect(() => {
    const supabase = getBrowserClient()
    const interval = setInterval(async () => {
      const { data: { user } } = await supabase.auth.getUser()
      if (user?.email_confirmed_at) {
        console.log('[verify] verified detected, redirecting')
        router.push('/')
      }
    }, 3000)
    return () => clearInterval(interval)
  }, [router])

  async function handleResend() {
    if (resendState === 'sending') return
    setResendState('sending')
    setResendError('')
    console.log('[verify] resend clicked', { email, t: Date.now() })
    try {
      const res = await fetch('/api/auth/resend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      const json = await res.json()
      if (json.error) {
        console.log('[verify] resend error', { error: json.error })
        setResendError(json.error)
        setResendState('error')
      } else {
        console.log('[verify] resend succeeded')
        setResendState('sent')
        setShowSlowWarning(false)
        setTimeout(() => setResendState('idle'), 30_000)
      }
    } catch {
      setResendError('Failed to resend. Try again.')
      setResendState('error')
    }
  }

  const resendButtonText =
    resendState === 'sending' ? 'Sending…'
    : resendState === 'sent' ? 'Email sent'
    : resendState === 'error' ? 'Try again'
    : 'Resend email'

  return (
    <div className="min-h-screen flex items-center justify-center bg-white">
      <div className="relative w-full max-w-sm px-6 py-8 border border-neutral-200 rounded-lg">
        <button
          onClick={() => router.push('/')}
          className="absolute top-4 right-4 text-neutral-400 hover:text-neutral-600 text-lg leading-none"
          aria-label="Close"
        >
          ×
        </button>

        {expired && (
          <p className="text-sm text-amber-700 mb-4">
            This verification link has expired or has already been used.
          </p>
        )}

        <h2 className="text-base font-semibold text-neutral-900 mb-2">Verify email</h2>
        <p className="text-sm text-neutral-600 mb-6">
          Verification sent to: {email}
        </p>

        <button
          onClick={handleResend}
          disabled={resendState === 'sending' || resendState === 'sent'}
          className="text-sm text-neutral-900 underline disabled:opacity-40"
        >
          {resendButtonText}
        </button>

        {resendState === 'error' && resendError && (
          <p className="mt-2 text-sm text-red-600">{resendError}</p>
        )}

        {showSlowWarning && (
          <p className="text-xs text-neutral-400 mt-3">
            Still sending… email delivery occasionally takes a little longer.
          </p>
        )}

        <div className="mt-6 space-y-2">
          <button onClick={() => router.push('/')} className="text-xs text-neutral-400 underline block">
            Change email
          </button>
          <button onClick={() => router.push('/')} className="text-xs text-neutral-400 underline block">
            Back to sign in
          </button>
        </div>
      </div>
    </div>
  )
}
