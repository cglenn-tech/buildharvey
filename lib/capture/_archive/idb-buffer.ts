import type { Episode, KeyObservation } from '@/lib/types'

export type EvidenceBlob = {
  dataUrl: string
  filename: string          // `${episodeId}-${i}.jpg` — assigned once, never changes on retry
  storagePath: string | null  // set after first URL fetch; reused on retry
  uploaded: boolean
  storageConfirmed: boolean
}

export type PendingEpisodeRow = {
  episodeId: string          // keyPath
  episode: Episode
  evidenceBlobs: EvidenceBlob[]
  episodeSaved: boolean
  allScreenshotsSaved: boolean
  retryCount: number
  lastRetryAt: string | null
  failedPermanently: boolean
}

export type SessionMetaRow = {
  sessionId: string
  startedAt: string
  lastFrameAt: string
  lastMeaningfulAt: string | null
}

// EpisodeCandidate referenced in ActiveEpisodeSnapshot
export type CandidateForSnapshot = {
  timestamp: string
  ocrText: string
  screenshot: string | null
  taskDescription: string | null
  suggestedEpisodeName: string | null
  workType: 'project' | 'administrative' | 'not_work' | null
  issueWorkedOn: string | null
  diffScore: number
}

export type ActiveEpisodeSnapshot = {
  sessionId: string
  episode: Episode
  currentCandidates: CandidateForSnapshot[]
  pendingSwitchCandidates: CandidateForSnapshot[]
  lastMeaningfulAt: string
}

const DB_NAME = 'buildharvey-session'
const DB_VERSION = 3

const STORE_PENDING = 'pending-episodes'
const STORE_SESSION_META = 'session-meta'
const STORE_ACTIVE_EPISODE = 'active-episode'

function reqToPromise<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

function txToPromise(tx: IDBTransaction): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
    tx.onabort = () => reject(tx.error ?? new Error('Transaction aborted'))
  })
}

function openDB(): Promise<IDBDatabase> {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)

    req.onupgradeneeded = (event: IDBVersionChangeEvent) => {
      const db = (event.target as IDBOpenDBRequest).result
      const oldVersion = event.oldVersion

      // v1: create pending-episodes
      if (oldVersion < 1) {
        db.createObjectStore(STORE_PENDING, { keyPath: 'episodeId' })
      }

      // v2: create session-meta (out-of-line key)
      if (oldVersion < 2) {
        db.createObjectStore(STORE_SESSION_META)
      }

      // v3: create active-episode (out-of-line key)
      if (oldVersion < 3) {
        if (!db.objectStoreNames.contains(STORE_ACTIVE_EPISODE)) {
          db.createObjectStore(STORE_ACTIVE_EPISODE)
        }
      }
    }

    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
    req.onblocked = () => reject(new Error('IndexedDB open blocked'))
  })
}

// ---------------------------------------------------------------------------
// Pending episodes
// ---------------------------------------------------------------------------

export async function putPendingEpisode(row: PendingEpisodeRow): Promise<void> {
  const db = await openDB()
  const tx = db.transaction(STORE_PENDING, 'readwrite')
  const store = tx.objectStore(STORE_PENDING)
  store.put(row)
  await txToPromise(tx)
  db.close()
}

export async function getPendingEpisodes(): Promise<PendingEpisodeRow[]> {
  const db = await openDB()
  const tx = db.transaction(STORE_PENDING, 'readonly')
  const store = tx.objectStore(STORE_PENDING)
  const result = await reqToPromise(store.getAll())
  db.close()
  return result
}

export async function updatePendingEpisode(
  episodeId: string,
  patch: Partial<PendingEpisodeRow>,
): Promise<void> {
  const db = await openDB()
  const tx = db.transaction(STORE_PENDING, 'readwrite')
  const store = tx.objectStore(STORE_PENDING)
  const existing: PendingEpisodeRow | undefined = await reqToPromise(store.get(episodeId))
  if (existing === undefined) {
    tx.abort()
    db.close()
    return
  }
  const updated: PendingEpisodeRow = { ...existing, ...patch, episodeId }
  store.put(updated)
  await txToPromise(tx)
  db.close()
}

export async function deletePendingEpisode(episodeId: string): Promise<void> {
  const db = await openDB()
  const tx = db.transaction(STORE_PENDING, 'readwrite')
  const store = tx.objectStore(STORE_PENDING)
  store.delete(episodeId)
  await txToPromise(tx)
  db.close()
}

export async function clearPendingEpisodes(): Promise<void> {
  const db = await openDB()
  const tx = db.transaction(STORE_PENDING, 'readwrite')
  const store = tx.objectStore(STORE_PENDING)
  store.clear()
  await txToPromise(tx)
  db.close()
}

// ---------------------------------------------------------------------------
// Session meta
// ---------------------------------------------------------------------------

export async function setSessionMeta(meta: SessionMetaRow): Promise<void> {
  const db = await openDB()
  const tx = db.transaction(STORE_SESSION_META, 'readwrite')
  const store = tx.objectStore(STORE_SESSION_META)
  store.put(meta, 'current')
  await txToPromise(tx)
  db.close()
}

export async function getSessionMeta(): Promise<SessionMetaRow | null> {
  const db = await openDB()
  const tx = db.transaction(STORE_SESSION_META, 'readonly')
  const store = tx.objectStore(STORE_SESSION_META)
  const result: SessionMetaRow | undefined = await reqToPromise(store.get('current'))
  db.close()
  return result ?? null
}

export async function clearSessionMeta(): Promise<void> {
  const db = await openDB()
  const tx = db.transaction(STORE_SESSION_META, 'readwrite')
  const store = tx.objectStore(STORE_SESSION_META)
  store.delete('current')
  await txToPromise(tx)
  db.close()
}

// ---------------------------------------------------------------------------
// Active episode snapshot (crash recovery)
// ---------------------------------------------------------------------------

export async function setActiveEpisodeSnapshot(snap: ActiveEpisodeSnapshot): Promise<void> {
  const db = await openDB()
  const tx = db.transaction(STORE_ACTIVE_EPISODE, 'readwrite')
  const store = tx.objectStore(STORE_ACTIVE_EPISODE)
  store.put(snap, 'current')
  await txToPromise(tx)
  db.close()
}

export async function getActiveEpisodeSnapshot(): Promise<ActiveEpisodeSnapshot | null> {
  const db = await openDB()
  const tx = db.transaction(STORE_ACTIVE_EPISODE, 'readonly')
  const store = tx.objectStore(STORE_ACTIVE_EPISODE)
  const result: ActiveEpisodeSnapshot | undefined = await reqToPromise(store.get('current'))
  db.close()
  return result ?? null
}

export async function clearActiveEpisodeSnapshot(): Promise<void> {
  const db = await openDB()
  const tx = db.transaction(STORE_ACTIVE_EPISODE, 'readwrite')
  const store = tx.objectStore(STORE_ACTIVE_EPISODE)
  store.delete('current')
  await txToPromise(tx)
  db.close()
}
