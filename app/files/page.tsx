import { redirect } from "next/navigation";
import { getServerClient } from "@/lib/supabase-server";
import { fmt12Date } from "@/lib/fmt";
import type { Episode } from "@/lib/types";
import AppNav from "@/components/AppNav";

export const dynamic = "force-dynamic";

type WeeklyReport = {
  id: string;
  week_start: string;
  week_end: string;
  period_label: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  content: string;
};

function EpisodeFilesRow({ episode }: { episode: Episode }) {
  const start = new Date(episode.started_at).toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
  const end = new Date(episode.ended_at).toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
  const duration = (() => {
    const m = episode.duration_minutes;
    if (!m || m < 1) return "< 1m";
    const h = Math.floor(m / 60);
    const min = Math.round(m % 60);
    return h > 0 ? `${h}h ${min}m` : `${min}m`;
  })();

  return (
    <div className="py-3 flex items-start justify-between">
      <div className="min-w-0 flex-1 pr-4">
        <p className="text-sm text-neutral-900 font-medium truncate">
          {episode.case_name}
        </p>
        <p className="text-xs text-neutral-400 mt-0.5">
          {fmt12Date(episode.started_at)} · {start} – {end} · {duration}
        </p>
        {episode.key_observations.length > 0 && (
          <p className="text-xs text-neutral-500 mt-1 line-clamp-2">
            {episode.key_observations[0].text}
          </p>
        )}
      </div>
    </div>
  );
}

export default async function FilesPage() {
  const supabase = await getServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/");

  const [reportsResult, episodesResult] = await Promise.all([
    supabase
      .from("weekly_reports")
      .select("id, week_start, week_end, period_label, version, created_at, updated_at, content")
      .eq("user_id", user.id)
      .order("created_at", { ascending: false }),
    supabase
      .from("episodes")
      .select(
        "id, case_name, started_at, ended_at, duration_minutes, key_observations, is_reportable, created_at"
      )
      .eq("user_id", user.id)
      .eq("is_reportable", true)
      .order("started_at", { ascending: false })
      .limit(200),
  ]);

  // All reports, already sorted by created_at DESC from the query
  const reports: WeeklyReport[] = reportsResult.data ?? [];
  const episodes: Episode[] = episodesResult.data ?? [];

  return (
    <>
      <AppNav />
      <main className="max-w-2xl mx-auto px-6 py-10 space-y-12">
      <h1 className="text-lg font-semibold">My Files</h1>

      {/* Weekly Reports */}
      <section>
        <h2 className="text-xs font-medium text-neutral-500 uppercase tracking-wide mb-4">
          Weekly Reports
        </h2>
        {reports.length === 0 ? (
          <p className="text-sm text-neutral-400">No reports yet.</p>
        ) : (
          <div className="divide-y divide-neutral-100">
            {reports.map((r) => (
              <div
                key={r.id}
                className="py-3 flex items-start justify-between"
              >
                <div>
                  <p className="text-sm text-neutral-900">
                    {r.period_label ?? `Week of ${fmt12Date(r.week_start + "T12:00:00Z")}`}
                  </p>
                  <p className="text-xs text-neutral-400 mt-0.5">
                    Generated {fmt12Date(r.created_at)}
                  </p>
                </div>
                <div className="flex gap-3 ml-4 shrink-0">
                  <a
                    href={`/api/report/download/${r.id}`}
                    className="text-xs text-neutral-500 underline"
                  >
                    Download
                  </a>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Episodes */}
      <section>
        <h2 className="text-xs font-medium text-neutral-500 uppercase tracking-wide mb-4">
          Episodes
        </h2>
        {episodes.length === 0 ? (
          <p className="text-sm text-neutral-400">No episodes yet.</p>
        ) : (
          <div className="divide-y divide-neutral-100">
            {episodes.map((ep) => (
              <EpisodeFilesRow key={ep.id} episode={ep} />
            ))}
          </div>
        )}
      </section>
    </main>
    </>
  );
}
