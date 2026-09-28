import { useEffect, useState } from 'react'

import {
  formatMemoryBytes,
  formatNullableMetric,
  type ModelStatus,
} from '@/components/dgxRuntimeModel'
import { API_BASE, apiRequest } from '@/lib/api'
import { cn } from '@/lib/utils'

export type DgxRuntimePanelProps = {
  className?: string
  /** Compact header chip vs full section layout. */
  variant?: 'header' | 'section'
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; detail: string }
  | { kind: 'ok'; data: ModelStatus }

export function DgxRuntimePanel({
  className,
  variant = 'section',
}: DgxRuntimePanelProps) {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      try {
        const result = await apiRequest<ModelStatus>('/api/model/status')
        if (cancelled) return
        if (!result.ok) {
          setState({
            kind: 'error',
            detail: result.body || `HTTP ${result.status}`,
          })
          return
        }
        setState({ kind: 'ok', data: result.data })
      } catch (err) {
        if (!cancelled) {
          setState({
            kind: 'error',
            detail: err instanceof Error ? err.message : String(err),
          })
        }
      }
    }
    void tick()
    const id = window.setInterval(() => void tick(), 10_000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  if (variant === 'header') {
    return (
      <div
        className={cn(
          'flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-1.5 text-sm',
          className,
        )}
        title={`GET ${API_BASE}/api/model/status`}
      >
        <span className="text-muted-foreground">DGX</span>
        {state.kind === 'loading' ? (
          <span className="text-muted-foreground">…</span>
        ) : state.kind === 'error' ? (
          <span className="text-destructive">离线</span>
        ) : (
          <>
            <span className="font-medium">{state.data.model}</span>
            <span className="text-muted-foreground">·</span>
            <span>{state.data.backend}</span>
            <span className="text-muted-foreground">·</span>
            <span className="text-muted-foreground">
              {formatNullableMetric(state.data.tokens_per_second)} token/秒
            </span>
            <span className="text-muted-foreground">·</span>
            <span className="text-muted-foreground">
              内存 {formatMemoryBytes(state.data.memory_bytes)}
            </span>
          </>
        )}
      </div>
    )
  }

  return (
    <section
      aria-label="DGX 运行时"
      className={cn('flex flex-col gap-3 rounded-md border bg-card p-3', className)}
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          DGX 运行时
        </h2>
        <span className="text-xs text-muted-foreground">
          GET /api/model/status
        </span>
      </div>
      {state.kind === 'loading' ? (
        <p className="text-sm text-muted-foreground">加载中…</p>
      ) : state.kind === 'error' ? (
        <p className="text-sm text-destructive">{state.detail}</p>
      ) : (
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              模型
            </dt>
            <dd className="mt-1 text-sm font-medium">{state.data.model}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              后端
            </dt>
            <dd className="mt-1 text-sm font-medium">{state.data.backend}</dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Token/秒
            </dt>
            <dd className="mt-1 text-sm font-medium tabular-nums">
              {formatNullableMetric(state.data.tokens_per_second)}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              内存
            </dt>
            <dd className="mt-1 text-sm font-medium tabular-nums">
              {formatMemoryBytes(state.data.memory_bytes)}
            </dd>
          </div>
        </dl>
      )}
    </section>
  )
}
