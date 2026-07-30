import Anthropic from "@anthropic-ai/sdk";
import { getSupabaseClient } from "@/lib/supabase";
import type { Episode, KeyObservation } from "@/lib/types";

export async function POST(request: Request) {
  const { weekStart, weekEnd } = await request.json();

  if (!weekStart || !weekEnd) {
    return Response.json(
      { error: "weekStart and weekEnd are required" },
      { status: 400 }
    );
  }

  // Fetch every episode in the requested date range
  const supabase = getSupabaseClient();
  const { data, error } = await supabase
    .from("episodes")
    .select("*")
    .gte("started_at", weekStart)
    .lte("started_at", weekEnd)
    .order("started_at", { ascending: true });

  if (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }

  const episodes = (data as Episode[]) ?? [];

  if (episodes.length === 0) {
    return Response.json({
      report: "No work episodes found for this period.",
    });
  }

  const context = episodes.map(formatEpisode).join("\n\n---\n\n");

  let report: string;
  try {
    const client = new Anthropic();
    const message = await client.messages.create({
      model: "claude-opus-4-6",
      max_tokens: 4096,
      messages: [
        {
          role: "user",
          content: `You are generating a professional weekly work report for a knowledge worker (attorney, appraiser, accountant, or consultant).

Below are structured work episodes from the week. Each episode represents work done on one case or matter.

Your task: generate a clean, professional report with one entry per episode. Use the format shown exactly.

Format for each episode:
---
Case: [case name]
Issue Worked On: [one-line description of the issue or subject matter]
Tasks Completed:
• [task 1]
• [task 2]
• [task 3]
Time: [X.XX hours]
---

Rules:
- "Issue Worked On" should be a concise professional description inferred from the key observations.
- "Tasks Completed" should be professional work descriptions, not app names or file names.
  Good: "Reviewed appraisal documents", "Drafted response letter", "Compared valuation materials"
  Bad: "Opened Microsoft Word", "Used Preview", "Browsed google.com"
- Convert duration_minutes to hours (e.g. 90 min = 1.50 hours). Round to nearest 0.25.
- Merge episodes with the same case name — combine their observations and sum their duration.
- List "Administrative" last if present.
- Do not add commentary before or after the report entries.
- Do not invent work that is not supported by the observations.

Work Episodes:

${context}`,
        },
      ],
    });
    report = message.content[0].type === "text" ? message.content[0].text : "";
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return Response.json({ error: `AI report generation failed: ${msg}` }, { status: 500 });
  }

  return Response.json({ report });
}

function formatEpisode(ep: Episode): string {
  const obs = ep.key_observations
    .map((o: KeyObservation) => `  - ${o.text}`)
    .join("\n");

  return [
    `Case: ${ep.case_name}`,
    `Duration: ${ep.duration_minutes} minutes`,
    `Started: ${ep.started_at}`,
    `Ended: ${ep.ended_at}`,
    `Key observations:\n${obs || "  (no observations recorded)"}`,
  ].join("\n");
}
