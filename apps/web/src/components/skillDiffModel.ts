/**
 * Pure helpers for SkillDiff: unified-diff line classification and failure panel
 * state. Diff text comes from GET .../versions/{id}/diff; failure fields come from
 * EvolveResponse when present — never invent failure content.
 */

export type DiffLineKind =
  | 'add'
  | 'remove'
  | 'context'
  | 'hunk'
  | 'header'
  | 'meta'

export type DiffLine = {
  kind: DiffLineKind
  text: string
}

/** Failure panel wired from EvolveResponse (or empty when loading diff alone). */
export type SkillDiffFailure = {
  failure_class: string | null
  symptom: string | null
  evidence: string[]
  source_support: string[]
}

export type SkillDiffPayload = {
  version_id: string
  parent_version_id: string | null
  has_parent: boolean
  diff: string
}

export const EMPTY_SKILL_DIFF_FAILURE: SkillDiffFailure = {
  failure_class: null,
  symptom: null,
  evidence: [],
  source_support: [],
}

/** Sample unified diff for offline UI smoke (not CoT). */
export const MOCK_SKILL_DIFF: SkillDiffPayload = {
  version_id: 'sv_mock_v02',
  parent_version_id: 'sv_mock_v01',
  has_parent: true,
  diff: [
    '--- a/SKILL.md',
    '+++ b/SKILL.md',
    '@@ -20,3 +20,4 @@',
    ' ins_03 http.get http://127.0.0.1:8088/health.',
    '+ins_08 Run nginx -t before reload.',
  ].join('\n'),
}

export const MOCK_SKILL_DIFF_FAILURE: SkillDiffFailure = {
  failure_class: 'missing_instruction',
  symptom: 'F3 nginx_bad_config_reload still failing after restart',
  evidence: ['http_status=502', 'tool_call nginx.reload without nginx -t'],
  source_support: ['runbook.md#page=12', 'Appendix B: upstream mismatch'],
}

export function emptySkillDiffFailure(): SkillDiffFailure {
  return { ...EMPTY_SKILL_DIFF_FAILURE, evidence: [], source_support: [] }
}

/**
 * Classify unified-diff lines for highlighting.
 * Deterministic; does not interpret model reasoning.
 */
export function parseUnifiedDiff(diff: string): DiffLine[] {
  if (!diff) {
    return []
  }
  return diff.split('\n').map((text) => ({ kind: classifyDiffLine(text), text }))
}

export function classifyDiffLine(line: string): DiffLineKind {
  if (line.startsWith('+++ ') || line.startsWith('--- ')) {
    return 'header'
  }
  if (line.startsWith('@@')) {
    return 'hunk'
  }
  if (line.startsWith('\\')) {
    return 'meta'
  }
  if (line.startsWith('+')) {
    return 'add'
  }
  if (line.startsWith('-')) {
    return 'remove'
  }
  return 'context'
}

export function hasFailureContent(failure: SkillDiffFailure | null | undefined): boolean {
  if (!failure) {
    return false
  }
  return Boolean(
    failure.failure_class ||
      failure.symptom ||
      failure.evidence.length > 0 ||
      failure.source_support.length > 0,
  )
}

/** Map EvolveResponse failure fields; missing keys → empty evidence state. */
export function failureFromEvolve(data: {
  failure_class?: unknown
  symptom?: unknown
  evidence?: unknown
  source_support?: unknown
}): SkillDiffFailure {
  return {
    failure_class:
      typeof data.failure_class === 'string' ? data.failure_class : null,
    symptom: typeof data.symptom === 'string' ? data.symptom : null,
    evidence: stringList(data.evidence),
    source_support: stringList(data.source_support),
  }
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.filter((item): item is string => typeof item === 'string')
}
