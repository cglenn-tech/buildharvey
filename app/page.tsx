import { getSupabaseClient } from "@/lib/supabase";
import type { Episode } from "@/lib/types";
import EpisodeList from "@/components/EpisodeList";

export const dynamic = "force-dynamic";

export default async function Home() {
  const supabase = getSupabaseClient();
  const { data } = await supabase
    .from("episodes")
    .select("*")
    .order("started_at", { ascending: false });

  const episodes = (data as Episode[]) ?? [];

  return (
    <main className="max-w-2xl mx-auto px-6 py-10">
      <div className="mb-8">
        <h1 className="text-lg font-semibold text-neutral-900">Episodes</h1>
        <p className="text-sm text-neutral-500 mt-1">
          Work sessions observed and grouped by BuildHarvey.
        </p>
      </div>
      <EpisodeList initialEpisodes={episodes} />
    </main>
  );
}
