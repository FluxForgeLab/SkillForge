/** Pure helpers for Skill Studio: frontmatter and source-map evidence. */

export type SkillSpecFields = {
  name: string | null
  description: string | null
  triggers: string[]
  tools: string[]
}

export type EvidenceRow = {
  instructionId: string
  document: string
  sha256: string
  page: number | string | null
  lineStart: number | string | null
}

const EMPTY_SPEC: SkillSpecFields = {
  name: null,
  description: null,
  triggers: [],
  tools: [],
}

/** Parse SKILL.md YAML frontmatter for the SkillSpec panel (lite, no CoT). */
export function parseSkillFrontmatter(text: string): SkillSpecFields {
  const match = /^---\r?\n([\s\S]*?)\r?\n---/.exec(text)
  if (!match) {
    return { ...EMPTY_SPEC }
  }
  const block = match[1]
  return {
    name: readScalar(block, 'name'),
    description: readScalar(block, 'description'),
    triggers: readList(block, 'triggers'),
    tools: readList(block, 'tools'),
  }
}

/** Flatten references/source-map.json into evidence sidebar rows. */
export function parseSourceMapEvidence(text: string): EvidenceRow[] {
  let parsed: unknown
  try {
    parsed = JSON.parse(text) as unknown
  } catch {
    return []
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return []
  }
  const rows: EvidenceRow[] = []
  for (const [instructionId, value] of Object.entries(
    parsed as Record<string, unknown>,
  )) {
    const entry =
      value && typeof value === 'object' && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : {}
    rows.push({
      instructionId,
      document: stringOrEmpty(entry.document),
      sha256: stringOrEmpty(entry.sha256),
      page: scalarOrNull(entry.page),
      lineStart: scalarOrNull(entry.line_start),
    })
  }
  return rows.sort((a, b) => a.instructionId.localeCompare(b.instructionId))
}

function readScalar(block: string, key: string): string | null {
  const re = new RegExp(`^${key}:\\s*(.+?)\\s*$`, 'm')
  const match = re.exec(block)
  if (!match) {
    return null
  }
  const raw = match[1].trim()
  if (
    (raw.startsWith('"') && raw.endsWith('"')) ||
    (raw.startsWith("'") && raw.endsWith("'"))
  ) {
    return raw.slice(1, -1)
  }
  if (raw.startsWith('[')) {
    return null
  }
  return raw
}

function readList(block: string, key: string): string[] {
  const re = new RegExp(`^${key}:\\s*(.+?)\\s*$`, 'm')
  const match = re.exec(block)
  if (!match) {
    return []
  }
  const raw = match[1].trim()
  if (!raw.startsWith('[') || !raw.endsWith(']')) {
    return raw ? [raw] : []
  }
  const inner = raw.slice(1, -1).trim()
  if (!inner) {
    return []
  }
  return inner.split(',').map((item) => item.trim()).filter(Boolean)
}

function stringOrEmpty(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value)
}

function scalarOrNull(value: unknown): number | string | null {
  if (value == null) {
    return null
  }
  if (typeof value === 'number' || typeof value === 'string') {
    return value
  }
  return String(value)
}
