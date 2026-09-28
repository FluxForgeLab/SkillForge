import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { LiveTrace } from '@/components/LiveTrace'
import type { TraceEventWire } from '@/hooks/useEvents'
import { apiRequest } from '@/lib/api'
import { cn } from '@/lib/utils'
import {
  computeEvaluationFigures,
  formatMeanLatency,
  formatSuccessRate,
  formatUpliftPp,
  toCaseMatrixRows,
  type EvaluationRunWire,
} from '@/pages/evaluationLabModel'

export default function EvaluationLabPage() {
  const { id: skillId = '' } = useParams<{ id: string }>()
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)

  const listQuery = useQuery({
    queryKey: ['skill-evaluations', skillId],
    enabled: Boolean(skillId),
    queryFn: async () => {
      const result = await apiRequest<EvaluationRunWire[]>(
        `/api/skills/${skillId}/evaluations`,
      )
      if (!result.ok) {
        throw new Error(result.body || `evaluations ${result.status}`)
      }
      return result.data
    },
  })

  const eventsQuery = useQuery({
    queryKey: ['run-events', selectedRunId],
    enabled: Boolean(selectedRunId),
    queryFn: async () => {
      const result = await apiRequest<TraceEventWire[]>(
        `/api/runs/${selectedRunId}/events`,
      )
      if (!result.ok) {
        throw new Error(result.body || `events ${result.status}`)
      }
      return result.data
    },
  })

  const runs = listQuery.data ?? []
  const figures = computeEvaluationFigures(runs)
  const matrixRows = toCaseMatrixRows(runs)
  const empty = listQuery.isSuccess && runs.length === 0

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 p-4">
      <header className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-xl font-semibold tracking-tight">
            Evaluation Lab
          </h1>
          <p className="truncate font-mono text-xs text-muted-foreground">
            {skillId || '—'}
          </p>
        </div>
        {skillId ? (
          <Link
            className="text-sm underline underline-offset-4"
            to={`/skills/${encodeURIComponent(skillId)}`}
          >
            Skill Studio
          </Link>
        ) : null}
      </header>

      {listQuery.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading evaluations…</p>
      ) : null}
      {listQuery.isError ? (
        <p className="text-sm text-destructive">
          {(listQuery.error as Error).message}
        </p>
      ) : null}

      {empty ? (
        <section
          aria-label="Empty evaluations"
          className="rounded-md border border-dashed px-4 py-10 text-center"
        >
          <p className="text-sm font-medium">No evaluation runs yet</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Run Evaluate from Demo, then return here. Figures stay empty until
            stored metrics exist — nothing is invented.
          </p>
          <p className="mt-3 text-sm">
            <Link className="underline underline-offset-4" to="/demo">
              Open Demo
            </Link>
          </p>
        </section>
      ) : null}

      {figures ? (
        <section aria-label="Evaluation figures" className="flex flex-col gap-3">
          <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
            Figures
          </h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <FigureCard
              label="Success rate"
              value={formatSuccessRate(figures.successRate)}
            />
            <FigureCard
              label="Policy violations"
              value={String(figures.policyViolationSum)}
            />
            <FigureCard
              label="Mean latency"
              value={formatMeanLatency(figures.meanLatencyMs)}
            />
            <FigureCard
              label="Tool errors"
              value={String(figures.toolErrorSum)}
            />
            <FigureCard label="Tokens" value={String(figures.tokenSum)} />
            {figures.upliftPp !== null ? (
              <FigureCard
                label="Uplift"
                value={formatUpliftPp(figures.upliftPp)}
                emphasize={figures.upliftPp > 0}
              />
            ) : null}
          </div>
        </section>
      ) : null}

      {matrixRows.length > 0 ? (
        <section aria-label="Case matrix" className="flex flex-col gap-2">
          <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
            Case matrix
          </h2>
          <p className="text-xs text-muted-foreground">
            Click a row to load stored trace events (Action / Tool / Input /
            Output / Evidence / Verification — no CoT).
          </p>
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full min-w-[36rem] border-collapse text-left text-sm">
              <thead className="border-b bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">Case</th>
                  <th className="px-3 py-2 font-medium">Arm</th>
                  <th className="px-3 py-2 font-medium">Passed</th>
                  <th className="px-3 py-2 font-medium">Run</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {matrixRows.map((row) => {
                  const selected = row.runId === selectedRunId
                  return (
                    <tr
                      key={row.runId}
                      className={cn(
                        'cursor-pointer hover:bg-muted/50',
                        selected && 'bg-muted/60',
                      )}
                      onClick={() => setSelectedRunId(row.runId)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault()
                          setSelectedRunId(row.runId)
                        }
                      }}
                      tabIndex={0}
                      aria-selected={selected}
                    >
                      <td className="px-3 py-2 font-mono text-xs">
                        {row.caseId}
                      </td>
                      <td className="px-3 py-2 capitalize">{row.arm}</td>
                      <td
                        className={cn(
                          'px-3 py-2 font-medium',
                          row.passed
                            ? 'text-emerald-700'
                            : 'text-destructive',
                        )}
                      >
                        {row.passed ? 'pass' : 'fail'}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                        {row.runId}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {selectedRunId ? (
        <section aria-label="Run trace" className="flex flex-col gap-2">
          <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
            Trace
          </h2>
          {eventsQuery.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading events…</p>
          ) : null}
          {eventsQuery.isError ? (
            <p className="text-sm text-destructive">
              {(eventsQuery.error as Error).message}
            </p>
          ) : null}
          {eventsQuery.isSuccess && eventsQuery.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No stored events for this run.
            </p>
          ) : null}
          {eventsQuery.isSuccess && eventsQuery.data.length > 0 ? (
            <LiveTrace
              events={eventsQuery.data}
              className="rounded-md border p-3"
            />
          ) : null}
        </section>
      ) : null}
    </div>
  )
}

function FigureCard({
  label,
  value,
  emphasize,
}: {
  label: string
  value: string
  emphasize?: boolean
}) {
  return (
    <div className="rounded-md border px-3 py-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p
        className={cn(
          'mt-2 text-2xl font-semibold tracking-tight tabular-nums',
          emphasize && 'text-emerald-700',
        )}
      >
        {value}
      </p>
    </div>
  )
}
