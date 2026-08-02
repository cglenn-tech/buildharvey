/**
 * POST /api/screenshots/confirm
 * Body: { episode_id: string, path: string }
 *
 * Device token required. Inserts an episode_screenshots row after the agent
 * has successfully uploaded the file to Supabase Storage.
 * Returns 409 if a row with the same storage_path already exists (idempotent).
 */
import { createHash } from "crypto";
import type { NextRequest } from "next/server";
import { getAdminClient } from "@/lib/supabase-admin";

async function getDeviceFromToken(authHeader: string | null) {
  if (!authHeader?.startsWith("Bearer ")) return null;
  const rawToken = authHeader.slice(7);
  const tokenHash = createHash("sha256").update(rawToken).digest("hex");

  const admin = getAdminClient();
  const { data: device } = await admin
    .from("devices")
    .select("id, user_id")
    .eq("token_hash", tokenHash)
    .is("revoked_at", null)
    .single();

  return device ?? null;
}

export async function POST(request: NextRequest) {
  const device = await getDeviceFromToken(
    request.headers.get("authorization")
  );
  if (!device) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  let body: { episode_id?: string; path?: string };
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const { episode_id: episodeId, path: storagePath } = body;
  if (!episodeId || !storagePath) {
    return Response.json(
      { error: "episode_id and path are required" },
      { status: 400 }
    );
  }

  const admin = getAdminClient();

  // Verify device owns the episode
  const { data: episode } = await admin
    .from("episodes")
    .select("id")
    .eq("id", episodeId)
    .eq("user_id", device.user_id)
    .single();

  if (!episode) {
    return Response.json({ error: "Episode not found" }, { status: 404 });
  }

  // Idempotency: skip if already recorded
  const { data: existing } = await admin
    .from("episode_screenshots")
    .select("id")
    .eq("storage_path", storagePath)
    .limit(1)
    .single();

  if (existing) {
    return Response.json({ ok: true, duplicate: true }, { status: 409 });
  }

  const { error } = await admin.from("episode_screenshots").insert({
    episode_id: episodeId,
    user_id: device.user_id,
    storage_path: storagePath,
  });

  if (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }

  return Response.json({ ok: true });
}
