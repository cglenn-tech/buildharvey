"use client";

import { useState } from "react";
import type { Episode } from "@/lib/types";
import EpisodeCard from "./EpisodeCard";

type Props = {
  initialEpisodes: Episode[];
};

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

  return (
    <div className="divide-y divide-neutral-200 border border-neutral-200 rounded-xl overflow-hidden">
      {episodes.map((episode) => (
        <EpisodeCard key={episode.id} episode={episode} onDelete={handleDelete} />
      ))}
    </div>
  );
}
