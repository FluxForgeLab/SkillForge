import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { apiFetch } from '@/lib/api'
import { knowledgeTypeLabel } from '@/lib/labels'
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
          知识库
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          查看项目里的文档和知识单元。点击一条单元，显示已保存的页码或行号。
        </p>
      </header>

      {projectsQuery.isLoading ? (
        <p className="text-sm text-muted-foreground">正在加载项目…</p>
      ) : projectsQuery.isError ? (
        <p className="text-sm text-destructive">
          项目加载失败：
          {projectsQuery.error instanceof Error
            ? projectsQuery.error.message
            : '未知错误'}
        </p>
      ) : projects.length === 0 ? (
        <p className="text-sm text-muted-foreground">还没有项目。</p>
      ) : (
        <>
          <label className="flex max-w-md flex-col gap-1 text-sm">
            <span className="font-medium">项目</span>
            <select
              className="rounded-md border bg-background px-3 py-2"
              value={projectId}
              onChange={(event) => onProjectChange(event.target.value)}
            >
              <option value="">选择项目…</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>

          {!projectId ? (
            <p className="text-sm text-muted-foreground">
              先选择一个项目，再列出文档和知识单元。
            </p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              <section className="flex flex-col gap-2">
                <h2 className="text-sm font-semibold tracking-tight">
                  文档
                </h2>
                {sourcesQuery.isLoading ? (
                  <p className="text-sm text-muted-foreground">加载中…</p>
                ) : sourcesQuery.isError ? (
                  <p className="text-sm text-destructive">
                    文档加载失败。
                  </p>
                ) : sources.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    这个项目还没有文档。
                  </p>
                ) : (
                  <ul className="divide-y rounded-md border bg-card text-sm">
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
                  知识单元
                </h2>
                {knowledgeQuery.isLoading ? (
                  <p className="text-sm text-muted-foreground">加载中…</p>
                ) : knowledgeQuery.isError ? (
                  <p className="text-sm text-destructive">
                    知识单元加载失败。
                  </p>
                ) : units.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    这个项目还没有知识单元。
                  </p>
                ) : (
                  <ul className="divide-y rounded-md border bg-card text-sm">
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
                            {knowledgeTypeLabel(unit.type)}
                            {unit.confidence != null
                              ? ` · 置信度 ${unit.confidence.toFixed(2)}`
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
    <section className="rounded-md border bg-card p-4 text-sm">
      <h2 className="font-semibold tracking-tight">选中的单元</h2>
      <dl className="mt-2 grid gap-2 sm:grid-cols-2">
        <div>
          <dt className="text-xs text-muted-foreground">标题</dt>
          <dd>{unit.title || '—'}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">类型</dt>
          <dd>{knowledgeTypeLabel(unit.type)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">文档</dt>
          <dd>{filename}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">位置</dt>
          <dd>{location}</dd>
        </div>
      </dl>
    </section>
  )
}
