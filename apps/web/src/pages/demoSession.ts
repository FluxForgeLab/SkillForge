/**
 * Demo page session. Survives leaving /demo and reloading the tab.
 * Cleared only when the browser tab closes.
 */

import type { BenchmarkData } from '@/components/benchmarkModel'
import {
  emptySkillDiffFailure,
  type SkillDiffFailure,
  type SkillDiffPayload,
} from '@/components/skillDiffModel'
import type { TraceEventWire } from '@/hooks/useEvents'
import {
  FAULT_IDS,
  defaultEvolveForm,
  type EvolveFormState,
  type FaultId,
  type StepLogEntry,
} from '@/pages/demoJudgeModel'

const STORAGE_KEY = 'skillforge.demo.v1'
const HIDDEN_EVENT_TYPES = new Set(['model_request', 'model_response'])

export type DemoSource = {
  id: string
  project_id: string
  filename: string
  sha256: string
  version: string
  parser: string
  created_at: string
}

export type DemoSession = {
  projectId: string
  projectName: string
  projectDescription: string
  sources: DemoSource[]
  knowledgeCount: number | null
  skillId: string
  versionId: string
  skillName: string
  skillDescription: string
  triggersText: string
  faultId: FaultId
  evalJobId: string | null
  benchmark: BenchmarkData | undefined
  approver: string
  evolveForm: EvolveFormState
  skillDiff: SkillDiffPayload | null
  skillDiffFailure: SkillDiffFailure
  stepLog: StepLogEntry[]
  handledEvalJobIds: string[]
  events: TraceEventWire[]
}

export function defaultDemoSession(): DemoSession {
  return {
    projectId: '',
    projectName: 'service-recovery-demo',
    projectDescription: '现场演示项目',
    sources: [],
    knowledgeCount: null,
    skillId: '',
    versionId: '',
    skillName: 'service-recovery',
    skillDescription: '从常见故障中恢复 nginx 上游和后端',
    triggersText: 'HTTP 502\nbackend unavailable\nhealth check failed',
    faultId: 'backend_stopped',
    evalJobId: null,
    benchmark: undefined,
    approver: 'judge',
    evolveForm: defaultEvolveForm(),
    skillDiff: null,
    skillDiffFailure: emptySkillDiffFailure(),
    stepLog: [],
    handledEvalJobIds: [],
    events: [],
  }
}

export function loadDemoSession(): DemoSession {
  const fallback = defaultDemoSession()
  if (typeof sessionStorage === 'undefined') {
    return fallback
  }
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) {
      return fallback
    }
    const parsed: unknown = JSON.parse(raw)
    if (!isRecord(parsed)) {
      return fallback
    }
    return mergeSession(fallback, parsed)
  } catch {
    return fallback
  }
}

export function saveDemoSession(session: DemoSession): void {
  if (typeof sessionStorage === 'undefined') {
    return
  }
  const stored: DemoSession = {
    ...session,
    events: session.events
      .filter((event) => !HIDDEN_EVENT_TYPES.has(event.type))
      .slice(0, 80),
    stepLog: session.stepLog.slice(0, 40),
  }
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(stored))
}

export function readRememberedSkillId(): string {
  return loadDemoSession().skillId.trim()
}

function mergeSession(
  fallback: DemoSession,
  parsed: Record<string, unknown>,
): DemoSession {
  const faultId = parsed.faultId
  return {
    ...fallback,
    projectId: stringOr(parsed.projectId, fallback.projectId),
    projectName: stringOr(parsed.projectName, fallback.projectName),
    projectDescription: stringOr(
      parsed.projectDescription,
      fallback.projectDescription,
    ),
    sources: sourcesOr(parsed.sources),
    knowledgeCount: numberOrNull(parsed.knowledgeCount),
    skillId: stringOr(parsed.skillId, ''),
    versionId: stringOr(parsed.versionId, ''),
    skillName: stringOr(parsed.skillName, fallback.skillName),
    skillDescription: stringOr(
      parsed.skillDescription,
      fallback.skillDescription,
    ),
    triggersText: stringOr(parsed.triggersText, fallback.triggersText),
    faultId:
      typeof faultId === 'string' &&
      (FAULT_IDS as readonly string[]).includes(faultId)
        ? (faultId as FaultId)
        : fallback.faultId,
    evalJobId:
      typeof parsed.evalJobId === 'string' ? parsed.evalJobId : null,
    benchmark: isRecord(parsed.benchmark)
      ? (parsed.benchmark as BenchmarkData)
      : undefined,
    approver: stringOr(parsed.approver, fallback.approver),
    evolveForm: evolveFormOr(parsed.evolveForm, fallback.evolveForm),
    skillDiff: skillDiffOr(parsed.skillDiff),
    skillDiffFailure: failureOr(parsed.skillDiffFailure),
    stepLog: stepLogOr(parsed.stepLog),
    handledEvalJobIds: stringList(parsed.handledEvalJobIds),
    events: eventsOr(parsed.events),
  }
}

function evolveFormOr(value: unknown, fallback: EvolveFormState): EvolveFormState {
  if (!isRecord(value)) {
    return fallback
  }
  return {
    version: stringOr(value.version, fallback.version),
    run_id: stringOr(value.run_id, fallback.run_id),
    assertionJson: stringOr(value.assertionJson, fallback.assertionJson),
    verifierJson: stringOr(value.verifierJson, fallback.verifierJson),
    sourceMapUpdatesJson: stringOr(
      value.sourceMapUpdatesJson,
      fallback.sourceMapUpdatesJson,
    ),
  }
}

function skillDiffOr(value: unknown): SkillDiffPayload | null {
  if (!isRecord(value) || typeof value.version_id !== 'string') {
    return null
  }
  return {
    version_id: value.version_id,
    parent_version_id:
      typeof value.parent_version_id === 'string'
        ? value.parent_version_id
        : null,
    has_parent: value.has_parent === true,
    diff: stringOr(value.diff, ''),
  }
}

function failureOr(value: unknown): SkillDiffFailure {
  const empty = emptySkillDiffFailure()
  if (!isRecord(value)) {
    return empty
  }
  return {
    failure_class:
      typeof value.failure_class === 'string' ? value.failure_class : null,
    symptom: typeof value.symptom === 'string' ? value.symptom : null,
    evidence: stringList(value.evidence),
    source_support: stringList(value.source_support),
  }
}

function sourcesOr(value: unknown): DemoSource[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.filter(isSource)
}

function isSource(value: unknown): value is DemoSource {
  if (!isRecord(value)) {
    return false
  }
  return (
    typeof value.id === 'string' &&
    typeof value.project_id === 'string' &&
    typeof value.filename === 'string' &&
    typeof value.sha256 === 'string' &&
    typeof value.version === 'string' &&
    typeof value.parser === 'string' &&
    typeof value.created_at === 'string'
  )
}

function stepLogOr(value: unknown): StepLogEntry[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.filter(isStepLog).slice(0, 40)
}

function isStepLog(value: unknown): value is StepLogEntry {
  if (!isRecord(value)) {
    return false
  }
  return (
    typeof value.id === 'string' &&
    typeof value.step === 'string' &&
    (value.status === null || typeof value.status === 'number') &&
    typeof value.detail === 'string' &&
    typeof value.at === 'string'
  )
}

function eventsOr(value: unknown): TraceEventWire[] {
  if (!Array.isArray(value)) {
    return []
  }
  const events: TraceEventWire[] = []
  for (const item of value) {
    const event = eventOr(item)
    if (event) {
      events.push(event)
    }
    if (events.length >= 80) {
      break
    }
  }
  return events
}

function eventOr(value: unknown): TraceEventWire | null {
  if (!isRecord(value)) {
    return null
  }
  if (typeof value.id !== 'string' || typeof value.type !== 'string') {
    return null
  }
  return {
    id: value.id,
    run_id: stringOr(value.run_id, ''),
    type: value.type,
    timestamp: stringOr(value.timestamp, ''),
    stage: typeof value.stage === 'string' ? value.stage : null,
    name: typeof value.name === 'string' ? value.name : null,
    input: isRecord(value.input) ? value.input : {},
    output: isRecord(value.output) ? value.output : {},
    duration_ms: typeof value.duration_ms === 'number' ? value.duration_ms : null,
  }
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.filter((item): item is string => typeof item === 'string')
}

function stringOr(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value : fallback
}

function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' ? value : null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
