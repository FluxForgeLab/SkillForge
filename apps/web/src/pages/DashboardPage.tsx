import { useQuery } from '@tanstack/react-query'

import { apiFetch } from '@/lib/api'
import type { ProjectWire } from '@/pages/knowledgeLabModel'

type SkillListItem = {
  id: string
  project_id: string
  name: string
  description: string | null
  current_version_id: string | null
}

type SourceWire = { id: string }
type KnowledgeUnitWire = { id: string }

type DashboardCounts = {
  projects: number
  documents: number
  knowledgeUnits: number
  skills: number
}

async function loadDashboardCounts(): Promise<DashboardCounts> {
  const [projects, skills] = await Promise.all([
    apiFetch<ProjectWire[]>('/api/projects'),
    apiFetch<SkillListItem[]>('/api/skills'),
  ])

  const perProject = await Promise.all(
    projects.map(async (project) => {
      const [sources, units] = await Promise.all([
        apiFetch<SourceWire[]>(
          `/api/projects/${encodeURIComponent(project.id)}/sources`,
        ),
        apiFetch<KnowledgeUnitWire[]>(
          `/api/projects/${encodeURIComponent(project.id)}/knowledge`,
        ),
      ])
      return { sources: sources.length, units: units.length }
    }),
  )

  return {
    projects: projects.length,
    documents: perProject.reduce((sum, row) => sum + row.sources, 0),
    knowledgeUnits: perProject.reduce((sum, row) => sum + row.units, 0),
    skills: skills.length,
  }
}

const CARDS: { key: keyof DashboardCounts; label: string }[] = [
  { key: 'projects', label: 'Projects' },
  { key: 'documents', label: 'Documents' },
  { key: 'knowledgeUnits', label: 'Knowledge units' },
  { key: 'skills', label: 'Skills' },
]

/** Live count cards from projects / sources / knowledge / skills APIs (C9.12). */
export default function DashboardPage() {
  const countsQuery = useQuery({
    queryKey: ['dashboard-counts'],
    queryFn: loadDashboardCounts,
  })

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-4 p-4 sm:p-6">
      <header className="border-b pb-4">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
          Dashboard
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Counts from live API endpoints. Empty lists show 0; fetch failures
          show an error.
        </p>
      </header>

      {countsQuery.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading dashboard…</p>
      ) : countsQuery.isError ? (
        <p className="text-sm text-destructive" role="alert">
          Failed to load dashboard:{' '}
          {countsQuery.error instanceof Error
            ? countsQuery.error.message
            : 'unknown error'}
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {CARDS.map((card) => (
            <div
              key={card.key}
              className="flex flex-col gap-1 border-b border-border pb-3"
            >
              <span className="text-sm text-muted-foreground">{card.label}</span>
              <span className="text-3xl font-semibold tabular-nums tracking-tight">
                {countsQuery.data?.[card.key] ?? 0}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
