import {
  MOCK_TRACE_EVENTS,
  formatTraceJson,
  toLiveTraceRow,
} from '@/components/liveTraceModel'
import type { TraceEventWire } from '@/hooks/useEvents'
import { cn } from '@/lib/utils'

export type LiveTraceProps = {
  /** Live TraceEventWire stream (e.g. from useEvents). Empty → mock fallback. */
  events?: TraceEventWire[]
  /** `empty` shows no rows until live events arrive. Default keeps the offline sample. */
  placeholder?: 'mock' | 'empty'
  className?: string
}

export function LiveTrace({
  events,
  placeholder = 'mock',
  className,
}: LiveTraceProps) {
  const usingMock =
    placeholder === 'mock' && (events === undefined || events.length === 0)
  const source = usingMock ? MOCK_TRACE_EVENTS : (events ?? [])
  const rows = source
    .map(toLiveTraceRow)
    .filter((row): row is NonNullable<typeof row> => row !== null)

  return (
    <section
      aria-label="实时轨迹"
      className={cn('flex flex-col gap-2 rounded-md border bg-card', className)}
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          实时轨迹
        </h2>
        <span className="text-xs text-muted-foreground">
          {usingMock ? '示例数据' : `${rows.length} 条实时事件`}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        动作 / 工具 / 输入 / 输出 / 证据 / 校验 — 不展示模型思维链。
      </p>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[48rem] border-collapse text-left text-sm">
          <thead className="border-b bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">时间</th>
              <th className="px-3 py-2 font-medium">动作</th>
              <th className="px-3 py-2 font-medium">工具</th>
              <th className="px-3 py-2 font-medium">输入</th>
              <th className="px-3 py-2 font-medium">输出</th>
              <th className="px-3 py-2 font-medium">证据</th>
              <th className="px-3 py-2 font-medium">校验</th>
            </tr>
          </thead>
          <tbody className="divide-y font-mono text-xs">
            {rows.map((row) => (
              <tr key={row.id} className="align-top">
                <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                  {row.timestamp}
                </td>
                <td className="px-3 py-2 font-sans text-sm font-medium">
                  {row.action}
                </td>
                <td className="px-3 py-2">{row.tool ?? '—'}</td>
                <td className="max-w-[14rem] break-words px-3 py-2">
                  {formatTraceJson(row.input)}
                </td>
                <td className="max-w-[14rem] break-words px-3 py-2">
                  {formatTraceJson(row.output)}
                </td>
                <td className="max-w-[12rem] break-words px-3 py-2">
                  {row.evidence ?? '—'}
                </td>
                <td
                  className={cn(
                    'px-3 py-2 font-sans text-sm font-medium',
                    row.verification === 'PASS' && 'text-emerald-700',
                    row.verification === 'FAIL' && 'text-destructive',
                  )}
                >
                  {row.verification === 'PASS'
                    ? '通过'
                    : row.verification === 'FAIL'
                      ? '失败'
                      : (row.verification ?? '—')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
