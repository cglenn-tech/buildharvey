/**
 * GET /api/screenshots/[episodeId]
 *
 * User session required. Returns signed read URLs for all screenshots
 * belonging to the authenticated user's episode.
 * Signed URLs expire in 5 minutes.
 */
import type { NextRequest } from "next/server";
import { getAdminClient } from "@/lib/supabase-admin";
import { getServerClient } from "@/lib/supabase-server";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ episodeId: string }> }
) {
  const { episodeId } = await params;

  const supabase = await getServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const admin = getAdminClient();

  // Verify user owns the episode via RLS-equivalent check
  const { data: episode } = await admin
    .from("episodes")
    .select("id")
    .eq("id", episodeId)
    .eq("user_id", user.id)
    .single();

  if (!episode) {
    return Response.json({ error: "Episode not found" }, { status: 404 });
  }

  // Fetch screenshot rows for this episode
  const { data: screenshots, error } = await admin
    .from("episode_screenshots")
    .select("id, storage_path")
    .eq("episode_id", episodeId)
    .eq("user_id", user.id)
    .order("uploaded_at", { ascending: true });

  if (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }

  if (!screenshots?.length) {
    return Response.json([]);
  }

  // Generate signed read URLs (5 minute expiry)
  const signed = await Promise.all(
    screenshots.map(async (s) => {
      const { data } = await admin.storage
        .from("episode-screenshots")
        .createSignedUrl(s.storage_path, 300);
      return { id: s.id, signed_url: data?.signedUrl ?? null };
    })
  );

  return Response.json(signed.filter((s) => s.signed_url !== null));
}
