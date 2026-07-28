import type { StorylineEntry } from "@/lib/types";

type Props = {
  entries: StorylineEntry[];
};

export default function Storyline({ entries }: Props) {
  if (entries.length === 0) return null;

  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-3">
        Timeline
      </p>
      <div className="space-y-2">
        {entries.map((entry, i) => (
          <div key={i} className="flex gap-3">
            <span className="font-mono text-xs text-neutral-400 w-12 shrink-0 pt-0.5">
              {entry.timestamp}
            </span>
            <span className="text-sm text-neutral-700">{entry.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
