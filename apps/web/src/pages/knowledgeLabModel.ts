/** Pure helpers for Knowledge Lab location display (C9.11). */

export type SourceLocationWire = {
  page: number | null
  line_start: number | null
  line_end: number | null
  chunk_id: string | null
}

export type KnowledgeUnitWire = {
  id: string
  document_id: string
  type: string
  title: string
  confidence: number | null
  content: Record<string, unknown>
  source_location: SourceLocationWire | null
}

export type SourceWire = {
  id: string
  project_id: string
  filename: string
  sha256: string
  version: string
  parser: string
  created_at: string
}

export type ProjectWire = {
  id: string
  name: string
  description: string | null
  created_at: string
}

/** Filename from sources list; never invent a page number. */
export function documentFilename(
  documentId: string,
  sources: readonly SourceWire[],
): string {
  const match = sources.find((source) => source.id === documentId)
  return match?.filename ?? documentId
}

/**
 * Location label for a selected KU:
 * page if present, else line_start; both null → "location not stored".
 */
export function formatKuLocation(
  location: SourceLocationWire | null | undefined,
): string {
  if (!location) {
    return 'location not stored'
  }
  if (location.page != null) {
    return `page ${location.page}`
  }
  if (location.line_start != null) {
    return `line ${location.line_start}`
  }
  return 'location not stored'
}
