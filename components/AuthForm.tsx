'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { getBrowserClient } from '@/lib/supabase-browser'

type Mode = 'signup' | 'signin'

export default function AuthForm() {
  const router = useRouter()
  const [mode, setMode] = useState<Mode>('signup')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const showPassword = email.includes('@') && email.includes('.')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (loading) return
    setError('')
    setLoading(true)

    const supabase = getBrowserClient()

    try {
      if (mode === 'signup') {
        const { data, error: signUpError } = await supabase.auth.signUp({
          email,
          password,
          options: { emailRedirectTo: '/auth/callback' },
        })

        if (signUpError) {
          if (signUpError.message.toLowerCase().includes('already registered')) {
            setError('Account exists — sign in instead')
          } else {
            setError(signUpError.message)
          }
          return
        }

        if (data.user) {
          router.push(`/verify?email=${encodeURIComponent(email)}`)
        }
      } else {
        const { error: signInError } = await supabase.auth.signInWithPassword({
          email,
          password,
        })

        if (signInError) {
          if (signInError.message.toLowerCase().includes('email not confirmed')) {
            router.push(`/verify?email=${encodeURIComponent(email)}`)
            return
          }
          setError('Invalid login credentials')
          return
        }

        router.refresh()
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-white">
      <div className="w-full max-w-sm px-6">
        <h1 className="text-lg font-semibold text-neutral-900 mb-6">BuildHarvey</h1>

        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => { setEmail(e.target.value); setError('') }}
            required
            className="w-full border border-neutral-200 rounded px-3 py-2 text-sm outline-none focus:border-neutral-400"
          />

          {showPassword && (
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => { setPassword(e.target.value); setError('') }}
              required
              minLength={6}
              className="w-full border border-neutral-200 rounded px-3 py-2 text-sm outline-none focus:border-neutral-400"
            />
          )}

          {error && (
            <p className="text-sm text-red-600">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading || !showPassword}
            className="w-full bg-neutral-900 text-white rounded px-3 py-2 text-sm font-medium disabled:opacity-40"
          >
            {loading
              ? 'Please wait…'
              : mode === 'signup'
              ? 'Continue'
              : 'Sign in'}
          </button>
        </form>

        <p className="mt-4 text-sm text-neutral-500">
          {mode === 'signup' ? (
            <>
              Already have an account?{' '}
              <button
                onClick={() => { setMode('signin'); setError('') }}
                className="text-neutral-900 underline"
              >
                Sign in
              </button>
            </>
          ) : (
            <>
              New to BuildHarvey?{' '}
              <button
                onClick={() => { setMode('signup'); setError('') }}
                className="text-neutral-900 underline"
              >
                Sign up
              </button>
            </>
          )}
        </p>
      </div>
    </div>
  )
}
