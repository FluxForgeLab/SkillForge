import { Link } from 'react-router'

import { useEvents } from '@/hooks/useEvents'

export default function HomePage() {
  const { events, status, error } = useEvents()

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">SkillForge</h1>
        <p className="text-sm text-muted-foreground">
          Live event feed from <code className="text-foreground">/api/events</code>
          . Status: <span className="text-foreground">{status}</span>
          {error ? <span className="text-destructive"> — {error}</span> : null}
        </p>
        <p className="text-sm">
          <Link className="underline underline-offset-4" to="/demo">
            Demo (placeholder)
          </Link>
        </p>
      </header>

      <section aria-label="Trace events" className="flex flex-col gap-2">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          Events
        </h2>
        {events.length === 0 ? (
          <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            No events yet. Start the API and emit a TraceEvent to see type / name
            here.
          </p>
        ) : (
          <ul className="divide-y rounded-md border font-mono text-sm">
            {events.map((event) => (
              <li key={event.id} className="flex flex-wrap gap-x-3 gap-y-1 px-3 py-2">
                <span className="text-muted-foreground">
                  {event.timestamp}
                </span>
                <span className="font-medium">{event.type}</span>
                <span>{event.name ?? '—'}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
