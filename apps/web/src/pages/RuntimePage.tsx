import { Link } from 'react-router'

import { DgxRuntimePanel } from '@/components/DgxRuntimePanel'

/** Standalone DGX Runtime view (C9.10). */
export default function RuntimePage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4 sm:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b pb-4">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
          DGX Runtime
        </h1>
        <Link
          className="text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
          to="/demo"
        >
          Back to Demo
        </Link>
      </header>
      <p className="text-sm text-muted-foreground">
        Configured model identity from Settings. Tokens/s and memory stay{' '}
        <span className="text-foreground">not measured</span> until the
        StepFun adapter reports live metrics (C10.2).
      </p>
      <DgxRuntimePanel variant="section" />
    </div>
  )
}
