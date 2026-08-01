import { getServerClient } from '@/lib/supabase-server'
import VerifyEmailBox from '@/components/VerifyEmailBox'

interface Props {
  searchParams: Promise<{ email?: string }>
}

export default async function VerifyPage({ searchParams }: Props) {
  const { email: rawEmail } = await searchParams

  // Prefer the URL param; fall back to the session email (handles page refresh)
  let email = rawEmail ? decodeURIComponent(rawEmail) : ''
  if (!email) {
    const supabase = await getServerClient()
    const { data: { user } } = await supabase.auth.getUser()
    email = user?.email ?? ''
  }

  return <VerifyEmailBox email={email} />
}
