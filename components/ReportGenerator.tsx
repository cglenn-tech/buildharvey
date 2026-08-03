"use client";

import { useState, useEffect, useCallback } from "react";

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

function localIsoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export default function ReportGenerator() {
  const todayMonday = isoMonday(new Date());
  const [from, setFrom] = useState(todayMonday);
  const [to, setTo] = useState(isoSunday(todayMonday));
  const [roundTo15, setRoundTo15] = useState(false);
  const [report, setReport] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);
  const [reportId, setReportId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [noEpisodes, setNoEpisodes] = useState(false);

  // Load previously saved report when date range changes
  const loadSaved = useCallback(
    async (periodStart: string, periodEnd: string) => {
      setLoading(true);
      setReport(null);
      setSaved(false);
      setReportId(null);
      setError(null);
      setNoEpisodes(false);
      try {
        const res = await fetch(
          `/api/report?periodStart=${periodStart}&periodEnd=${periodEnd}`
        );
        if (res.ok) {
          const json = await res.json();
          if (json?.content) {
            setReport(json.content);
            setSaved(true);
            setReportId(json.id ?? null);
          }
        }
      } catch {
        // Non-fatal: silently skip pre-fill if load fails
      } finally {
        setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    loadSaved(from, to);
  }, [from, to, loadSaved]);

  function setThisWeek() {
    const mon = isoMonday(new Date());
    setFrom(mon);
    setTo(isoSunday(mon));
  }

  function setLastWeek() {
    const lastMon = new Date(isoMonday(new Date()) + "T00:00:00Z");
    lastMon.setDate(lastMon.getDate() - 7);
    const mon = lastMon.toISOString().slice(0, 10);
    setFrom(mon);
    setTo(isoSunday(mon));
  }

  function setThisMonth() {
    const now = new Date();
    setFrom(localIsoDate(new Date(now.getFullYear(), now.getMonth(), 1)));
    setTo(localIsoDate(new Date(now.getFullYear(), now.getMonth() + 1, 0)));
  }

  function setLastMonth() {
    const now = new Date();
    setFrom(localIsoDate(new Date(now.getFullYear(), now.getMonth() - 1, 1)));
    setTo(localIsoDate(new Date(now.getFullYear(), now.getMonth(), 0)));
  }

  async function generate() {
    setGenerating(true);
    setReport(null);
    setSaved(false);
    setReportId(null);
    setError(null);
    setNoEpisodes(false);
    try {
      const res = await fetch("/api/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ periodStart: from, periodEnd: to, roundTo15 }),
      });
      let json: { error?: string; report?: string; id?: string };
      try {
        json = await res.json();
      } catch {
        throw new Error(`Server error (${res.status})`);
      }
      if (res.status === 422 && json.error === "no_episodes") {
        setNoEpisodes(true);
        return;
      }
      if (json.error) throw new Error(json.error);
      setReport(json.report ?? "");
      setSaved(true);
      setReportId(json.id ?? null);
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
          <label className="block text-xs text-neutral-500 mb-1">
            Date From
          </label>
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
          disabled={generating || loading || !from || !to}
          className="text-sm font-medium bg-neutral-900 text-white px-4 py-1.5 rounded
                     hover:bg-neutral-700 transition-colors disabled:opacity-40"
        >
          {generating ? "Generating\u2026" : "Generate Report"}
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mb-3">
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
        <button
          onClick={setThisMonth}
          className="text-xs text-neutral-500 hover:text-neutral-800 border border-neutral-200
                     rounded px-2 py-0.5 transition-colors"
        >
          This Month
        </button>
        <button
          onClick={setLastMonth}
          className="text-xs text-neutral-500 hover:text-neutral-800 border border-neutral-200
                     rounded px-2 py-0.5 transition-colors"
        >
          Last Month
        </button>
      </div>

      <div className="flex items-center gap-2 mb-1">
        <input
          id="round-to-15"
          type="checkbox"
          checked={roundTo15}
          onChange={(e) => setRoundTo15(e.target.checked)}
          className="rounded border-neutral-300"
        />
        <label htmlFor="round-to-15" className="text-xs text-neutral-600">
          Round to nearest 15 min
        </label>
      </div>

      {error && <p className="mt-3 text-xs text-red-500">{error}</p>}

      {noEpisodes && !report && (
        <p className="mt-3 text-xs text-neutral-500">
          No work episodes found for this period.
        </p>
      )}

      {loading && (
        <p className="mt-3 text-xs text-neutral-400">
          Loading saved report\u2026
        </p>
      )}

      {report && (
        <div className="mt-5 pt-5 border-t border-neutral-100">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2 flex-wrap">
              <p className="text-xs font-semibold uppercase tracking-widest text-neutral-400">
                Report
              </p>
              {saved && (
                <span className="text-xs text-neutral-400">&middot; Saved</span>
              )}
              {saved && reportId && (
                <a
                  href="/files"
                  className="text-xs text-neutral-400 hover:text-neutral-700 underline"
                >
                  Open in My Files
                </a>
              )}
            </div>
            <button
              onClick={() => {
                setReport(null);
                setSaved(false);
              }}
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
