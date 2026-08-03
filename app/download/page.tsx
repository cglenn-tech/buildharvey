import { redirect } from 'next/navigation'
import { getServerClient } from '@/lib/supabase-server'

export const dynamic = 'force-dynamic'

export default async function DownloadPage() {
  const supabase = await getServerClient()
  const { data: { user }, error: authError } = await supabase.auth.getUser()

  if (authError || !user) {
    redirect('/')
  }

  if (!user.email_confirmed_at) {
    redirect(`/verify?email=${encodeURIComponent(user.email ?? '')}`)
  }

  // Desktop download is archived — redirect confirmed users to the app
  redirect('/')
}
