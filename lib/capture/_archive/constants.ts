/** All tunable capture constants in one place. */

export const FRAME_INTERVAL_MS = 5_000          // target sample interval
export const MIN_ANALYSIS_INTERVAL_MS = 20_000  // min time between Claude calls (20s → ≤180 calls/hr at rest)
export const INACTIVITY_THRESHOLD_MS = 5 * 60 * 1000  // 5 min → close Episode
export const DIFF_THRESHOLD = 0.02              // 2% pixel change required to proceed
export const OCR_DIFF_THRESHOLD = 0.20         // 20% Jaccard text change
export const STRONG_CHANGE_THRESHOLD = 0.50    // 50% text change → bypass analysis interval
export const SWITCH_SIGNALS_REQUIRED = 2        // consecutive end_and_start to confirm switch
export const MAX_EVIDENCE_CANDIDATES = 6        // bounded evidence candidate buffer per episode
export const MAX_EVIDENCE_SCREENSHOTS = 3       // evidence screenshots saved per episode
export const MAX_CONTEXT_OBSERVATIONS = 5       // recent obs sent to analyze endpoint
export const OCR_TEXT_MAX_CHARS = 3_000         // truncate before sending to server
export const CANVAS_WIDTH = 1_280
export const CANVAS_HEIGHT = 720
export const ANALYSIS_TIMEOUT_MS = 10_000       // abort Claude call if no response
export const MAX_PENDING_ANALYSES = 20          // max queued offline analyses before dropping oldest
