"use client";

import type { Episode, Season, DayGroup } from "@/lib/types";
import EpisodeCard from "./EpisodeCard";
import { fmt12Date } from "@/lib/fmt";

type Props = {
  episodes: Episode[];
  onDelete: (id: string) => void;
  onUpdate: (ep: Episode) => void;
  onMerge: (keepId: string, dropId: string, merged: Episode) => void;
};

const DAY_NAMES = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

function localIsoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function isoMonday(d: Date): string {
  const day = d.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  const mon = new Date(d);
  mon.setDate(d.getDate() + diff);
  return localIsoDate(mon);
}

function weekLabel(monday: string): string {
  const currentMonday = isoMonday(new Date());
  if (monday === currentMonday) return "This week";
  const currentMondayDate = new Date(currentMonday + "T00:00:00");
  const lastMon = new Date(currentMondayDate);
  lastMon.setDate(lastMon.getDate() - 7);
  if (monday === localIsoDate(lastMon)) return "Last week";
  const d = new Date(monday + "T00:00:00");
  return `Week of ${d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  })}`;
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
        const key = `${DAY_NAMES[d.getDay()]}|${localIsoDate(d)}`;
        (byDay[key] ??= []).push(ep);
      }
      const days: DayGroup[] = Object.entries(byDay)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, dayEps]) => {
          const [label, date] = key.split("|");
          // Sort within day by started_at ascending
          const sorted = [...dayEps].sort((a, b) =>
            a.started_at.localeCompare(b.started_at)
          );
          return { label, date, episodes: sorted };
        });
      const sun = new Date(monday + "T00:00:00");
      sun.setDate(sun.getDate() + 6);
      return {
        weekStart: monday,
        weekEnd: localIsoDate(sun),
        label: weekLabel(monday),
        days,
      };
    });
}

export default function EpisodeList({
  episodes,
  onDelete,
  onUpdate,
  onMerge,
}: Props) {
  if (episodes.length === 0) {
    return (
      <p className="text-sm text-neutral-500 text-center py-12">
        No episodes yet. Start a work session or add a manual entry.
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
                  {fmt12Date(day.date + "T12:00:00")}
                </p>
                <div className="divide-y divide-neutral-100">
                  {day.episodes.map((ep, idx) => {
                    // Check if an immediately adjacent episode has the same project name
                    const prev = idx > 0 ? day.episodes[idx - 1] : null;
                    const next =
                      idx < day.episodes.length - 1
                        ? day.episodes[idx + 1]
                        : null;
                    const mergeTarget =
                      (prev &&
                        prev.case_name?.trim().toLowerCase() ===
                          ep.case_name?.trim().toLowerCase()
                        ? prev
                        : null) ??
                      (next &&
                        next.case_name?.trim().toLowerCase() ===
                          ep.case_name?.trim().toLowerCase()
                        ? next
                        : null);
                    return (
                      <EpisodeCard
                        key={ep.id}
                        episode={ep}
                        mergeTarget={mergeTarget}
                        onDelete={onDelete}
                        onUpdate={onUpdate}
                        onMerge={onMerge}
                      />
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
