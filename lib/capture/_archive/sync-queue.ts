import { getPendingEpisodes, updatePendingEpisode, deletePendingEpisode } from './idb-buffer'
import type { EvidenceBlob } from './idb-buffer'
import type { Episode } from '@/lib/types'

export type DrainResult = {
  syncedEpisodes: Episode[]
  remainingCount: number
  permanentlyFailedCount: number
}

function backoff(retryCount: number): number {
  return Math.min(Math.pow(2, retryCount) * 5_000, 5 * 60_000)
}

export async function drainSyncQueue(): Promise<DrainResult> {
  const rows = await getPendingEpisodes()
  const synced: Episode[] = []

  for (const row of rows) {
    if (row.episodeSaved && row.allScreenshotsSaved) continue
    if (row.failedPermanently) continue
    if (
      row.lastRetryAt !== null &&
      Date.now() < Date.parse(row.lastRetryAt) + backoff(row.retryCount)
    ) {
      continue
    }

    try {
      if (!row.episodeSaved) {
        const res = await fetch('/api/episodes/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(row.episode),
        })
        if (!res.ok) {
          throw new Error(`episode save failed: ${res.status}`)
        }
        await updatePendingEpisode(row.episodeId, { episodeSaved: true })
        row.episodeSaved = true
      }

      const blobs: EvidenceBlob[] = row.evidenceBlobs

      for (const blob of blobs) {
        if (blob.storageConfirmed) continue

        // Always fetch a fresh signed upload URL (signed URLs expire)
        const urlRes = await fetch(
          `/api/screenshots/session-upload-url?episode_id=${encodeURIComponent(row.episodeId)}&filename=${encodeURIComponent(blob.filename)}`
        )
        if (!urlRes.ok) {
          throw new Error(`upload-url fetch failed: ${urlRes.status}`)
        }
        const { upload_url, path } = (await urlRes.json()) as {
          upload_url: string
          path: string
        }

        // Persist the storage path on first acquisition so retries can skip URL derivation
        if (blob.storagePath === null) {
          blob.storagePath = path
        }

        const blobData = await fetch(blob.dataUrl).then((r) => r.blob())
        const putRes = await fetch(upload_url, {
          method: 'PUT',
          // The signed URL already includes auth — do NOT send Authorization header
          headers: { 'Content-Type': 'image/jpeg' },
          body: blobData,
        })
        if (!putRes.ok) {
          throw new Error(`storage PUT failed: ${putRes.status}`)
        }

        const confirmRes = await fetch('/api/screenshots/session-confirm', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ episode_id: row.episodeId, path: blob.storagePath }),
        })
        if (!confirmRes.ok) {
          throw new Error(`confirm failed: ${confirmRes.status}`)
        }

        blob.uploaded = true
        blob.storageConfirmed = true
      }

      await updatePendingEpisode(row.episodeId, { evidenceBlobs: blobs })
      row.evidenceBlobs = blobs

      const allDone =
        row.episodeSaved && row.evidenceBlobs.every((b) => b.storageConfirmed)

      if (allDone) {
        await deletePendingEpisode(row.episodeId)
        synced.push(row.episode)
      }
    } catch {
      const nextRetryCount = row.retryCount + 1
      await updatePendingEpisode(row.episodeId, {
        retryCount: nextRetryCount,
        lastRetryAt: new Date().toISOString(),
        ...(nextRetryCount >= 10 ? { failedPermanently: true } : {}),
      })
    }
  }

  const remaining = await getPendingEpisodes()

  return {
    syncedEpisodes: synced,
    remainingCount: remaining.filter(
      (r) => !r.failedPermanently && (!r.episodeSaved || !r.allScreenshotsSaved)
    ).length,
    permanentlyFailedCount: remaining.filter((r) => r.failedPermanently).length,
  }
}
