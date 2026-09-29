/**
 * Pure helpers for Judge Mode (/demo): evolve prefill and benchmark assembly
 * from evaluation run payloads returned by existing APIs.
 */

import type { BenchmarkData } from '@/components/benchmarkModel'
import type { TraceEventWire } from '@/hooks/useEvents'

export const FAULT_IDS = [
  'backend_stopped',
  'nginx_wrong_upstream',
  'nginx_bad_config_reload',
] as const

export type FaultId = (typeof FAULT_IDS)[number]

export type FieldMismatchWire = {
  field: string
  expected: unknown
  actual?: unknown
}

/** Matches skillforge.evaluator.assertions.AssertionResult JSON. */
export type AssertionWire = {
  passed: boolean
  mismatches: FieldMismatchWire[]
  forbidden_hits: string[]
}

/** Matches EvolveRequest fields the operator must supply. */
export type EvolveFormState = {
  version: string
  run_id: string
  assertionJson: string
  verifierJson: string
  sourceMapUpdatesJson: string
}

export type EvaluationRunWire = {
  id: string
  skill_version_id: string
  baseline: Record<string, unknown>
  metrics: Record<string, unknown>
  status: string
  started_at: string
  finished_at: string | null
}

export type StepLogEntry = {
  id: string
  step: string
  status: number | null
  detail: string
  at: string
}

export function defaultEvolveForm(): EvolveFormState {
  return {
    version: 'v0.2',
    run_id: '',
    assertionJson: JSON.stringify(
      { passed: false, mismatches: [], forbidden_hits: [] } satisfies AssertionWire,
      null,
      2,
    ),
    verifierJson: '{}',
    sourceMapUpdatesJson: '{}',
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseAssertion(output: Record<string, unknown>): AssertionWire | null {
  if (typeof output.passed !== 'boolean') {
    return null
  }
  const mismatchesRaw = output.mismatches
  const forbiddenRaw = output.forbidden_hits
  const mismatches: FieldMismatchWire[] = []
  if (Array.isArray(mismatchesRaw)) {
    for (const item of mismatchesRaw) {
      if (!isRecord(item) || typeof item.field !== 'string') {
        continue
      }
      mismatches.push({
        field: item.field,
        expected: item.expected,
        actual: item.actual,
      })
    }
  }
  const forbidden_hits = Array.isArray(forbiddenRaw)
    ? forbiddenRaw.filter((x): x is string => typeof x === 'string')
    : []
  return { passed: output.passed, mismatches, forbidden_hits }
}

/**
 * Prefill evolve form from the newest assertion / agent-run events on the wire.
 * Operator can still edit run_id before submit.
 */
export function prefillEvolveFromEvents(
  events: TraceEventWire[],
  previous: EvolveFormState,
): EvolveFormState {
  const assertionEvent = events.find((e) => e.type === 'assertion')
  const agentEvent = events.find(
    (e) =>
      e.run_id &&
      e.type !== 'evaluation_completed' &&
      !e.run_id.startsWith('job_'),
  )
  const run_id =
    assertionEvent?.run_id || agentEvent?.run_id || previous.run_id

  let assertionJson = previous.assertionJson
  if (assertionEvent) {
    const parsed = parseAssertion(assertionEvent.output)
    if (parsed) {
      assertionJson = JSON.stringify(parsed, null, 2)
    }
  }

  let verifierJson = previous.verifierJson
  if (assertionEvent && isRecord(assertionEvent.input)) {
    const expected = assertionEvent.input.expected
    if (isRecord(expected)) {
      // Reconstruct a minimal verifier snapshot from expected + mismatches.
      const assertion = parseAssertion(assertionEvent.output)
      const verifier: Record<string, unknown> = { ...expected }
      if (assertion) {
        for (const mismatch of assertion.mismatches) {
          verifier[mismatch.field] = mismatch.actual ?? null
        }
      }
      verifierJson = JSON.stringify(verifier, null, 2)
    }
  }

  return {
    ...previous,
    run_id,
    assertionJson,
    verifierJson,
  }
}

/** Build BenchmarkData from GET /api/skills/{id}/evaluations/{run_id} payloads. */
export function buildBenchmarkFromRuns(
  runs: EvaluationRunWire[],
): BenchmarkData | undefined {
  if (runs.length === 0) {
    return undefined
  }

  const byCase = new Map<
    string,
    { control: boolean[]; treatment: boolean[] }
  >()

  for (const run of runs) {
    const caseId = run.metrics.case_id
    if (typeof caseId !== 'string') {
      continue
    }
    const arm = run.baseline.baseline === true ? 'control' : 'treatment'
    const passed = run.metrics.passed === true
    let bucket = byCase.get(caseId)
    if (!bucket) {
      bucket = { control: [], treatment: [] }
      byCase.set(caseId, bucket)
    }
    bucket[arm].push(passed)
  }

  if (byCase.size === 0) {
    return undefined
  }

  const cases = [...byCase.keys()].sort().map((case_id) => {
    const bucket = byCase.get(case_id)!
    const control_success_rate =
      bucket.control.length > 0
        ? bucket.control.filter(Boolean).length / bucket.control.length
        : 0
    const treatment_success_rate =
      bucket.treatment.length > 0
        ? bucket.treatment.filter(Boolean).length / bucket.treatment.length
        : 0
    return {
      case_id,
      name: case_id,
      control_passed: control_success_rate >= 1,
      treatment_passed: treatment_success_rate >= 1,
      control_success_rate,
      treatment_success_rate,
      uplift_pp: (treatment_success_rate - control_success_rate) * 100,
    }
  })

  const controlRates = cases.map((c) => c.control_success_rate)
  const treatmentRates = cases.map((c) => c.treatment_success_rate)
  const control =
    controlRates.reduce((a, b) => a + b, 0) / Math.max(controlRates.length, 1)
  const treatment =
    treatmentRates.reduce((a, b) => a + b, 0) /
    Math.max(treatmentRates.length, 1)

  return {
    task_success_rate: { control, treatment },
    skill_uplift_pp: (treatment - control) * 100,
    cases,
  }
}

export function shortBody(body: string, max = 180): string {
  const trimmed = body.trim()
  if (trimmed.length <= max) {
    return trimmed
  }
  return `${trimmed.slice(0, max)}…`
}

/** Prefer the API error sentence over the raw JSON body. */
export function apiErrorDetail(body: string, max = 240): string {
  const trimmed = body.trim()
  try {
    const parsed: unknown = JSON.parse(trimmed)
    if (
      typeof parsed === 'object' &&
      parsed !== null &&
      'error' in parsed &&
      typeof parsed.error === 'object' &&
      parsed.error !== null &&
      'message' in parsed.error &&
      typeof parsed.error.message === 'string' &&
      parsed.error.message.trim()
    ) {
      return shortBody(parsed.error.message, max)
    }
  } catch {
    // Response body is not JSON.
  }
  return shortBody(trimmed, max)
}
