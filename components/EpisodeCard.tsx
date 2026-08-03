"use client";

import Link from "next/link";
import { useState } from "react";
import type { Episode } from "@/lib/types";
import { fmt12Range } from "@/lib/fmt";

type Props = {
  episode: Episode;
  mergeTarget: Episode | null;
  onDelete: (id: string) => void;
  onUpdate: (ep: Episode) => void;
  onMerge: (keepId: string, dropId: string, merged: Episode) => void;
};

function fmtDuration(minutes: number): string {
  if (!minutes || minutes < 1) return "< 1m";
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

export default function EpisodeCard({
  episode,
  mergeTarget,
  onDelete,
  onUpdate,
  onMerge,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [merging, setMerging] = useState(false);
  const [saving, setSaving] = useState(false);

  // Edit form state — synced from episode prop
  const [caseName, setCaseName] = useState(episode.case_name);
  const [workType, setWorkType] = useState<"project" | "administrative">(
    episode.work_type ?? "project"
  );
  const [issue, setIssue] = useState(episode.issue_worked_on ?? "");
  const [isReportable, setIsReportable] = useState(
    episode.is_reportable !== false
  );

  const time = fmt12Range(episode.started_at, episode.ended_at);
  const duration = fmtDuration(episode.duration_minutes);

  async function handleDelete() {
    setDeleting(true);
    await fetch(`/api/episodes/${episode.id}`, { method: "DELETE" });
    onDelete(episode.id);
  }

  async function handleSave() {
    setSaving(true);
    try {
      const res = await fetch(`/api/episodes/${episode.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          case_name: caseName.trim() || episode.case_name,
          work_type: workType,
          issue_worked_on: issue.trim() || null,
          is_reportable: isReportable,
        }),
      });
      if (res.ok) {
        const json = await res.json();
        onUpdate(json.episode);
        setEditing(false);
      }
    } finally {
      setSaving(false);
    }
  }

  function handleCancelEdit() {
    setCaseName(episode.case_name);
    setWorkType(episode.work_type ?? "project");
    setIssue(episode.issue_worked_on ?? "");
    setIsReportable(episode.is_reportable !== false);
    setEditing(false);
  }

  async function handleMerge() {
    if (!mergeTarget) return;
    setMerging(true);
    try {
      // Keep the earlier episode by started_at so its name and observations lead
      const keepId =
        episode.started_at <= mergeTarget.started_at
          ? episode.id
          : mergeTarget.id;
      const dropId =
        episode.started_at <= mergeTarget.started_at
          ? mergeTarget.id
          : episode.id;
      const res = await fetch("/api/episodes/merge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keep_id: keepId, drop_id: dropId }),
      });
      if (res.ok) {
        const json = await res.json();
        onMerge(keepId, dropId, json.episode);
      }
    } finally {
      setMerging(false);
    }
  }

  const titleLink = (
    <Link
      href={`/project?name=${encodeURIComponent(episode.case_name)}`}
      className="text-sm font-medium text-neutral-900 hover:underline"
    >
      {episode.case_name}
    </Link>
  );

  const metaLine = (
    <p className="text-xs text-neutral-400 mt-0.5">
      {time}&nbsp;&middot;&nbsp;{duration}
      {episode.work_type === "administrative" && (
        <span className="ml-1 text-neutral-300">&middot; Admin</span>
      )}
    </p>
  );

  // ── Collapsed ──────────────────────────────────────────────────────────────
  if (!expanded) {
    return (
      <div className="px-6 py-4 hover:bg-neutral-50 transition-colors">
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            {titleLink}
            {metaLine}
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

  // ── Edit mode ──────────────────────────────────────────────────────────────
  if (editing) {
    return (
      <div className="px-6 py-5 bg-neutral-50">
        <div className="space-y-3 mb-4">
          <div>
            <label className="block text-xs text-neutral-500 mb-1">
              Project title
            </label>
            <input
              type="text"
              value={caseName}
              onChange={(e) => setCaseName(e.target.value)}
              className="w-full text-sm border border-neutral-200 rounded px-2.5 py-1.5
                         text-neutral-800 focus:outline-none focus:ring-1 focus:ring-neutral-400"
            />
          </div>
          <div>
            <label className="block text-xs text-neutral-500 mb-1">
              Work type
            </label>
            <select
              value={workType}
              onChange={(e) =>
                setWorkType(e.target.value as "project" | "administrative")
              }
              className="w-full text-sm border border-neutral-200 rounded px-2.5 py-1.5
                         text-neutral-800 focus:outline-none focus:ring-1 focus:ring-neutral-400 bg-white"
            >
              <option value="project">Project work</option>
              <option value="administrative">Administrative</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-neutral-500 mb-1">
              Issue worked on
            </label>
            <input
              type="text"
              value={issue}
              onChange={(e) => setIssue(e.target.value)}
              className="w-full text-sm border border-neutral-200 rounded px-2.5 py-1.5
                         text-neutral-800 focus:outline-none focus:ring-1 focus:ring-neutral-400"
            />
          </div>
          <div className="flex items-center gap-2">
            <input
              id={`reportable-${episode.id}`}
              type="checkbox"
              checked={isReportable}
              onChange={(e) => setIsReportable(e.target.checked)}
              className="rounded border-neutral-300"
            />
            <label
              htmlFor={`reportable-${episode.id}`}
              className="text-xs text-neutral-600"
            >
              Reportable
            </label>
          </div>
        </div>
        <div className="flex gap-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="text-xs font-medium bg-neutral-900 text-white px-3 py-1.5 rounded
                       hover:bg-neutral-700 transition-colors disabled:opacity-40"
          >
            {saving ? "Saving\u2026" : "Save"}
          </button>
          <button
            onClick={handleCancelEdit}
            className="text-xs text-neutral-400 hover:text-neutral-700 transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  // ── Expanded ───────────────────────────────────────────────────────────────
  return (
    <div className="px-6 py-5 bg-neutral-50">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          {titleLink}
          {metaLine}
          {episode.issue_worked_on && (
            <p className="text-xs text-neutral-500 mt-0.5">
              {episode.issue_worked_on}
            </p>
          )}
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
              <span className="font-mono text-xs text-neutral-300 shrink-0 mt-0.5">
                {o.timestamp}
              </span>
              <span>{o.text}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="pt-3 border-t border-neutral-200 flex flex-wrap gap-x-4 gap-y-2">
        <button
          onClick={() => setEditing(true)}
          className="text-xs text-neutral-500 hover:text-neutral-800 transition-colors"
        >
          Edit
        </button>
        {mergeTarget && (
          <button
            onClick={handleMerge}
            disabled={merging}
            className="text-xs text-neutral-500 hover:text-neutral-800 transition-colors disabled:opacity-40"
          >
            {merging ? "Merging\u2026" : "Merge with adjacent"}
          </button>
        )}
        <button
          onClick={handleDelete}
          disabled={deleting}
          className="text-xs text-red-500 hover:text-red-700 transition-colors disabled:opacity-40"
        >
          {deleting ? "Deleting\u2026" : "Delete episode"}
        </button>
      </div>
    </div>
  );
}
