import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { apiFetch } from '@/lib/api'
import { cn } from '@/lib/utils'
import {
  documentFilename,
  formatKuLocation,
  type KnowledgeUnitWire,
  type ProjectWire,
  type SourceWire,
} from '@/pages/knowledgeLabModel'

/** Knowledge Lab lite: project docs + KU list with stored page/line (C9.11). */
export default function KnowledgeLabPage() {
  const [projectId, setProjectId] = useState('')
  const [selectedKuId, setSelectedKuId] = useState<string | null>(null)

  const projectsQuery = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiFetch<ProjectWire[]>('/api/projects'),
  })

  const sourcesQuery = useQuery({
    queryKey: ['project-sources', projectId],
    enabled: Boolean(projectId),
    queryFn: () =>
      apiFetch<SourceWire[]>(`/api/projects/${encodeURIComponent(projectId)}/sources`),
  })

  const knowledgeQuery = useQuery({
    queryKey: ['project-knowledge', projectId],
    enabled: Boolean(projectId),
    queryFn: () =>
      apiFetch<KnowledgeUnitWire[]>(
        `/api/projects/${encodeURIComponent(projectId)}/knowledge`,
      ),
  })

  const projects = projectsQuery.data ?? []
  const sources = sourcesQuery.data ?? []
  const units = knowledgeQuery.data ?? []
  const selected = units.find((unit) => unit.id === selectedKuId) ?? null

  function onProjectChange(nextId: string) {
    setProjectId(nextId)
    setSelectedKuId(null)
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-4 p-4 sm:p-6">
      <header className="border-b pb-4">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
          Knowledge Lab
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Documents and knowledge units for a project. Click a unit to see its
          stored source location (page or line).
        </p>
      </header>

      {projectsQuery.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading projects…</p>
      ) : projectsQuery.isError ? (
        <p className="text-sm text-destructive">
          Failed to load projects:{' '}
          {projectsQuery.error instanceof Error
            ? projectsQuery.error.message
            : 'unknown error'}
        </p>
      ) : projects.length === 0 ? (
        <p className="text-sm text-muted-foreground">No projects yet.</p>
      ) : (
        <>
          <label className="flex max-w-md flex-col gap-1 text-sm">
            <span className="font-medium">Project</span>
            <select
              className="rounded-md border bg-background px-3 py-2"
              value={projectId}
              onChange={(event) => onProjectChange(event.target.value)}
            >
              <option value="">Select a project…</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>

          {!projectId ? (
            <p className="text-sm text-muted-foreground">
              Choose a project to list documents and knowledge units.
            </p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              <section className="flex flex-col gap-2">
                <h2 className="text-sm font-semibold tracking-tight">
                  Documents
                </h2>
                {sourcesQuery.isLoading ? (
                  <p className="text-sm text-muted-foreground">Loading…</p>
                ) : sourcesQuery.isError ? (
                  <p className="text-sm text-destructive">
                    Failed to load documents.
                  </p>
                ) : sources.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No documents for this project.
                  </p>
                ) : (
                  <ul className="divide-y rounded-md border text-sm">
                    {sources.map((source) => (
                      <li key={source.id} className="px-3 py-2">
                        <div className="font-medium">{source.filename}</div>
                        <div className="font-mono text-xs text-muted-foreground">
                          {source.id} · {source.parser} · v{source.version}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className="flex flex-col gap-2">
                <h2 className="text-sm font-semibold tracking-tight">
                  Knowledge units
                </h2>
                {knowledgeQuery.isLoading ? (
                  <p className="text-sm text-muted-foreground">Loading…</p>
                ) : knowledgeQuery.isError ? (
                  <p className="text-sm text-destructive">
                    Failed to load knowledge units.
                  </p>
                ) : units.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No knowledge units for this project.
                  </p>
                ) : (
                  <ul className="divide-y rounded-md border text-sm">
                    {units.map((unit) => (
                      <li key={unit.id}>
                        <button
                          type="button"
                          className={cn(
                            'flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left hover:bg-muted/50',
                            selectedKuId === unit.id && 'bg-muted',
                          )}
                          onClick={() => setSelectedKuId(unit.id)}
                        >
                          <span className="font-medium">
                            {unit.title || unit.id}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {unit.type}
                            {unit.confidence != null
                              ? ` · conf ${unit.confidence.toFixed(2)}`
                              : ''}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          )}

          {selected ? (
            <SelectedKuDetail unit={selected} sources={sources} />
          ) : null}
        </>
      )}
    </div>
  )
}

function SelectedKuDetail({
  unit,
  sources,
}: {
  unit: KnowledgeUnitWire
  sources: readonly SourceWire[]
}) {
  const filename = documentFilename(unit.document_id, sources)
  const location = formatKuLocation(unit.source_location)

  return (
    <section className="rounded-md border p-4 text-sm">
      <h2 className="font-semibold tracking-tight">Selected unit</h2>
      <dl className="mt-2 grid gap-2 sm:grid-cols-2">
        <div>
          <dt className="text-xs text-muted-foreground">Title</dt>
          <dd>{unit.title || '—'}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Type</dt>
          <dd>{unit.type}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Document</dt>
          <dd>{filename}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Location</dt>
          <dd>{location}</dd>
        </div>
      </dl>
    </section>
  )
}
