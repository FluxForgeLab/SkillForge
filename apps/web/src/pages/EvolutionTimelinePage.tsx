import { useQueries, useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'

import { apiRequest } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { EvaluationRunWire } from '@/pages/evaluationLabModel'
import {
  benchmarkDeltaPp,
  formatBenchmarkDeltaPp,
  orderVersionChain,
  type VersionWire,
} from '@/pages/evolutionTimelineModel'

type VersionFile = {
  path: string
  text: string
}

export default function EvolutionTimelinePage() {
  const { id: skillId = '' } = useParams<{ id: string }>()

  const versionsQuery = useQuery({
    queryKey: ['skill-versions', skillId],
    enabled: Boolean(skillId),
    queryFn: async () => {
      const result = await apiRequest<VersionWire[]>(
        `/api/skills/${skillId}/versions`,
      )
      if (!result.ok) {
        throw new Error(result.body || `versions ${result.status}`)
      }
      return result.data
    },
  })

  const evaluationsQuery = useQuery({
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

  const versions = versionsQuery.data ?? []
  const ordered = orderVersionChain(versions)
  const runs = evaluationsQuery.data ?? []

  const approverQueries = useQueries({
    queries: ordered.map((version) => ({
      queryKey: ['skill-file', skillId, version.id, 'approver.txt'] as const,
      enabled: Boolean(skillId && version.id),
      queryFn: async (): Promise<{ status: 'ok' | 'missing'; name: string }> => {
        const result = await apiRequest<VersionFile>(
          `/api/skills/${skillId}/versions/${version.id}/file?path=${encodeURIComponent('approver.txt')}`,
        )
        if (result.status === 404) {
          return { status: 'missing', name: '' }
        }
        if (!result.ok) {
          throw new Error(result.body || `approver ${result.status}`)
        }
        return { status: 'ok', name: result.data.text.trim() }
      },
      retry: false,
    })),
  })

  const empty = versionsQuery.isSuccess && ordered.length === 0
  const loading =
    versionsQuery.isLoading || (versions.length > 0 && evaluationsQuery.isLoading)

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 p-4">
      <header className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-xl font-semibold tracking-tight">
            Evolution Timeline
          </h1>
          <p className="truncate font-mono text-xs text-muted-foreground">
            {skillId || '—'}
          </p>
        </div>
        {skillId ? (
          <div className="flex flex-wrap gap-3 text-sm">
            <Link
              className="underline underline-offset-4"
              to={`/skills/${encodeURIComponent(skillId)}`}
            >
              Skill Studio
            </Link>
            <Link
              className="underline underline-offset-4"
              to={`/skills/${encodeURIComponent(skillId)}/evaluations`}
            >
              Evaluations
            </Link>
          </div>
        ) : null}
      </header>

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading timeline…</p>
      ) : null}
      {versionsQuery.isError ? (
        <p className="text-sm text-destructive">
          {(versionsQuery.error as Error).message}
        </p>
      ) : null}
      {evaluationsQuery.isError ? (
        <p className="text-sm text-destructive">
          {(evaluationsQuery.error as Error).message}
        </p>
      ) : null}

      {empty ? (
        <section
          aria-label="Empty timeline"
          className="rounded-md border border-dashed px-4 py-10 text-center"
        >
          <p className="text-sm font-medium">No versions yet</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Compile a skill first. Timeline shows stored version chain, approver
            file, and evaluation deltas — nothing is invented.
          </p>
          <p className="mt-3 text-sm">
            <Link className="underline underline-offset-4" to="/demo">
              Open Demo
            </Link>
          </p>
        </section>
      ) : null}

      {ordered.length > 0 ? (
        <ol aria-label="Version chain" className="flex flex-col gap-0">
          {ordered.map((version, index) => {
            const delta = benchmarkDeltaPp(
              runs,
              version.id,
              version.parent_version_id,
            )
            const approver = approverQueries[index]?.data
            const isLast = index === ordered.length - 1
            return (
              <li key={version.id} className="relative flex gap-4 pb-6 last:pb-0">
                <div className="flex w-4 flex-col items-center">
                  <span
                    className="mt-1 size-3 shrink-0 rounded-full border-2 border-foreground bg-background"
                    aria-hidden
                  />
                  {!isLast ? (
                    <span
                      className="mt-1 w-px flex-1 bg-border"
                      aria-hidden
                    />
                  ) : null}
                </div>
                <div className="min-w-0 flex-1 rounded-md border px-4 py-3">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <h2 className="font-mono text-base font-semibold">
                      {version.version}
                    </h2>
                    <span className="text-xs uppercase tracking-wide text-muted-foreground">
                      {version.status}
                    </span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {version.id}
                    </span>
                  </div>

                  <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                    <div>
                      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Approver
                      </dt>
                      <dd className="mt-0.5">
                        {approverQueries[index]?.isLoading ? (
                          <span className="text-muted-foreground">…</span>
                        ) : approver?.status === 'ok' && approver.name ? (
                          approver.name
                        ) : (
                          <span className="text-muted-foreground">
                            Not approved yet (no approver.txt)
                          </span>
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Benchmark delta
                      </dt>
                      <dd
                        className={cn(
                          'mt-0.5 tabular-nums',
                          delta !== null &&
                            delta > 0 &&
                            'font-medium text-emerald-700',
                          delta !== null &&
                            delta < 0 &&
                            'font-medium text-destructive',
                        )}
                      >
                        {delta === null ? (
                          <span className="text-muted-foreground">
                            {version.parent_version_id
                              ? 'No stored treatment runs for delta'
                              : 'Root version (no parent)'}
                          </span>
                        ) : (
                          formatBenchmarkDeltaPp(delta)
                        )}
                      </dd>
                    </div>
                    <div className="sm:col-span-2">
                      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Reason
                      </dt>
                      <dd className="mt-0.5 text-muted-foreground">
                        Not stored
                      </dd>
                    </div>
                  </dl>
                </div>
              </li>
            )
          })}
        </ol>
      ) : null}
    </div>
  )
}
