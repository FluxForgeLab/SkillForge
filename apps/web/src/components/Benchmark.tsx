import {
  MOCK_BENCHMARK,
  formatSuccessPct,
  formatUpliftPp,
  type BenchmarkData,
} from '@/components/benchmarkModel'
import { cn } from '@/lib/utils'

export type BenchmarkProps = {
  /** When omitted or empty cases, mock sample is shown. */
  data?: BenchmarkData
  className?: string
}

function PassFailMark({ passed }: { passed: boolean }) {
  return (
    <span
      aria-label={passed ? 'pass' : 'fail'}
      className={cn(
        'font-sans text-lg font-semibold',
        passed ? 'text-emerald-700' : 'text-destructive',
      )}
    >
      {passed ? '✅' : '❌'}
    </span>
  )
}

export function Benchmark({ data, className }: BenchmarkProps) {
  const source =
    data !== undefined && data.cases.length > 0 ? data : MOCK_BENCHMARK
  const usingMock = data === undefined || data.cases.length === 0
  const controlPct = formatSuccessPct(source.task_success_rate.control)
  const treatmentPct = formatSuccessPct(source.task_success_rate.treatment)
  const uplift = formatUpliftPp(source.skill_uplift_pp)
  const upliftPositive = source.skill_uplift_pp > 0

  return (
    <section
      aria-label="Benchmark"
      className={cn('flex flex-col gap-4', className)}
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          Benchmark
        </h2>
        <span className="text-xs text-muted-foreground">
          {usingMock ? 'mock sample' : `${source.cases.length} case(s)`}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        Without Skill vs With Skill — success rates and Skill Uplift (pp).
      </p>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-md border px-4 py-5">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Without Skill
          </p>
          <p className="mt-2 text-4xl font-semibold tracking-tight tabular-nums">
            {controlPct}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">control success</p>
        </div>
        <div className="rounded-md border px-4 py-5">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            With Skill
          </p>
          <p className="mt-2 text-4xl font-semibold tracking-tight tabular-nums">
            {treatmentPct}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">treatment success</p>
        </div>
        <div className="rounded-md border px-4 py-5">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Skill Uplift
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
            percentage points
          </p>
        </div>
      </div>

      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[28rem] border-collapse text-left text-sm">
          <thead className="border-b bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Case</th>
              <th className="px-3 py-2 font-medium">Without Skill</th>
              <th className="px-3 py-2 font-medium">With Skill</th>
              <th className="px-3 py-2 font-medium">Uplift</th>
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
