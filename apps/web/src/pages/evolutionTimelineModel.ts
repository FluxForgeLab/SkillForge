/**
 * Pure helpers for Evolution Timeline: version chain order and treatment
 * passed-rate delta vs parent. Does not invent failure reasons.
 */

import {
  isBaselineControl,
  type EvaluationRunWire,
} from '@/pages/evaluationLabModel'

export type VersionWire = {
  id: string
  version: string
  status: string
  artifact_path: string | null
  parent_version_id: string | null
}

/** Treatment arm passed-rate for one version; null when no treatment runs. */
export function treatmentPassedRate(
  runs: EvaluationRunWire[],
  versionId: string,
): number | null {
  let passed = 0
  let total = 0
  for (const run of runs) {
    if (run.skill_version_id !== versionId) {
      continue
    }
    if (isBaselineControl(run.baseline)) {
      continue
    }
    total += 1
    if (run.metrics.passed === true) {
      passed += 1
    }
  }
  if (total === 0) {
    return null
  }
  return passed / total
}

/**
 * Benchmark delta in percentage points:
 * (this version treatment rate − parent treatment rate) × 100.
 * Null when parent is missing or either side lacks treatment runs.
 */
export function benchmarkDeltaPp(
  runs: EvaluationRunWire[],
  versionId: string,
  parentVersionId: string | null,
): number | null {
  if (!parentVersionId) {
    return null
  }
  const childRate = treatmentPassedRate(runs, versionId)
  const parentRate = treatmentPassedRate(runs, parentVersionId)
  if (childRate === null || parentRate === null) {
    return null
  }
  return (childRate - parentRate) * 100
}

/**
 * Order versions root → leaf by parent_version_id edges.
 * Orphans (broken parent refs) append after reachable chains, by version label.
 */
export function orderVersionChain(versions: VersionWire[]): VersionWire[] {
  if (versions.length === 0) {
    return []
  }
  const byId = new Map(versions.map((v) => [v.id, v]))
  const children = new Map<string, VersionWire[]>()
  const roots: VersionWire[] = []

  for (const version of versions) {
    const parentId = version.parent_version_id
    if (parentId && byId.has(parentId)) {
      const list = children.get(parentId) ?? []
      list.push(version)
      children.set(parentId, list)
    } else {
      roots.push(version)
    }
  }

  const sortByLabel = (a: VersionWire, b: VersionWire) =>
    a.version.localeCompare(b.version, undefined, { numeric: true })

  for (const list of children.values()) {
    list.sort(sortByLabel)
  }
  roots.sort(sortByLabel)

  const ordered: VersionWire[] = []
  const seen = new Set<string>()

  function walk(node: VersionWire) {
    if (seen.has(node.id)) {
      return
    }
    seen.add(node.id)
    ordered.push(node)
    for (const child of children.get(node.id) ?? []) {
      walk(child)
    }
  }

  for (const root of roots) {
    walk(root)
  }

  const leftovers = versions
    .filter((v) => !seen.has(v.id))
    .sort(sortByLabel)
  for (const left of leftovers) {
    walk(left)
  }

  return ordered
}

export function formatBenchmarkDeltaPp(pp: number): string {
  const sign = pp > 0 ? '+' : ''
  return `${sign}${pp.toFixed(1)} 百分点`
}
