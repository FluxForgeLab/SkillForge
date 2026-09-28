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
      aria-label="Live Trace"
      className={cn('flex flex-col gap-2', className)}
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          Live Trace
        </h2>
        <span className="text-xs text-muted-foreground">
          {usingMock ? 'mock sample' : `${rows.length} live event(s)`}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        Action / Tool / Input / Output / Evidence / Verification — no model
        chain-of-thought.
      </p>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[48rem] border-collapse text-left text-sm">
          <thead className="border-b bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Time</th>
              <th className="px-3 py-2 font-medium">Action</th>
              <th className="px-3 py-2 font-medium">Tool</th>
              <th className="px-3 py-2 font-medium">Input</th>
              <th className="px-3 py-2 font-medium">Output</th>
              <th className="px-3 py-2 font-medium">Evidence</th>
              <th className="px-3 py-2 font-medium">Verification</th>
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
                  {row.verification ?? '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
