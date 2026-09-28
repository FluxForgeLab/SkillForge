import {
  MOCK_BENCHMARK,
  formatSuccessPct,
  formatUpliftPp,
  type BenchmarkData,
} from '@/components/benchmarkModel'
import { cn } from '@/lib/utils'

export type BenchmarkProps = {
  /** When omitted or empty cases, mock sample is shown unless placeholder is empty. */
  data?: BenchmarkData
  /** `empty` shows no rates until a real evaluation payload arrives. */
  placeholder?: 'mock' | 'empty'
  className?: string
}

function PassFailMark({ passed }: { passed: boolean }) {
  return (
    <span
      aria-label={passed ? '通过' : '失败'}
      className={cn(
        'font-sans text-lg font-semibold',
        passed ? 'text-emerald-700' : 'text-destructive',
      )}
    >
      {passed ? '✅' : '❌'}
    </span>
  )
}

export function Benchmark({
  data,
  placeholder = 'mock',
  className,
}: BenchmarkProps) {
  const hasCases = data !== undefined && data.cases.length > 0
  const usingMock = placeholder === 'mock' && !hasCases
  const source = hasCases ? data : usingMock ? MOCK_BENCHMARK : undefined
  if (!source) {
    return (
      <section
      aria-label="评测对照"
        className={cn('flex flex-col gap-2 rounded-md border bg-card p-3', className)}
    >
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          评测对照
        </h2>
        <p className="text-sm text-muted-foreground">
          尚无评测结果。
        </p>
      </section>
    )
  }
  const controlPct = formatSuccessPct(source.task_success_rate.control)
  const treatmentPct = formatSuccessPct(source.task_success_rate.treatment)
  const uplift = formatUpliftPp(source.skill_uplift_pp)
  const upliftPositive = source.skill_uplift_pp > 0

  return (
    <section
      aria-label="评测对照"
      className={cn('flex flex-col gap-4 rounded-md border bg-card p-3', className)}
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          评测对照
        </h2>
        <span className="text-xs text-muted-foreground">
          {usingMock ? '示例数据' : `${source.cases.length} 个用例`}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        无技能与有技能的成功率，以及技能提升（百分点）。
      </p>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-md border px-4 py-5">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            无技能
          </p>
          <p className="mt-2 text-4xl font-semibold tracking-tight tabular-nums">
            {controlPct}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">对照成功率</p>
        </div>
        <div className="rounded-md border px-4 py-5">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            有技能
          </p>
          <p className="mt-2 text-4xl font-semibold tracking-tight tabular-nums">
            {treatmentPct}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">实验成功率</p>
        </div>
        <div className="rounded-md border px-4 py-5">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            技能提升
          </p>
          <p
            className={cn(
              'mt-2 text-4xl font-semibold tracking-tight tabular-nums',
              upliftPositive && 'text-emerald-700',
              source.skill_uplift_pp < 0 && 'text-destructive',
            )}
          >
            {uplift}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            相对对照组
          </p>
        </div>
      </div>

      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[28rem] border-collapse text-left text-sm">
          <thead className="border-b bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">用例</th>
              <th className="px-3 py-2 font-medium">无技能</th>
              <th className="px-3 py-2 font-medium">有技能</th>
              <th className="px-3 py-2 font-medium">提升</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {source.cases.map((row) => (
              <tr key={row.case_id} className="align-middle">
                <td className="px-3 py-2">
                  <div className="font-medium">{row.name}</div>
                  <div className="font-mono text-xs text-muted-foreground">
                    {row.case_id}
                  </div>
                </td>
                <td className="px-3 py-2">
                  <PassFailMark passed={row.control_passed} />
                </td>
                <td className="px-3 py-2">
                  <PassFailMark passed={row.treatment_passed} />
                </td>
                <td className="px-3 py-2 font-mono text-xs tabular-nums">
                  {formatUpliftPp(row.uplift_pp)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
