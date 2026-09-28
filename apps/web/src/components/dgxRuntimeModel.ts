/** Pure helpers for DGX Runtime / model status display (C9.10). */

export type ModelStatus = {
  model: string
  backend: string
  tokens_per_second: number | null
  memory_bytes: number | null
}

/** Null metrics must never render as 0 — they mean "not measured" until C10.2. */
export function formatNullableMetric(
  value: number | null | undefined,
): string {
  if (value === null || value === undefined) {
    return 'not measured'
  }
  return String(value)
}

export function formatMemoryBytes(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return 'not measured'
  }
  if (value >= 1_073_741_824) {
    return `${(value / 1_073_741_824).toFixed(1)} GiB`
  }
  if (value >= 1_048_576) {
    return `${(value / 1_048_576).toFixed(1)} MiB`
  }
  return `${value} B`
}
