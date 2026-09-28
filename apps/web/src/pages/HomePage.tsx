import { Link } from 'react-router'

import { Benchmark } from '@/components/Benchmark'
import { LiveTrace } from '@/components/LiveTrace'
import { PipelineStepper } from '@/components/PipelineStepper'
import { useEvents } from '@/hooks/useEvents'

export default function HomePage() {
  const { events, status, error } = useEvents()

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-6">
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

      <PipelineStepper events={events} />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <LiveTrace events={events} />
        <Benchmark />
      </div>
    </div>
  )
}
