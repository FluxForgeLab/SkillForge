import {
  MOCK_PIPELINE_EVENTS,
  PIPELINE_STEPS,
  derivePipelineStepperState,
  isPipelineWorkflowEvent,
  type StepVisualStatus,
} from '@/components/pipelineStepperModel'
import type { TraceEventWire } from '@/hooks/useEvents'
import { cn } from '@/lib/utils'

export type PipelineStepperProps = {
  /** Live TraceEventWire stream (e.g. from useEvents). No pipeline events → idle mock. */
  events?: TraceEventWire[]
  /** `empty` keeps every step pending until a real PipelineState event arrives. */
  placeholder?: 'mock' | 'empty'
  className?: string
}

function stepTone(status: StepVisualStatus): string {
  switch (status) {
    case 'complete':
      return 'border-emerald-600 bg-emerald-600 text-white'
    case 'active':
      return 'border-foreground bg-foreground text-background'
    case 'failed':
      return 'border-destructive bg-destructive text-white'
    default:
      return 'border-muted-foreground/40 bg-background text-muted-foreground'
  }
}

function connectorTone(
  left: StepVisualStatus,
  right: StepVisualStatus,
): string {
  if (left === 'failed') return 'bg-destructive/40'
  if (left === 'complete' && right !== 'pending') return 'bg-emerald-600/60'
  if (left === 'complete') return 'bg-emerald-600/40'
  if (left === 'active') return 'bg-foreground/30'
  return 'bg-muted-foreground/25'
}

export function PipelineStepper({
  events,
  placeholder = 'mock',
  className,
}: PipelineStepperProps) {
  const livePipeline =
    events !== undefined ? events.filter(isPipelineWorkflowEvent) : []
  const usingMock =
    placeholder === 'mock' && (events === undefined || livePipeline.length === 0)
  const source = usingMock ? MOCK_PIPELINE_EVENTS : livePipeline
  const { statuses, failed } = derivePipelineStepperState(source)

  return (
    <section
      aria-label="技能构建流水线"
      className={cn('flex flex-col gap-2 rounded-md border bg-card p-3', className)}
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          技能构建流水线
        </h2>
        <span className="text-xs text-muted-foreground">
          {usingMock
            ? '示例（空闲）'
            : livePipeline.length === 0
              ? '尚无流程事件'
              : failed
                ? '失败'
                : `${livePipeline.length} 条流程事件`}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        解析 → 抽取 → 规格 → 技能 → 测试 → 校验，随{' '}
        <code className="text-foreground">workflow_started</code> 中的流程状态推进。
      </p>

      <ol className="flex flex-wrap items-center gap-y-3 rounded-md bg-muted/70 px-3 py-4 sm:flex-nowrap sm:justify-between">
        {PIPELINE_STEPS.map((label, index) => {
          const status = statuses[index]
          const isLast = index === PIPELINE_STEPS.length - 1
          return (
            <li
              key={label}
              className={cn(
                'flex items-center',
                isLast ? 'flex-none' : 'min-w-0 flex-1',
              )}
            >
              <div className="flex flex-col items-center gap-1.5">
                <span
                  aria-current={status === 'active' ? 'step' : undefined}
                  className={cn(
                    'flex size-8 items-center justify-center rounded-full border text-xs font-semibold tabular-nums',
                    stepTone(status),
                  )}
                >
                  {status === 'complete'
                    ? '✓'
                    : status === 'failed'
                      ? '!'
                      : index + 1}
                </span>
                <span
                  className={cn(
                    'text-xs font-medium',
                    status === 'pending' && 'text-muted-foreground',
                    status === 'failed' && 'text-destructive',
                    (status === 'active' || status === 'complete') &&
                      'text-foreground',
                  )}
                >
                  {label}
                </span>
                <span className="sr-only">
                  {status === 'pending'
                    ? '等待'
                    : status === 'active'
                      ? '进行中'
                      : status === 'complete'
                        ? '完成'
                        : '失败'}
                </span>
              </div>
              {!isLast ? (
                <div
                  aria-hidden
                  className={cn(
                    'mx-2 hidden h-0.5 min-w-[1.25rem] flex-1 sm:block',
                    connectorTone(status, statuses[index + 1]),
                  )}
                />
              ) : null}
            </li>
          )
        })}
      </ol>
    </section>
  )
}
