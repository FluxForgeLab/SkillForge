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
            评测
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
              to={`/skills/${encodeURIComponent(skillId)}/timeline`}
            >
              时间线
            </Link>
          </div>
        ) : null}
      </header>

      {listQuery.isLoading ? (
        <p className="text-sm text-muted-foreground">正在加载评测…</p>
      ) : null}
      {listQuery.isError ? (
        <p className="text-sm text-destructive">
          {(listQuery.error as Error).message}
        </p>
      ) : null}

      {empty ? (
        <section
          aria-label="空评测"
          className="rounded-md border border-dashed px-4 py-10 text-center"
        >
          <p className="text-sm font-medium">还没有评测记录</p>
          <p className="mt-1 text-sm text-muted-foreground">
            先在演示页运行评测，再回到这里。没有已保存的指标时数字保持空白，不会编造。
          </p>
          <p className="mt-3 text-sm">
            <Link className="underline underline-offset-4" to="/demo">
              打开演示
            </Link>
          </p>
        </section>
      ) : null}

      {figures ? (
        <section aria-label="评测指标" className="flex flex-col gap-3">
          <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
            指标
          </h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <FigureCard
              label="成功率"
              value={formatSuccessRate(figures.successRate)}
            />
            <FigureCard
              label="策略违规"
              value={String(figures.policyViolationSum)}
            />
            <FigureCard
              label="平均延迟"
              value={formatMeanLatency(figures.meanLatencyMs)}
            />
            <FigureCard
              label="工具错误"
              value={String(figures.toolErrorSum)}
            />
            <FigureCard label="Token" value={String(figures.tokenSum)} />
            {figures.upliftPp !== null ? (
              <FigureCard
                label="提升"
                value={formatUpliftPp(figures.upliftPp)}
                emphasize={figures.upliftPp > 0}
              />
            ) : null}
          </div>
        </section>
      ) : null}

      {matrixRows.length > 0 ? (
        <section aria-label="用例矩阵" className="flex flex-col gap-2">
          <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
            用例矩阵
          </h2>
          <p className="text-xs text-muted-foreground">
            点击一行加载已保存的轨迹（动作 / 工具 / 输入 / 输出 / 证据 / 校验，不含思维链）。
          </p>
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full min-w-[36rem] border-collapse text-left text-sm">
              <thead className="border-b bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">用例</th>
                  <th className="px-3 py-2 font-medium">分组</th>
                  <th className="px-3 py-2 font-medium">结果</th>
                  <th className="px-3 py-2 font-medium">运行</th>
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
                      <td className="px-3 py-2">
                        {row.arm === 'control' ? '无技能' : '有技能'}
                      </td>
                      <td
                        className={cn(
                          'px-3 py-2 font-medium',
                          row.passed
                            ? 'text-emerald-700'
                            : 'text-destructive',
                        )}
                      >
                        {row.passed ? '通过' : '失败'}
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
        <section aria-label="运行轨迹" className="flex flex-col gap-2">
          <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
            轨迹
          </h2>
          {eventsQuery.isLoading ? (
            <p className="text-sm text-muted-foreground">正在加载事件…</p>
          ) : null}
          {eventsQuery.isError ? (
            <p className="text-sm text-destructive">
              {(eventsQuery.error as Error).message}
            </p>
          ) : null}
          {eventsQuery.isSuccess && eventsQuery.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              这次运行没有已保存的事件。
            </p>
          ) : null}
          {eventsQuery.isSuccess && eventsQuery.data.length > 0 ? (
            <LiveTrace events={eventsQuery.data} />
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
