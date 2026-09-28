import type { TraceEventWire } from '@/hooks/useEvents'

/** Columns allowed in the Live Trace UI (architecture §10.7). */
export type LiveTraceColumns = {
  action: string
  tool: string | null
  input: Record<string, unknown>
  output: Record<string, unknown>
  evidence: string | null
  verification: string | null
}

const HIDDEN_TYPES = new Set(['model_request', 'model_response'])

const SOURCE_REF_KEYS = [
  'source_ref',
  'source_refs',
  'evidence',
  'evidence_refs',
  'source_support',
  'hits',
] as const

/** Deterministic sample timeline so the UI works with WebSocket closed. */
export const MOCK_TRACE_EVENTS: TraceEventWire[] = [
  {
    id: 'mock-task',
    run_id: 'mock-run',
    type: 'workflow_started',
    timestamp: '2026-09-28T12:00:00.000Z',
    stage: 'runtime',
    name: 'service_recovery',
    input: { task: 'Restore nginx upstream after 502' },
    output: {},
    duration_ms: null,
  },
  {
    id: 'mock-tool-call',
    run_id: 'mock-run',
    type: 'tool_call',
    timestamp: '2026-09-28T12:00:02.000Z',
    stage: 'runtime',
    name: 'docker.restart',
    input: { service: 'backend' },
    output: {},
    duration_ms: null,
  },
  {
    id: 'mock-tool-result',
    run_id: 'mock-run',
    type: 'tool_result',
    timestamp: '2026-09-28T12:00:04.000Z',
    stage: 'runtime',
    name: 'docker.restart',
    input: {},
    output: { ok: true, service: 'backend' },
    duration_ms: 180,
  },
  {
    id: 'mock-retrieval',
    run_id: 'mock-run',
    type: 'retrieval_query',
    timestamp: '2026-09-28T12:00:06.000Z',
    stage: 'knowledge',
    name: 'sqlite_fts',
    input: { query: '502 upstream nginx -t' },
    output: {
      hits: [
        {
          title: 'Appendix B: upstream mismatch',
          source_ref: 'runbook.md#L31',
          score: 0.91,
        },
      ],
    },
    duration_ms: 12,
  },
  {
    id: 'mock-nginx-t',
    run_id: 'mock-run',
    type: 'tool_call',
    timestamp: '2026-09-28T12:00:08.000Z',
    stage: 'runtime',
    name: 'nginx.test',
    input: {},
    output: {},
    duration_ms: null,
  },
  {
    id: 'mock-nginx-t-result',
    run_id: 'mock-run',
    type: 'tool_result',
    timestamp: '2026-09-28T12:00:09.000Z',
    stage: 'runtime',
    name: 'nginx.test',
    input: {},
    output: { ok: true, stderr: 'nginx: configuration file ok' },
    duration_ms: 40,
  },
  {
    id: 'mock-assertion',
    run_id: 'mock-run',
    type: 'assertion',
    timestamp: '2026-09-28T12:00:12.000Z',
    stage: 'evaluator',
    name: 'case_f2_upstream',
    input: { case_id: 'f2' },
    output: {
      passed: true,
      expected: { health_status: 200 },
      actual: { health_status: 200 },
      source_ref: 'evals/evals.json#f2',
    },
    duration_ms: 5,
  },
]

export function formatTraceJson(value: Record<string, unknown>): string {
  if (Object.keys(value).length === 0) {
    return '—'
  }
  return JSON.stringify(value, null, 0)
}

function pickSourceLike(output: Record<string, unknown>): string | null {
  const parts: string[] = []
  for (const key of SOURCE_REF_KEYS) {
    if (!(key in output)) {
      continue
    }
    const value = output[key]
    if (value === undefined || value === null) {
      continue
    }
    parts.push(
      typeof value === 'string' ? value : JSON.stringify(value, null, 0),
    )
  }
  return parts.length > 0 ? parts.join(' · ') : null
}

function evidenceFor(event: TraceEventWire): string | null {
  if (event.type === 'retrieval_query' || event.type === 'assertion') {
    const fromKeys = pickSourceLike(event.output)
    if (fromKeys) {
      return fromKeys
    }
    if (Object.keys(event.output).length > 0) {
      return formatTraceJson(event.output)
    }
  }
  return pickSourceLike(event.output)
}

function verificationFor(event: TraceEventWire): string | null {
  if (event.type !== 'assertion') {
    return null
  }
  const passed = event.output.passed
  if (typeof passed === 'boolean') {
    return passed ? 'PASS' : 'FAIL'
  }
  return formatTraceJson(event.output)
}

/** Map a wire event into the six Live Trace columns; hide model CoT events. */
export function toLiveTraceRow(
  event: TraceEventWire,
): (LiveTraceColumns & { id: string; timestamp: string }) | null {
  if (HIDDEN_TYPES.has(event.type)) {
    return null
  }
  return {
    id: event.id,
    timestamp: event.timestamp,
    action: event.type,
    tool: event.name,
    input: event.input,
    output: event.output,
    evidence: evidenceFor(event),
    verification: verificationFor(event),
  }
}
