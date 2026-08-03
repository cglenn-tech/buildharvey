import { DIFF_THRESHOLD } from './constants'

export { DIFF_THRESHOLD }

/**
 * Fast pixel-sampled frame diff. Samples every 8th pixel (RGBA).
 * Returns 0–1 (fraction of sampled pixels that changed by > 30 units).
 */
export function frameDiff(a: ImageData, b: ImageData): number {
  if (a.width !== b.width || a.height !== b.height) return 1
  const step = 4 * 8  // every 8th pixel, 4 bytes RGBA
  let diff = 0, total = 0
  for (let i = 0; i < a.data.length; i += step) {
    const d = Math.abs(a.data[i] - b.data[i])
            + Math.abs(a.data[i + 1] - b.data[i + 1])
            + Math.abs(a.data[i + 2] - b.data[i + 2])
    if (d > 30) diff++
    total++
  }
  return total === 0 ? 0 : diff / total
}

/**
 * Word-set Jaccard distance between two OCR text strings.
 * Returns 0 (identical) to 1 (completely different).
 */
export function textJaccard(a: string, b: string): number {
  if (a === b) return 0
  if (!a || !b) return 1
  const aW = new Set(a.toLowerCase().match(/\w+/g) ?? [])
  const bW = new Set(b.toLowerCase().match(/\w+/g) ?? [])
  const inter = [...aW].filter(w => bW.has(w)).length
  const union = new Set([...aW, ...bW]).size
  return union === 0 ? 0 : 1 - inter / union
}

/**
 * Normalize a project title for aggregation comparisons only.
 * Trims, collapses repeated whitespace, lowercases.
 * Returns original for display; use this only as a map key.
 */
export function normalizeProjectKey(title: string): string {
  return title.trim().replace(/\s+/g, ' ').toLowerCase()
}
