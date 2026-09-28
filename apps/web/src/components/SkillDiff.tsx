import {
  MOCK_SKILL_DIFF,
  MOCK_SKILL_DIFF_FAILURE,
  emptySkillDiffFailure,
  hasFailureContent,
  parseUnifiedDiff,
  type SkillDiffFailure,
  type SkillDiffPayload,
} from '@/components/skillDiffModel'
import { cn } from '@/lib/utils'

export type SkillDiffProps = {
  /** When omitted, mock sample is shown for offline smoke. */
  data?: SkillDiffPayload | null
  /** From EvolveResponse when present; otherwise empty evidence state. */
  failure?: SkillDiffFailure | null
  /** `empty` hides the sample until a real diff is loaded. */
  placeholder?: 'mock' | 'empty'
  className?: string
}

const LINE_CLASS: Record<string, string> = {
  add: 'bg-emerald-500/15 text-emerald-900 dark:text-emerald-200',
  remove: 'bg-destructive/15 text-destructive',
  context: 'text-foreground/80',
  hunk: 'bg-muted/60 text-muted-foreground',
  header: 'font-semibold text-muted-foreground',
  meta: 'italic text-muted-foreground',
}

export function SkillDiff({
  data,
  failure,
  placeholder = 'mock',
  className,
}: SkillDiffProps) {
  const usingMock = placeholder === 'mock' && data == null
  if (!usingMock && data == null) {
    return (
      <section
        aria-label="技能差异"
        className={cn('flex flex-col gap-2 rounded-md border bg-card p-3', className)}
      >
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          技能差异
        </h2>
        <p className="text-sm text-muted-foreground">
          尚无差异。失败原因只在「分析并改进」之后出现。
        </p>
      </section>
    )
  }
  const source = usingMock ? MOCK_SKILL_DIFF : data
  if (source == null) {
    return null
  }
  const failurePanel =
    usingMock && !hasFailureContent(failure)
      ? MOCK_SKILL_DIFF_FAILURE
      : (failure ?? emptySkillDiffFailure())
  const lines = parseUnifiedDiff(source.diff)
  const showFailure = hasFailureContent(failurePanel)

  return (
    <section
      aria-label="技能差异"
      className={cn('flex flex-col gap-4 rounded-md border bg-card p-3', className)}
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          技能差异
        </h2>
        <span className="text-xs text-muted-foreground">
          {usingMock
            ? '示例数据'
            : source.has_parent
              ? '上一版 → 当前版'
              : '无父版本'}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        父版本与候选版本制品的统一差异。失败类别、症状、证据和出处只来自改进接口，不会编造。
      </p>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="flex min-h-0 flex-col gap-2">
          <div className="flex flex-wrap gap-x-3 gap-y-1 font-mono text-xs text-muted-foreground">
            {source.version_id ? (
              <span>
                版本{' '}
                <span className="text-foreground">{source.version_id}</span>
              </span>
            ) : null}
            {source.parent_version_id ? (
              <span>
                父版本{' '}
                <span className="text-foreground">
                  {source.parent_version_id}
                </span>
              </span>
            ) : null}
          </div>
          <pre
            aria-label="统一差异"
            className="max-h-80 overflow-auto rounded-md border bg-muted/20 p-0 font-mono text-xs leading-5"
          >
            {lines.length === 0 ? (
              <div className="px-3 py-4 text-muted-foreground">
                {source.has_parent
                  ? '差异为空（文本没有变化）'
                  : '没有父版本，无法比较'}
              </div>
            ) : (
              <code className="block">
                {lines.map((line, index) => (
                  <div
                    key={`${index}:${line.kind}:${line.text.slice(0, 24)}`}
                    className={cn(
                      'whitespace-pre-wrap break-all px-3 py-0.5',
                      LINE_CLASS[line.kind],
                    )}
                  >
                    {line.text.length === 0 ? ' ' : line.text}
                  </div>
                ))}
              </code>
            )}
          </pre>
        </div>

        <aside
          aria-label="失败原因"
          className="flex flex-col gap-3 rounded-md border p-3"
        >
          <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            失败原因
          </h3>
          {!showFailure ? (
            <p className="text-sm text-muted-foreground">
              接口没有返回失败字段。请在改进之后加载版本；只拉取差异时这里保持空白。
            </p>
          ) : (
            <>
              <dl className="grid gap-2 text-sm">
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                    类别
                  </dt>
                  <dd className="font-mono text-sm">
                    {failurePanel.failure_class ?? '—'}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                    症状
                  </dt>
                  <dd className="text-sm">{failurePanel.symptom ?? '—'}</dd>
                </div>
              </dl>
              <EvidenceList
                label="证据"
                items={failurePanel.evidence}
                empty="无证据"
              />
              <EvidenceList
                label="出处"
                items={failurePanel.source_support}
                empty="无出处"
              />
            </>
          )}
        </aside>
      </div>
    </section>
  )
}

function EvidenceList({
  label,
  items,
  empty,
}: {
  label: string
  items: string[]
  empty: string
}) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      {items.length === 0 ? (
        <p className="mt-1 text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="mt-1 list-disc space-y-1 pl-4 text-sm">
          {items.map((item) => (
            <li key={item} className="break-words">
              {item}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
