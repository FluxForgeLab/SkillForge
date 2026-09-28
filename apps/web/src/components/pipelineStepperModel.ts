import type { TraceEventWire } from '@/hooks/useEvents'

/** UI step labels for the Skill Build Pipeline (architecture §10.1 / demo script). */
export const PIPELINE_STEPS = [
  '解析',
  '抽取',
  '规格',
  '技能',
  '测试',
  '校验',
] as const

export type PipelineStepLabel = (typeof PIPELINE_STEPS)[number]

export type StepVisualStatus = 'pending' | 'active' | 'complete' | 'failed'

export type PipelineStepperState = {
  /** Per-step visual status, same order as PIPELINE_STEPS. */
  statuses: StepVisualStatus[]
  /** Index of the current step, or -1 when fully idle. */
  activeIndex: number
  failed: boolean
}

/** PipelineState values emitted as workflow_started.name. */
export const PIPELINE_STATE_NAMES = [
  'INGESTED',
  'EXTRACTED',
  'DRAFTED',
  'VALIDATING',
  'CANDIDATE',
  'EVALUATING',
  'PASSED',
  'FAILED',
  'APPROVED',
  'PUBLISHED',
] as const

export type PipelineStateName = (typeof PIPELINE_STATE_NAMES)[number]

const PIPELINE_STATE_SET = new Set<string>(PIPELINE_STATE_NAMES)

/**
 * Map orchestrator PipelineState → stepper index.
 * FAILED is not a success step; callers handle it separately.
 */
export function pipelineStateToStepIndex(name: string): number | null {
  switch (name) {
    case 'INGESTED':
      return 0
    case 'EXTRACTED':
      return 1
    case 'DRAFTED':
      return 2
    case 'VALIDATING':
    case 'CANDIDATE':
      return 3
    case 'EVALUATING':
      return 4
    case 'PASSED':
    case 'APPROVED':
    case 'PUBLISHED':
      return 5
    default:
      return null
  }
}

export function isPipelineWorkflowEvent(
  event: TraceEventWire,
): event is TraceEventWire & { name: PipelineStateName } {
  return (
    event.type === 'workflow_started' &&
    event.name !== null &&
    PIPELINE_STATE_SET.has(event.name)
  )
}

function idleState(): PipelineStepperState {
  return {
    statuses: PIPELINE_STEPS.map(() => 'pending'),
    activeIndex: -1,
    failed: false,
  }
}

function statusesForActive(activeIndex: number): StepVisualStatus[] {
  return PIPELINE_STEPS.map((_, i) => {
    if (i < activeIndex) return 'complete'
    if (i === activeIndex) return 'active'
    return 'pending'
  })
}

function statusesAllComplete(): StepVisualStatus[] {
  return PIPELINE_STEPS.map(() => 'complete')
}

/**
 * Derive stepper UI from TraceEventWire stream (newest-first or any order).
 * Only workflow_started events whose name is a PipelineState value advance steps.
 * FAILED marks the current step failed and never treats Validate as success.
 */
export function derivePipelineStepperState(
  events: TraceEventWire[],
): PipelineStepperState {
  const pipeline = events
    .filter(isPipelineWorkflowEvent)
    .slice()
    .sort((a, b) => a.timestamp.localeCompare(b.timestamp))

  if (pipeline.length === 0) {
    return idleState()
  }

  let activeIndex = -1
  let failed = false
  let terminalSuccess = false

  for (const event of pipeline) {
    const name = event.name

    if (name === 'FAILED') {
      failed = true
      terminalSuccess = false
      const previous =
        typeof event.output.previous === 'string' ? event.output.previous : null
      const fromPrevious =
        previous !== null ? pipelineStateToStepIndex(previous) : null
      const failAt =
        fromPrevious !== null
          ? fromPrevious
          : activeIndex >= 0
            ? activeIndex
            : 4
      activeIndex = failAt
      continue
    }

    const index = pipelineStateToStepIndex(name)
    if (index === null) {
      continue
    }

    failed = false
    activeIndex = index
    terminalSuccess =
      name === 'PASSED' || name === 'APPROVED' || name === 'PUBLISHED'
  }

  if (failed) {
    const statuses = PIPELINE_STEPS.map((_, i) => {
      if (i < activeIndex) return 'complete'
      if (i === activeIndex) return 'failed'
      return 'pending'
    })
    return { statuses, activeIndex, failed: true }
  }

  if (activeIndex < 0) {
    return idleState()
  }

  if (terminalSuccess) {
    return {
      statuses: statusesAllComplete(),
      activeIndex: 5,
      failed: false,
    }
  }

  return {
    statuses: statusesForActive(activeIndex),
    activeIndex,
    failed: false,
  }
}

/**
 * Deterministic idle sample: no PipelineState events, so the stepper stays
 * pending and remains visible with the WebSocket offline.
 */
export const MOCK_PIPELINE_EVENTS: TraceEventWire[] = []
