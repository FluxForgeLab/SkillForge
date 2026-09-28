import { useQueries, useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'

import { apiRequest } from '@/lib/api'
import { skillStatusLabel } from '@/lib/labels'
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
            演进时间线
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
              技能工作室
            </Link>
            <Link
              className="underline underline-offset-4"
              to={`/skills/${encodeURIComponent(skillId)}/evaluations`}
            >
              评测
            </Link>
          </div>
        ) : null}
      </header>

      {loading ? (
        <p className="text-sm text-muted-foreground">正在加载时间线…</p>
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
          aria-label="空时间线"
          className="rounded-md border border-dashed px-4 py-10 text-center"
        >
          <p className="text-sm font-medium">还没有版本</p>
          <p className="mt-1 text-sm text-muted-foreground">
            先编译一个技能。时间线只展示已保存的版本链、批准人和评测差值，不会编造内容。
          </p>
          <p className="mt-3 text-sm">
            <Link className="underline underline-offset-4" to="/demo">
              打开演示
            </Link>
          </p>
        </section>
      ) : null}

      {ordered.length > 0 ? (
        <ol aria-label="版本链" className="flex flex-col gap-0">
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
                <div className="min-w-0 flex-1 rounded-md border bg-card px-4 py-3">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <h2 className="font-mono text-base font-semibold">
                      {version.version}
                    </h2>
                    <span className="text-xs uppercase tracking-wide text-muted-foreground">
                      {skillStatusLabel(version.status)}
                    </span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {version.id}
                    </span>
                  </div>

                  <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                    <div>
                      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        批准人
                      </dt>
                      <dd className="mt-0.5">
                        {approverQueries[index]?.isLoading ? (
                          <span className="text-muted-foreground">…</span>
                        ) : approver?.status === 'ok' && approver.name ? (
                          approver.name
                        ) : (
                          <span className="text-muted-foreground">
                            尚未批准（没有 approver.txt）
                          </span>
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        评测差值
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
                              ? '没有可用于比较的实验组记录'
                              : '根版本（没有父版本）'}
                          </span>
                        ) : (
                          formatBenchmarkDeltaPp(delta)
                        )}
                      </dd>
                    </div>
                    <div className="sm:col-span-2">
                      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        原因
                      </dt>
                      <dd className="mt-0.5 text-muted-foreground">
                        未存储
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
