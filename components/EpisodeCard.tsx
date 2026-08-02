"use client";

import { useState } from "react";
import type { Episode } from "@/lib/types";
import { fmt12Range } from "@/lib/fmt";

type Props = {
  episode: Episode;
  onDelete: (id: string) => void;
};

function fmtDuration(minutes: number): string {
  if (!minutes || minutes < 1) return "< 1m";
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

export default function EpisodeCard({ episode, onDelete }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    setDeleting(true);
    await fetch(`/api/episodes/${episode.id}`, { method: "DELETE" });
    onDelete(episode.id);
  }

  const time = fmt12Range(episode.started_at, episode.ended_at);
  const duration = fmtDuration(episode.duration_minutes);

  if (!expanded) {
    return (
      <div className="px-6 py-4 hover:bg-neutral-50 transition-colors">
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <p className="text-sm font-medium text-neutral-900">{episode.case_name}</p>
            <p className="text-xs text-neutral-400 mt-0.5">{time} &middot; {duration}</p>
          </div>
          <button
            onClick={() => setExpanded(true)}
            className="text-xs text-neutral-400 hover:text-neutral-700 transition-colors shrink-0"
          >
            Expand
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="px-6 py-5 bg-neutral-50">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <p className="text-sm font-semibold text-neutral-900">{episode.case_name}</p>
          <p className="text-xs text-neutral-400 mt-0.5">{time} &middot; {duration}</p>
        </div>
        <button
          onClick={() => setExpanded(false)}
          className="text-xs text-neutral-400 hover:text-neutral-700 transition-colors shrink-0"
        >
          Collapse
        </button>
      </div>

      {episode.key_observations.length > 0 && (
        <ul className="space-y-1 mb-4">
          {episode.key_observations.map((o, i) => (
            <li key={i} className="flex gap-3 text-sm text-neutral-600">
              <span className="font-mono text-xs text-neutral-300 shrink-0 mt-0.5">{o.timestamp}</span>
              <span>{o.text}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="pt-3 border-t border-neutral-200">
        <button
          onClick={handleDelete}
          disabled={deleting}
          className="text-xs text-red-500 hover:text-red-700 transition-colors disabled:opacity-40"
        >
          {deleting ? "Deleting…" : "Delete episode"}
        </button>
      </div>
    </div>
  );
}
