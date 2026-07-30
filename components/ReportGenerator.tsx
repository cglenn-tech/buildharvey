"use client";

import { useState } from "react";

function isoMonday(d: Date): string {
  const day = d.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  const mon = new Date(d);
  mon.setDate(d.getDate() + diff);
  return mon.toISOString().slice(0, 10);
}

function isoSunday(monday: string): string {
  const d = new Date(monday + "T00:00:00Z");
  d.setDate(d.getDate() + 6);
  return d.toISOString().slice(0, 10);
}

export default function ReportGenerator() {
  const todayMonday = isoMonday(new Date());
  const [from, setFrom] = useState(todayMonday);
  const [to, setTo] = useState(isoSunday(todayMonday));
  const [report, setReport] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function setThisWeek() {
    const mon = isoMonday(new Date());
    setFrom(mon);
    setTo(isoSunday(mon));
    setReport(null);
  }

  function setLastWeek() {
    const lastMon = new Date(isoMonday(new Date()) + "T00:00:00Z");
    lastMon.setDate(lastMon.getDate() - 7);
    const mon = lastMon.toISOString().slice(0, 10);
    setFrom(mon);
    setTo(isoSunday(mon));
    setReport(null);
  }

  async function generate() {
    setGenerating(true);
    setReport(null);
    setError(null);
    try {
      const res = await fetch("/api/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          weekStart: from + "T00:00:00Z",
          weekEnd: to + "T23:59:59Z",
        }),
      });
      const json = await res.json();
      if (json.error) throw new Error(json.error);
      setReport(json.report);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="border border-neutral-200 rounded-xl p-5">
      <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400 mb-4">
        Generate Report
      </p>

      <div className="flex flex-wrap gap-4 items-end mb-3">
        <div>
          <label className="block text-xs text-neutral-500 mb-1">Date From</label>
          <input
            type="date"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            className="text-sm border border-neutral-200 rounded px-2.5 py-1.5 text-neutral-800
                       focus:outline-none focus:ring-1 focus:ring-neutral-400"
          />
        </div>
        <div>
          <label className="block text-xs text-neutral-500 mb-1">Date To</label>
          <input
            type="date"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            className="text-sm border border-neutral-200 rounded px-2.5 py-1.5 text-neutral-800
                       focus:outline-none focus:ring-1 focus:ring-neutral-400"
          />
        </div>
        <button
          onClick={generate}
          disabled={generating || !from || !to}
          className="text-sm font-medium bg-neutral-900 text-white px-4 py-1.5 rounded
                     hover:bg-neutral-700 transition-colors disabled:opacity-40"
        >
          {generating ? "Generating…" : "Generate Weekly Report"}
        </button>
      </div>

      <div className="flex gap-2">
        <button
          onClick={setThisWeek}
          className="text-xs text-neutral-500 hover:text-neutral-800 border border-neutral-200
                     rounded px-2 py-0.5 transition-colors"
        >
          This Week
        </button>
        <button
          onClick={setLastWeek}
          className="text-xs text-neutral-500 hover:text-neutral-800 border border-neutral-200
                     rounded px-2 py-0.5 transition-colors"
        >
          Last Week
        </button>
      </div>

      {error && (
        <p className="mt-3 text-xs text-red-500">{error}</p>
      )}

      {report && (
        <div className="mt-5 pt-5 border-t border-neutral-100">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400">
              Weekly Report
            </p>
            <button
              onClick={() => setReport(null)}
              className="text-xs text-neutral-400 hover:text-neutral-700"
            >
              Dismiss
            </button>
          </div>
          <pre className="text-sm text-neutral-700 whitespace-pre-wrap font-sans leading-relaxed">
            {report}
          </pre>
        </div>
      )}
    </div>
  );
}
