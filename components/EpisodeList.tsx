"use client";

import { useState } from "react";
import type { Episode, Season, DayGroup } from "@/lib/types";
import EpisodeCard from "./EpisodeCard";

type Props = {
  initialEpisodes: Episode[];
};

const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

function isoMonday(d: Date): string {
  const day = d.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  const mon = new Date(d);
  mon.setDate(d.getDate() + diff);
  return mon.toISOString().slice(0, 10);
}

function weekLabel(monday: string): string {
  const today = isoMonday(new Date());
  if (monday === today) return "This week";
  const lastMon = new Date(today + "T00:00:00Z");
  lastMon.setDate(lastMon.getDate() - 7);
  if (monday === lastMon.toISOString().slice(0, 10)) return "Last week";
  const d = new Date(monday + "T00:00:00Z");
  return `Week of ${d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })}`;
}

function groupByWeek(episodes: Episode[]): Season[] {
  const byWeek: Record<string, Episode[]> = {};
  for (const ep of episodes) {
    const mon = isoMonday(new Date(ep.started_at));
    (byWeek[mon] ??= []).push(ep);
  }

  return Object.entries(byWeek)
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([monday, eps]) => {
      const byDay: Record<string, Episode[]> = {};
      for (const ep of eps) {
        const d = new Date(ep.started_at);
        const key = `${DAY_NAMES[d.getDay()]}|${d.toISOString().slice(0, 10)}`;
        (byDay[key] ??= []).push(ep);
      }
      const days: DayGroup[] = Object.entries(byDay)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, dayEps]) => {
          const [label, date] = key.split("|");
          return { label, date, episodes: dayEps };
        });
      const sun = new Date(monday + "T00:00:00Z");
      sun.setDate(sun.getDate() + 6);
      return { weekStart: monday, weekEnd: sun.toISOString().slice(0, 10), label: weekLabel(monday), days };
    });
}

export default function EpisodeList({ initialEpisodes }: Props) {
  const [episodes, setEpisodes] = useState<Episode[]>(initialEpisodes);

  function handleDelete(id: string) {
    setEpisodes((prev) => prev.filter((e) => e.id !== id));
  }

  if (episodes.length === 0) {
    return (
      <p className="text-sm text-neutral-500 text-center py-12">
        No episodes yet. Start the desktop agent to begin capturing work.
      </p>
    );
  }

  const seasons = groupByWeek(episodes);

  return (
    <div className="space-y-8">
      {seasons.map((season) => (
        <div key={season.weekStart}>
          <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-3">
            {season.label}
          </p>
          <div className="border border-neutral-200 rounded-xl overflow-hidden divide-y divide-neutral-200">
            {season.days.map((day) => (
              <div key={day.date}>
                <p className="px-6 py-2 text-xs font-medium text-neutral-400 bg-neutral-50 border-b border-neutral-100">
                  {day.label}
                </p>
                <div className="divide-y divide-neutral-100">
                  {day.episodes.map((ep) => (
                    <EpisodeCard key={ep.id} episode={ep} onDelete={handleDelete} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
