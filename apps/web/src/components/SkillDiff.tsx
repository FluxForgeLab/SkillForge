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
        aria-label="Skill Diff"
        className={cn('flex flex-col gap-2', className)}
      >
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          Skill Diff
        </h2>
        <p className="text-sm text-muted-foreground">
          No diff yet. Failure reason appears only after Analyze &amp; Improve.
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
      aria-label="Skill Diff"
      className={cn('flex flex-col gap-4', className)}
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          Skill Diff
        </h2>
        <span className="text-xs text-muted-foreground">
          {usingMock
            ? 'mock sample'
            : source.has_parent
              ? 'v(n-1) → v(n)'
              : 'no parent'}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        Unified diff between parent and candidate skill artifacts. Failure
        class, symptom, evidence, and source_support come from evolve when
        available — never invented.
      </p>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="flex min-h-0 flex-col gap-2">
          <div className="flex flex-wrap gap-x-3 gap-y-1 font-mono text-xs text-muted-foreground">
            {source.version_id ? (
              <span>
                version{' '}
                <span className="text-foreground">{source.version_id}</span>
              </span>
            ) : null}
            {source.parent_version_id ? (
              <span>
                parent{' '}
                <span className="text-foreground">
                  {source.parent_version_id}
                </span>
              </span>
            ) : null}
          </div>
          <pre
            aria-label="Unified diff"
            className="max-h-80 overflow-auto rounded-md border bg-muted/20 p-0 font-mono text-xs leading-5"
          >
            {lines.length === 0 ? (
              <div className="px-3 py-4 text-muted-foreground">
                {source.has_parent
                  ? 'Empty diff (no text changes)'
                  : 'No parent version — nothing to diff'}
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
          aria-label="Failure reason"
          className="flex flex-col gap-3 rounded-md border p-3"
        >
          <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Failure reason
          </h3>
          {!showFailure ? (
            <p className="text-sm text-muted-foreground">
              No failure fields from the API. Load a version after evolve, or
              empty evidence state when only the diff endpoint was called.
            </p>
          ) : (
            <>
              <dl className="grid gap-2 text-sm">
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                    Class
                  </dt>
                  <dd className="font-mono text-sm">
                    {failurePanel.failure_class ?? '—'}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                    Symptom
                  </dt>
                  <dd className="text-sm">{failurePanel.symptom ?? '—'}</dd>
                </div>
              </dl>
              <EvidenceList
                label="Evidence"
                items={failurePanel.evidence}
                empty="No evidence"
              />
              <EvidenceList
                label="Source support"
                items={failurePanel.source_support}
                empty="No source_support"
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
