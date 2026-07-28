import { getSupabaseClient } from "@/lib/supabase";
import type { Episode } from "@/lib/types";

export async function GET() {
  const supabase = getSupabaseClient();
  const { data, error } = await supabase
    .from("episodes")
    .select("*")
    .order("started_at", { ascending: false });

  if (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }

  return Response.json(data as Episode[]);
}
