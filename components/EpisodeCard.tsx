"use client";

import { useState } from "react";
import type { Episode } from "@/lib/types";
import Storyline from "./Storyline";

type Props = {
  episode: Episode;
  onDelete: (id: string) => void;
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDuration(startedAt: string, endedAt: string): string {
  const ms = new Date(endedAt).getTime() - new Date(startedAt).getTime();
  const totalMinutes = Math.floor(ms / 60000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export default function EpisodeCard({ episode, onDelete }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    setDeleting(true);
    await fetch(`/api/episodes/${episode.id}`, { method: "DELETE" });
    onDelete(episode.id);
  }

  const summaryExcerpt =
    episode.summary.length > 120
      ? episode.summary.slice(0, 120) + "\u2026"
      : episode.summary;

  const endedAt = episode.ended_at ?? new Date().toISOString();

  if (!expanded) {
    return (
      <div className="px-6 py-5 hover:bg-neutral-50 transition-colors">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-sm font-medium text-neutral-900">{episode.title}</p>
            {summaryExcerpt && (
              <p className="text-sm text-neutral-500 leading-relaxed mt-0.5">
                {summaryExcerpt}
              </p>
            )}
            <p className="text-xs text-neutral-400 mt-1">
              {formatDate(episode.started_at)} &ndash; {formatDate(endedAt)}{" "}
              &middot; {formatDuration(episode.started_at, endedAt)}
            </p>
          </div>
          <button
            onClick={() => setExpanded(true)}
            className="text-xs text-neutral-400 hover:text-neutral-900 transition-colors shrink-0"
          >
            Expand ↓
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="px-6 py-6 bg-neutral-50">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 mb-5">
        <div className="min-w-0">
          <p className="text-sm font-medium text-neutral-900">{episode.title}</p>
          <p className="text-xs text-neutral-400 mt-1">
            {formatDate(episode.started_at)} &ndash; {formatDate(endedAt)}{" "}
            &middot; {formatDuration(episode.started_at, endedAt)}
          </p>
        </div>
        <button
          onClick={() => setExpanded(false)}
          className="text-xs text-neutral-400 hover:text-neutral-900 transition-colors shrink-0"
        >
          Collapse ↑
        </button>
      </div>

      {/* Summary */}
      {episode.summary && (
        <div className="mb-5">
          <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-2">
            Summary
          </p>
          <p className="text-sm text-neutral-500 leading-relaxed">{episode.summary}</p>
        </div>
      )}

      {/* Storyline */}
      {episode.storyline.length > 0 && (
        <div className="mb-5">
          <Storyline entries={episode.storyline} />
        </div>
      )}

      {/* Screenshots */}
      {episode.screenshots.length > 0 && (
        <div className="mb-5">
          <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-3">
            Screenshots
          </p>
          <div className="space-y-5">
            {episode.screenshots.map((s) => (
              <div key={s.id}>
                {s.storageUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={s.storageUrl}
                    alt={s.extractedText || "Screenshot"}
                    className="w-full rounded-lg border border-neutral-200"
                  />
                ) : (
                  <div className="w-full h-40 rounded-lg border border-neutral-200 bg-neutral-100 flex items-center justify-center">
                    <span className="text-xs text-neutral-400">Image uploading…</span>
                  </div>
                )}
                {s.extractedText && (
                  <p className="text-xs text-neutral-500 mt-1.5 leading-relaxed">
                    {s.extractedText}
                  </p>
                )}
                <p className="text-xs text-neutral-400 mt-0.5 font-mono">{s.timestamp}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center pt-4 border-t border-neutral-200">
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
