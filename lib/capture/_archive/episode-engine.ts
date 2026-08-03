import type { Episode, KeyObservation } from '@/lib/types'
import {
  SWITCH_SIGNALS_REQUIRED,
  MAX_EVIDENCE_CANDIDATES,
  MAX_EVIDENCE_SCREENSHOTS,
  INACTIVITY_THRESHOLD_MS,
} from './constants'
import { textJaccard } from './frame-differ'
import type { CandidateForSnapshot, ActiveEpisodeSnapshot } from './idb-buffer'

export type AnalyzeResult = {
  meaningful: boolean
  work_type: 'project' | 'administrative' | 'not_work'
  issue_worked_on: string | null
  task_description: string | null
  episode_action: 'continue' | 'end_and_start' | 'end'
  suggested_episode_name: string | null
}

export type EpisodeCandidate = {
  timestamp: string
  ocrText: string
  screenshot: string | null
  taskDescription: string | null
  suggestedEpisodeName: string | null
  workType: 'project' | 'administrative' | 'not_work' | null
  issueWorkedOn: string | null
  diffScore: number
}

export type FinalizedEpisode = {
  episode: Episode
  selectedScreenshots: string[]  // 1–MAX_EVIDENCE_SCREENSHOTS base64 JPEGs
  evidenceFilenames: string[]    // `${episode.id}-${i}.jpg` for each screenshot
}

function deepCopyEpisode(ep: Episode): Episode {
  return JSON.parse(JSON.stringify(ep))
}

function deepCopyCandidate(c: EpisodeCandidate): EpisodeCandidate {
  return { ...c }
}

export class EpisodeEngine {
  private current: Episode | null = null
  private currentCandidates: EpisodeCandidate[] = []
  private pendingSwitchCandidates: EpisodeCandidate[] = []
  private lastMeaningfulAt: string | null = null
  private switchSignals = 0
  private pendingNewName: string | null = null

  handleAnalysis(result: AnalyzeResult, candidate: EpisodeCandidate): FinalizedEpisode | null {
    if (!result.meaningful) return null

    this.lastMeaningfulAt = candidate.timestamp

    if (result.episode_action === 'end_and_start') {
      this.switchSignals++
      this.pendingNewName = result.suggested_episode_name
      this.pendingSwitchCandidates.push(candidate)

      const nameMatch =
        this.switchSignals === 1 &&
        textJaccard(
          this.current?.case_name ?? '',
          result.suggested_episode_name ?? '',
        ) > 0.8

      const confirmSwitch =
        this.switchSignals >= SWITCH_SIGNALS_REQUIRED || nameMatch

      if (confirmSwitch && this.current !== null) {
        const finalized = this.closeCurrentEpisode()
        this.openNew(result.suggested_episode_name, candidate.timestamp, result.work_type)
        this.currentCandidates = [...this.pendingSwitchCandidates]
        this.pendingSwitchCandidates = []
        this.switchSignals = 0
        return finalized
      }

      if (confirmSwitch && this.current === null) {
        this.openNew(result.suggested_episode_name, candidate.timestamp, result.work_type)
        this.currentCandidates = [...this.pendingSwitchCandidates]
        this.pendingSwitchCandidates = []
        this.switchSignals = 0
        return null
      }

      return null
    }

    if (result.episode_action === 'end') {
      // Reject switch — reattach pending to current before closing
      this.currentCandidates.push(...this.pendingSwitchCandidates)
      this.pendingSwitchCandidates = []
      this.switchSignals = 0

      if (this.current !== null) {
        const finalized = this.closeCurrentEpisode()
        return finalized
      }
      return null
    }

    // 'continue'
    // Reject switch — reattach pending to current
    this.currentCandidates.push(...this.pendingSwitchCandidates)
    this.pendingSwitchCandidates = []
    this.switchSignals = 0

    this.currentCandidates.push(candidate)

    // Trim evidence candidate buffer to MAX_EVIDENCE_CANDIDATES (keep first + most recent)
    const screenshotCount = this.currentCandidates.filter(c => c.screenshot !== null).length
    if (screenshotCount > MAX_EVIDENCE_CANDIDATES) {
      this.trimEvidenceCandidates()
    }

    if (this.current === null) {
      this.openNew(result.suggested_episode_name, candidate.timestamp, result.work_type)
    } else {
      // Update episode with latest data
      if (result.task_description) {
        const obs: KeyObservation = {
          timestamp: candidate.timestamp,
          text: result.task_description,
          task_description: result.task_description,
        }
        this.current.key_observations.push(obs)
      }
      // Update mutable fields (latest wins)
      this.current.work_type =
        result.work_type === 'not_work' ? this.current.work_type : result.work_type
      if (result.issue_worked_on) {
        this.current.issue_worked_on = result.issue_worked_on
      }
    }

    return null
  }

  checkInactivity(nowIso: string): FinalizedEpisode | null {
    if (this.lastMeaningfulAt === null || this.current === null) return null
    const elapsed = Date.parse(nowIso) - Date.parse(this.lastMeaningfulAt)
    if (elapsed < INACTIVITY_THRESHOLD_MS) return null
    // Finalize at lastMeaningfulAt (not nowIso — exclude idle time)
    const finalized = this.closeCurrentEpisode()
    this.current = null
    this.currentCandidates = []
    this.pendingSwitchCandidates = []
    return finalized
    // Work Session stays ACTIVE. New Episode starts on next meaningful frame.
  }

  closeSession(_nowIso: string): FinalizedEpisode | null {
    if (this.current === null) return null
    return this.closeCurrentEpisode()
  }

  getCurrentEpisode(): Episode | null {
    if (this.current === null) return null
    return deepCopyEpisode(this.current)
  }

  getLastMeaningfulAt(): string | null {
    return this.lastMeaningfulAt
  }

  reset(): void {
    this.current = null
    this.currentCandidates = []
    this.pendingSwitchCandidates = []
    this.lastMeaningfulAt = null
    this.switchSignals = 0
    this.pendingNewName = null
  }

  getRecoverySnapshot(sessionId: string): ActiveEpisodeSnapshot | null {
    if (this.current === null || this.lastMeaningfulAt === null) return null

    const toSnapshot = (c: EpisodeCandidate): CandidateForSnapshot => ({
      timestamp: c.timestamp,
      ocrText: c.ocrText,
      screenshot: c.screenshot,
      taskDescription: c.taskDescription,
      suggestedEpisodeName: c.suggestedEpisodeName,
      workType: c.workType,
      issueWorkedOn: c.issueWorkedOn,
      diffScore: c.diffScore,
    })

    return {
      sessionId,
      episode: deepCopyEpisode(this.current),
      currentCandidates: this.currentCandidates.map(toSnapshot),
      pendingSwitchCandidates: this.pendingSwitchCandidates.map(toSnapshot),
      lastMeaningfulAt: this.lastMeaningfulAt,
    }
  }

  restoreRecoverySnapshot(snap: ActiveEpisodeSnapshot): void {
    const fromSnapshot = (c: CandidateForSnapshot): EpisodeCandidate => ({
      timestamp: c.timestamp,
      ocrText: c.ocrText,
      screenshot: c.screenshot,
      taskDescription: c.taskDescription,
      suggestedEpisodeName: c.suggestedEpisodeName,
      workType: c.workType,
      issueWorkedOn: c.issueWorkedOn,
      diffScore: c.diffScore,
    })

    this.current = deepCopyEpisode(snap.episode)
    this.currentCandidates = snap.currentCandidates.map(fromSnapshot)
    this.pendingSwitchCandidates = snap.pendingSwitchCandidates.map(fromSnapshot)
    this.lastMeaningfulAt = snap.lastMeaningfulAt
    this.switchSignals = 0
    this.pendingNewName = null
  }

  private closeCurrentEpisode(): FinalizedEpisode {
    if (this.currentCandidates.length > 0) {
      this.current!.started_at = this.currentCandidates[0].timestamp
    } else {
      this.current!.started_at =
        this.lastMeaningfulAt ?? this.current!.started_at
    }

    this.current!.ended_at = this.lastMeaningfulAt!
    this.current!.duration_minutes =
      (Date.parse(this.current!.ended_at) - Date.parse(this.current!.started_at)) / 60000

    // Evidence selection from candidates WITH screenshots
    const evidence = this.currentCandidates.filter(c => c.screenshot !== null)

    let selected: EpisodeCandidate[]
    if (evidence.length === 0) {
      selected = []
    } else if (evidence.length <= MAX_EVIDENCE_SCREENSHOTS) {
      selected = evidence
    } else {
      const first = evidence[0]
      const middle = evidence[Math.floor(evidence.length / 2)]
      const last = evidence[evidence.length - 1]
      selected = [first, middle, last]

      // Skip near-duplicates: if middle === first (by text), use second-to-last instead
      if (selected[0].ocrText === selected[1].ocrText && evidence.length > 3) {
        selected[1] = evidence[evidence.length - 2]
      }
    }

    const episodeCopy = deepCopyEpisode(this.current!)
    const finalized: FinalizedEpisode = {
      episode: episodeCopy,
      selectedScreenshots: selected.map(c => c.screenshot!),
      evidenceFilenames: selected.map((_, i) => `${this.current!.id}-${i}.jpg`),
    }

    this.current = null
    this.currentCandidates = []
    return finalized
  }

  private openNew(
    name: string | null,
    timestamp: string,
    workType: AnalyzeResult['work_type'],
  ): void {
    const id = crypto.randomUUID()
    this.current = {
      id,
      case_name: name ?? 'Uncategorized work',
      work_type: workType === 'not_work' ? 'project' : workType,
      issue_worked_on: null,
      started_at: timestamp,
      ended_at: timestamp,
      duration_minutes: 0,
      key_observations: [],
      created_at: new Date().toISOString(),
      is_reportable: true,
    }
  }

  private trimEvidenceCandidates(): void {
    // Keep first frame + most recent (MAX_EVIDENCE_CANDIDATES - 1) frames with screenshots
    const withScreenshot = this.currentCandidates
      .map((c, idx) => ({ c, idx }))
      .filter(({ c }) => c.screenshot !== null)

    if (withScreenshot.length <= MAX_EVIDENCE_CANDIDATES) return

    const firstIdx = withScreenshot[0].idx
    // Take last (MAX_EVIDENCE_CANDIDATES - 1) candidates with screenshots
    const keepScreenshotEntries = withScreenshot.slice(
      -(MAX_EVIDENCE_CANDIDATES - 1),
    )
    const keepIndices = new Set<number>([
      firstIdx,
      ...keepScreenshotEntries.map(({ idx }) => idx),
    ])

    // Also keep all candidates without screenshots (they have no screenshots to trim)
    this.currentCandidates = this.currentCandidates.filter(
      (c, idx) => c.screenshot === null || keepIndices.has(idx),
    )
  }
}
