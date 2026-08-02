/**
 * GET /api/screenshots/upload-url?episode_id=...&filename=...
 *
 * Device token required. Returns a signed Supabase Storage upload URL
 * scoped to this device's user and episode.
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

export async function GET(request: NextRequest) {
  const device = await getDeviceFromToken(
    request.headers.get("authorization")
  );
  if (!device) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const url = new URL(request.url);
  const episodeId = url.searchParams.get("episode_id");
  const filename = url.searchParams.get("filename");

  if (!episodeId || !filename) {
    return Response.json(
      { error: "episode_id and filename are required" },
      { status: 400 }
    );
  }

  // Verify device owns the episode
  const admin = getAdminClient();
  const { data: episode } = await admin
    .from("episodes")
    .select("id")
    .eq("id", episodeId)
    .eq("user_id", device.user_id)
    .single();

  if (!episode) {
    return Response.json({ error: "Episode not found" }, { status: 404 });
  }

  const storagePath = `${device.user_id}/${episodeId}/${filename}`;

  const { data, error } = await admin.storage
    .from("episode-screenshots")
    .createSignedUploadUrl(storagePath);

  if (error || !data) {
    return Response.json(
      { error: error?.message ?? "Could not create upload URL" },
      { status: 500 }
    );
  }

  return Response.json({ upload_url: data.signedUrl, path: storagePath });
}
