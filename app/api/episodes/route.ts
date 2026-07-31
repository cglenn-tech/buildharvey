import { getServerClient } from '@/lib/supabase-server'
import type { Episode } from '@/lib/types'

export async function GET() {
  const supabase = await getServerClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const { data, error } = await supabase
    .from('episodes')
    .select('*')
    .order('started_at', { ascending: false })

  if (error) {
    return Response.json({ error: error.message }, { status: 500 })
  }

  return Response.json(data as Episode[])
}
