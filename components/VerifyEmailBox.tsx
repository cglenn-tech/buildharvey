'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'

export default function VerifyEmailBox({ email }: { email: string }) {
  const router = useRouter()
  const [resendDisabled, setResendDisabled] = useState(false)
  const [resendMsg, setResendMsg] = useState('')

  async function handleResend() {
    setResendDisabled(true)
    setResendMsg('')
    try {
      const res = await fetch('/api/auth/resend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      const json = await res.json()
      if (json.error) {
        setResendMsg(json.error)
      } else {
        setResendMsg('Email sent.')
      }
    } catch {
      setResendMsg('Failed to resend. Try again.')
    }
    setTimeout(() => setResendDisabled(false), 30_000)
  }

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

        <h2 className="text-base font-semibold text-neutral-900 mb-2">Verify email</h2>
        <p className="text-sm text-neutral-600 mb-6">
          Verification sent to: {email}
        </p>

        <button
          onClick={handleResend}
          disabled={resendDisabled}
          className="text-sm text-neutral-900 underline disabled:opacity-40"
        >
          Resend email
        </button>

        {resendMsg && (
          <p className="mt-2 text-sm text-neutral-500">{resendMsg}</p>
        )}
      </div>
    </div>
  )
}
