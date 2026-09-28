/**
 * Pure helpers for Evaluation Lab (lite): aggregate stored evaluation_runs metrics.
 * Does not invent values when the list is empty.
 */

export type EvaluationRunWire = {
  id: string
  skill_version_id: string
  baseline: Record<string, unknown>
  metrics: Record<string, unknown>
  status: string
  started_at: string
  finished_at: string | null
}

export type CaseMatrixRow = {
  runId: string
  caseId: string
  passed: boolean
  arm: 'control' | 'treatment'
  latencyMs: number
  policyViolations: number
  toolErrors: number
  tokens: number
}

export type EvaluationFigures = {
  successRate: number
  policyViolationSum: number
  meanLatencyMs: number
  toolErrorSum: number
  tokenSum: number
  /** Present only when both control and treatment arms exist in the list. */
  upliftPp: number | null
}

function metricNumber(metrics: Record<string, unknown>, key: string): number {
  const value = metrics[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

export function isBaselineControl(baseline: Record<string, unknown>): boolean {
  return baseline.baseline === true
}

/** One matrix row per evaluation run (case_id + passed + arm). */
export function toCaseMatrixRows(runs: EvaluationRunWire[]): CaseMatrixRow[] {
  const rows: CaseMatrixRow[] = []
  for (const run of runs) {
    const caseId = run.metrics.case_id
    if (typeof caseId !== 'string' || caseId.length === 0) {
      continue
    }
    rows.push({
      runId: run.id,
      caseId,
      passed: run.metrics.passed === true,
      arm: isBaselineControl(run.baseline) ? 'control' : 'treatment',
      latencyMs: metricNumber(run.metrics, 'latency_ms'),
      policyViolations: metricNumber(run.metrics, 'policy_violations'),
      toolErrors: metricNumber(run.metrics, 'tool_errors'),
      tokens: metricNumber(run.metrics, 'tokens'),
    })
  }
  return rows
}

/**
 * Five headline figures from stored metrics only.
 * Returns null when there are no runs (caller shows empty state).
 */
export function computeEvaluationFigures(
  runs: EvaluationRunWire[],
): EvaluationFigures | null {
  if (runs.length === 0) {
    return null
  }

  const passedCount = runs.filter((run) => run.metrics.passed === true).length
  const successRate = passedCount / runs.length

  let policyViolationSum = 0
  let latencySum = 0
  let toolErrorSum = 0
  let tokenSum = 0
  let controlPassed = 0
  let controlCount = 0
  let treatmentPassed = 0
  let treatmentCount = 0

  for (const run of runs) {
    policyViolationSum += metricNumber(run.metrics, 'policy_violations')
    latencySum += metricNumber(run.metrics, 'latency_ms')
    toolErrorSum += metricNumber(run.metrics, 'tool_errors')
    tokenSum += metricNumber(run.metrics, 'tokens')
    const passed = run.metrics.passed === true
    if (isBaselineControl(run.baseline)) {
      controlCount += 1
      if (passed) {
        controlPassed += 1
      }
    } else {
      treatmentCount += 1
      if (passed) {
        treatmentPassed += 1
      }
    }
  }

  let upliftPp: number | null = null
  if (controlCount > 0 && treatmentCount > 0) {
    const controlRate = controlPassed / controlCount
    const treatmentRate = treatmentPassed / treatmentCount
    upliftPp = (treatmentRate - controlRate) * 100
  }

  return {
    successRate,
    policyViolationSum,
    meanLatencyMs: latencySum / runs.length,
    toolErrorSum,
    tokenSum,
    upliftPp,
  }
}

export function formatSuccessRate(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`
}

export function formatMeanLatency(ms: number): string {
  return `${Math.round(ms)} 毫秒`
}

export function formatUpliftPp(pp: number): string {
  const sign = pp > 0 ? '+' : ''
  return `${sign}${pp.toFixed(1)} 百分点`
}
