import { NextRequest } from "next/server";
import Anthropic from "@anthropic-ai/sdk";
import { getServerClient } from "@/lib/supabase-server";
import type { Episode, KeyObservation } from "@/lib/types";

// ── Duration formatter ─────────────────────────────────────────────────────────

export function fmtDur(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  if (h === 0) return `${m} min`;
  if (m === 0) return `${h} hr`;
  return `${h} hr ${m} min`;
}

// ── Time formatters (UTC, for server-side report rendering) ───────────────────

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone: "UTC",
  });
}

function fmtDateLong(dateIso: string): string {
  // dateIso is YYYY-MM-DD
  return new Date(dateIso + "T12:00:00Z").toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  });
}

function fmtDateWithYear(dateIso: string): string {
  return new Date(dateIso + "T12:00:00Z").toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

// ── Period label ───────────────────────────────────────────────────────────────

function buildPeriodLabel(periodStart: string, periodEnd: string): string {
  const startStr = fmtDateLong(periodStart);
  const endStr = fmtDateWithYear(periodEnd);
  return `${startStr} \u2013 ${endStr}`;
}

// ── Group type returned by Claude ─────────────────────────────────────────────

type ClaudeGroup = {
  title: string;
  is_administrative: boolean;
  episode_ids: string[];
};

// ── Computed group with totals ────────────────────────────────────────────────

type GroupResult = {
  title: string;
  is_administrative: boolean;
  episode_ids: string[];
  episodes: Episode[];
  totalMinutes: number;
};

// ── Summary JSON stored in DB ─────────────────────────────────────────────────

export type ReportSummary = {
  periodLabel: string;
  groups: Array<{
    title: string;
    is_administrative: boolean;
    totalMinutes: number;
    episode_ids: string[];
  }>;
  caseMinutes: number;
  adminMinutes: number;
  totalMinutes: number;
};

// ── Phase 2: TypeScript calculates all totals ─────────────────────────────────

function buildGroups(
  claudeGroups: ClaudeGroup[],
  episodes: Episode[]
): GroupResult[] {
  const episodeById = new Map(episodes.map((e) => [e.id, e]));

  return claudeGroups.map((g) => {
    const eps = g.episode_ids
      .map((id) => episodeById.get(id))
      .filter((e): e is Episode => e !== undefined);
    const totalMinutes = eps.reduce(
      (sum, e) => sum + (e.duration_minutes ?? 0),
      0
    );
    return { ...g, episodes: eps, totalMinutes };
  });
}

// ── Phase 3: Render report text ───────────────────────────────────────────────

const COL_WIDTH = 40;
const DIVIDER = "\u2500".repeat(COL_WIDTH + 18);

function renderReport(
  groups: GroupResult[],
  periodLabel: string,
  caseMinutes: number,
  adminMinutes: number,
  totalMinutes: number,
  roundTo15: boolean
): string {
  // If roundTo15, round each episode's duration for display only
  function displayMin(raw: number): number {
    if (!roundTo15) return raw;
    return Math.round(raw / 15) * 15;
  }

  function groupDisplayTotal(g: GroupResult): number {
    if (!roundTo15) return g.totalMinutes;
    return g.episodes.reduce(
      (s, ep) => s + displayMin(ep.duration_minutes ?? 0),
      0
    );
  }

  const displayCaseMinutes = groups
    .filter((g) => !g.is_administrative)
    .reduce((s, g) => s + groupDisplayTotal(g), 0);
  const displayAdminMinutes = groups
    .filter((g) => g.is_administrative)
    .reduce((s, g) => s + groupDisplayTotal(g), 0);
  const displayTotalMinutes = displayCaseMinutes + displayAdminMinutes;

  // Suppress unused vars when roundTo15 is false
  void caseMinutes;
  void adminMinutes;
  void totalMinutes;

  const lines: string[] = [];

  // Header
  lines.push(`Reporting period: ${periodLabel}`);
  lines.push("");

  // Summary table
  lines.push(`${"MATTER/PROJECT".padEnd(COL_WIDTH)}TIME`);
  lines.push("");

  const caseGroups = groups.filter((g) => !g.is_administrative);
  for (const g of caseGroups) {
    lines.push(
      `${g.title.padEnd(COL_WIDTH)}${fmtDur(groupDisplayTotal(g))}`
    );
  }

  lines.push(DIVIDER);
  lines.push(
    `${"Total case/project time".padEnd(COL_WIDTH)}${fmtDur(displayCaseMinutes)}`
  );

  const adminGroups = groups.filter((g) => g.is_administrative);
  if (adminGroups.length > 0) {
    lines.push("");
    lines.push(
      `${"Administrative work".padEnd(COL_WIDTH)}${fmtDur(displayAdminMinutes)}`
    );
    lines.push(DIVIDER);
    lines.push(
      `${"Total administrative time".padEnd(COL_WIDTH)}${fmtDur(displayAdminMinutes)}`
    );
  }

  lines.push(DIVIDER);
  lines.push(
    `${"Total recorded time".padEnd(COL_WIDTH)}${fmtDur(displayTotalMinutes)}`
  );

  // Detail sections
  for (const g of groups) {
    if (g.episodes.length === 0) continue;
    lines.push("");
    lines.push("");
    lines.push(`${g.title.toUpperCase()} \u2014 ${fmtDur(groupDisplayTotal(g))}`);

    // Group episodes by day (UTC date)
    const dayMap = new Map<string, Episode[]>();
    const sortedEps = [...g.episodes].sort((a, b) =>
      a.started_at.localeCompare(b.started_at)
    );
    for (const ep of sortedEps) {
      const dayKey = ep.started_at.slice(0, 10);
      if (!dayMap.has(dayKey)) dayMap.set(dayKey, []);
      dayMap.get(dayKey)!.push(ep);
    }

    for (const [dayKey, dayEps] of [...dayMap.entries()].sort()) {
      lines.push("");
      lines.push(fmtDateLong(dayKey));
      for (const ep of dayEps) {
        const start = fmtTime(ep.started_at);
        const end = fmtTime(ep.ended_at);
        const dur = fmtDur(displayMin(ep.duration_minutes ?? 0));
        lines.push(`  ${start}\u2013${end} (${dur})`);
        const obs = (ep.key_observations as KeyObservation[])
          .map((o) => o.text)
          .filter(Boolean)
          .join(". ");
        if (obs) {
          lines.push(`  ${obs}`);
        }
      }
    }
  }

  if (roundTo15) {
    lines.push("");
    lines.push("(Durations rounded to nearest 15 min)");
  }

  return lines.join("\n");
}

// ── Episode summary for Claude grouping prompt ────────────────────────────────

function episodeSummary(ep: Episode): string {
  const obs = (ep.key_observations as KeyObservation[])
    .map((o) => `  - ${o.text}`)
    .join("\n");
  return [
    `id: ${ep.id}`,
    `case_name: ${ep.case_name}`,
    `work_type: ${ep.work_type ?? "project"}`,
    `duration_minutes: ${ep.duration_minutes}`,
    `started_at: ${ep.started_at}`,
    `observations:\n${obs || "  (none)"}`,
  ].join("\n");
}

// ── GET /api/report ────────────────────────────────────────────────────────────
// Accepts ?id=UUID  OR  ?periodStart=YYYY-MM-DD&periodEnd=YYYY-MM-DD

export async function GET(request: NextRequest) {
  const supabase = await getServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return Response.json({ error: "Unauthorized" }, { status: 401 });

  const params = new URL(request.url).searchParams;
  const id = params.get("id");
  const periodStart = params.get("periodStart");
  const periodEnd = params.get("periodEnd");

  if (!id && (!periodStart || !periodEnd)) {
    return Response.json({ content: null });
  }

  const base = supabase
    .from("weekly_reports")
    .select("id, content, period_label, summary_json, created_at")
    .eq("user_id", user.id);

  const { data } = id
    ? await base.eq("id", id).limit(1).single()
    : await base
        .eq("period_start", periodStart!)
        .eq("period_end", periodEnd!)
        .order("created_at", { ascending: false })
        .limit(1)
        .single();

  return Response.json(data ?? { content: null });
}

// ── POST /api/report ───────────────────────────────────────────────────────────

export async function POST(request: Request) {
  const supabase = await getServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const body = await request.json();

  // Accept new periodStart/periodEnd format; fall back to legacy weekStart/weekEnd
  const periodStart = (
    body.periodStart ??
    body.weekStart ??
    ""
  ).slice(0, 10);
  const periodEnd = (body.periodEnd ?? body.weekEnd ?? "").slice(0, 10);
  const roundTo15: boolean = body.roundTo15 === true;
  const periodLabel: string =
    body.periodLabel ?? buildPeriodLabel(periodStart, periodEnd);

  if (!periodStart || !periodEnd) {
    return Response.json(
      { error: "periodStart and periodEnd are required" },
      { status: 400 }
    );
  }

  // Fetch episodes in the requested date range (inclusive)
  const { data, error } = await supabase
    .from("episodes")
    .select("*")
    .gte("started_at", periodStart + "T00:00:00Z")
    .lte("started_at", periodEnd + "T23:59:59Z")
    .order("started_at", { ascending: true });

  if (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }

  const reportable = ((data as Episode[]) ?? []).filter(
    (ep) =>
      ep.is_reportable !== false &&
      ep.duration_minutes >= 0.5 &&
      ep.key_observations.length > 0 &&
      ep.case_name?.trim()
  );

  if (reportable.length === 0) {
    return Response.json({ error: "no_episodes" }, { status: 422 });
  }

  // ── Phase 1: Claude groups episodes (JSON only, no math) ──────────────────

  const episodesSummary = reportable.map(episodeSummary).join("\n\n---\n\n");

  const groupingPrompt = `You are grouping work episodes for a lawyer's timesheet.

Return JSON only — an array of groups:
[
  {
    "title": "Franklin Audit",
    "is_administrative": false,
    "episode_ids": ["uuid1", "uuid2"]
  }
]

Rules:
- Title must come from the actual work (client name, matter name, project name, or honest description like "Review of disputed payment records").
- NEVER use preset terms: Legal Research, Document Review, Case Management, Client Communication, Drafting, General Legal Work, Other Legal Activity, Administrative Activity.
- "Administrative work" is the ONLY administrative bucket. No sub-categories.
- One group per distinct body of work.
- If a real matter name is not supported by the evidence, describe the work honestly and specifically.
- Group episodes that clearly belong to the same matter or project, even if they have slightly different case_names.
- Episodes with work_type="administrative" should go in the "Administrative work" group (is_administrative: true).
- Every episode_id must appear in exactly one group.
- Return ONLY the JSON array. No explanation, no markdown fences.

Episodes:
${episodesSummary}`;

  let claudeGroups: ClaudeGroup[];
  try {
    const client = new Anthropic();
    const message = await client.messages.create({
      model: "claude-opus-4-6",
      max_tokens: 2048,
      messages: [{ role: "user", content: groupingPrompt }],
    });
    const raw =
      message.content[0].type === "text" ? message.content[0].text : "[]";
    // Strip any accidental markdown fences
    const cleaned = raw
      .replace(/^```(?:json)?\s*/i, "")
      .replace(/\s*```\s*$/i, "")
      .trim();
    claudeGroups = JSON.parse(cleaned);
    if (!Array.isArray(claudeGroups)) throw new Error("Expected JSON array");
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return Response.json(
      { error: `Grouping failed: ${msg}` },
      { status: 500 }
    );
  }

  // ── Phase 2: TypeScript calculates all totals (from actual data) ───────────

  const groups = buildGroups(claudeGroups, reportable);

  const caseMinutes = groups
    .filter((g) => !g.is_administrative)
    .reduce((s, g) => s + g.totalMinutes, 0);
  const adminMinutes = groups
    .filter((g) => g.is_administrative)
    .reduce((s, g) => s + g.totalMinutes, 0);
  const totalMinutes = caseMinutes + adminMinutes;

  // ── Phase 3: Render report text (rounded for display if requested) ──────────

  const report = renderReport(
    groups,
    periodLabel,
    caseMinutes,
    adminMinutes,
    totalMinutes,
    roundTo15
  );

  // Summary JSON stores actual (unrounded) totals
  const summaryJson: ReportSummary = {
    periodLabel,
    groups: groups.map((g) => ({
      title: g.title,
      is_administrative: g.is_administrative,
      totalMinutes: g.totalMinutes,
      episode_ids: g.episode_ids,
    })),
    caseMinutes,
    adminMinutes,
    totalMinutes,
  };

  // Always INSERT new row (never update)
  let savedId: string | null = null;
  try {
    const { data: savedReport, error: saveErr } = await supabase
      .from("weekly_reports")
      .insert({
        user_id: user.id,
        week_start: periodStart,
        week_end: periodEnd,
        period_start: periodStart,
        period_end: periodEnd,
        period_label: periodLabel,
        source_episode_ids: reportable.map((e) => e.id),
        summary_json: summaryJson,
        content: report,
        version: 1,
      })
      .select("id")
      .single();
    if (saveErr) {
      console.error("[report] failed to save to DB:", saveErr);
    } else {
      savedId = savedReport?.id ?? null;
    }
  } catch (saveErr) {
    // Non-fatal: report still returned to client even if DB write fails
    console.error("[report] failed to save to DB:", saveErr);
  }

  return Response.json({ report, id: savedId });
}
