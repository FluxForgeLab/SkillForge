import { Link } from 'react-router'

/** Placeholder until C9.5 Judge Mode. */
export default function DemoPage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-6">
      <h1 className="text-2xl font-semibold tracking-tight">Demo</h1>
      <p className="text-sm text-muted-foreground">
        Judge Mode lands in C9.5. This route is a shell placeholder.
      </p>
      <Link className="text-sm underline underline-offset-4" to="/">
        Back to home
      </Link>
    </div>
  )
}
