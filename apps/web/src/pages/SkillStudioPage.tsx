import Editor from '@monaco-editor/react'
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'

import { apiRequest } from '@/lib/api'
import { skillStatusLabel } from '@/lib/labels'
import {
  parseSkillFrontmatter,
  parseSourceMapEvidence,
} from '@/pages/skillStudioModel'

type SkillDetail = {
  id: string
  project_id: string
  name: string
  description: string | null
  current_version_id: string | null
  status: string | null
}

type VersionItem = {
  id: string
  version: string
  status: string
  artifact_path: string | null
}

type VersionFile = {
  path: string
  text: string
}

export default function SkillStudioPage() {
  const { id: skillId = '' } = useParams<{ id: string }>()
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(
    null,
  )

  const skillQuery = useQuery({
    queryKey: ['skill', skillId],
    enabled: Boolean(skillId),
    queryFn: async () => {
      const result = await apiRequest<SkillDetail>(`/api/skills/${skillId}`)
      if (!result.ok) {
        throw new Error(result.body || `skill ${result.status}`)
      }
      return result.data
    },
  })

  const versionsQuery = useQuery({
    queryKey: ['skill-versions', skillId],
    enabled: Boolean(skillId),
    queryFn: async () => {
      const result = await apiRequest<VersionItem[]>(
        `/api/skills/${skillId}/versions`,
      )
      if (!result.ok) {
        throw new Error(result.body || `versions ${result.status}`)
      }
      return result.data
    },
  })

  const versions = versionsQuery.data ?? []
  const versionId = resolveVersionId(
    versions,
    skillQuery.data?.current_version_id ?? null,
    selectedVersionId,
  )

  const skillMdQuery = useQuery({
    queryKey: ['skill-file', skillId, versionId, 'SKILL.md'],
    enabled: Boolean(skillId && versionId),
    queryFn: async () => {
      const result = await apiRequest<VersionFile>(
        `/api/skills/${skillId}/versions/${versionId}/file?path=${encodeURIComponent('SKILL.md')}`,
      )
      if (!result.ok) {
        throw new Error(result.body || `SKILL.md ${result.status}`)
      }
      return result.data
    },
  })

  const sourceMapQuery = useQuery({
    queryKey: ['skill-file', skillId, versionId, 'source-map'],
    enabled: Boolean(skillId && versionId),
    queryFn: async () => {
      const result = await apiRequest<VersionFile>(
        `/api/skills/${skillId}/versions/${versionId}/file?path=${encodeURIComponent('references/source-map.json')}`,
      )
      if (!result.ok) {
        throw new Error(result.body || `source-map ${result.status}`)
      }
      return result.data
    },
  })

  const skillMdText = skillMdQuery.data?.text ?? ''
  const spec = parseSkillFrontmatter(skillMdText)
  const sourceMapText = sourceMapQuery.data?.text
  const evidence = useMemo(
    () => (sourceMapText ? parseSourceMapEvidence(sourceMapText) : []),
    [sourceMapText],
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 p-4">
      <header className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-xl font-semibold tracking-tight">
            技能工作室
            {skillQuery.data ? (
              <span className="ml-2 text-base font-normal text-muted-foreground">
                {skillQuery.data.name}
              </span>
            ) : null}
          </h1>
          <p className="truncate font-mono text-xs text-muted-foreground">
            {skillId}
            {skillQuery.data?.status
              ? ` · ${skillStatusLabel(skillQuery.data.status)}`
              : null}
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">版本</span>
          <select
            className="rounded-md border bg-background px-2 py-1.5 font-mono text-sm"
            value={versionId}
            disabled={!versions.length}
            onChange={(event) => setSelectedVersionId(event.target.value)}
          >
            {versions.map((version) => (
              <option key={version.id} value={version.id}>
                {version.version}（{skillStatusLabel(version.status)}）
              </option>
            ))}
          </select>
        </label>
        {skillId ? (
          <div className="flex flex-wrap gap-3 text-sm">
            <Link
              className="underline underline-offset-4"
              to={`/skills/${encodeURIComponent(skillId)}/evaluations`}
            >
              评测
            </Link>
            <Link
              className="underline underline-offset-4"
              to={`/skills/${encodeURIComponent(skillId)}/timeline`}
            >
              时间线
            </Link>
          </div>
        ) : null}
      </header>

      {skillQuery.isError ? (
        <p className="text-sm text-destructive">
          技能加载失败：{(skillQuery.error as Error).message}
        </p>
      ) : null}

      <div className="grid min-h-[70vh] flex-1 grid-cols-1 gap-3 lg:grid-cols-[220px_minmax(0,1fr)_240px]">
        <aside className="flex min-h-0 flex-col overflow-hidden rounded-md border bg-card">
          <h2 className="border-b px-3 py-2 text-sm font-medium">证据</h2>
          <div className="min-h-0 flex-1 overflow-auto p-2 text-xs">
            {sourceMapQuery.isLoading ? (
              <p className="text-muted-foreground">正在加载 source-map…</p>
            ) : sourceMapQuery.isError ? (
              <p className="text-destructive">
                {(sourceMapQuery.error as Error).message}
              </p>
            ) : evidence.length === 0 ? (
              <p className="text-muted-foreground">没有证据条目。</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {evidence.map((row) => (
                  <li
                    key={row.instructionId}
                    className="rounded border border-border/60 px-2 py-1.5"
                  >
                    <div className="font-mono font-medium">
                      {row.instructionId}
                    </div>
                    <div className="text-muted-foreground">
                      {row.document || '—'}
                    </div>
                    <div className="break-all font-mono text-[10px] text-muted-foreground">
                      {row.sha256 || '—'}
                    </div>
                    <div className="text-muted-foreground">
                      第 {row.page ?? '—'} 页 · 第 {row.lineStart ?? '—'} 行
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        <section className="flex min-h-[320px] flex-col overflow-hidden rounded-md border bg-card">
          <h2 className="border-b px-3 py-2 text-sm font-medium">SKILL.md</h2>
          <div className="min-h-0 flex-1">
            {skillMdQuery.isLoading ? (
              <p className="p-3 text-sm text-muted-foreground">加载中…</p>
            ) : skillMdQuery.isError ? (
              <p className="p-3 text-sm text-destructive">
                {(skillMdQuery.error as Error).message}
              </p>
            ) : (
              <Editor
                height="100%"
                defaultLanguage="markdown"
                theme="vs"
                value={skillMdText}
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  wordWrap: 'on',
                  scrollBeyondLastLine: false,
                  fontSize: 13,
                  lineNumbers: 'on',
                  renderLineHighlight: 'none',
                  domReadOnly: true,
                }}
              />
            )}
          </div>
        </section>

        <aside className="flex min-h-0 flex-col overflow-hidden rounded-md border bg-card">
          <h2 className="border-b px-3 py-2 text-sm font-medium">SkillSpec</h2>
          <dl className="min-h-0 flex-1 space-y-3 overflow-auto p-3 text-sm">
            <SpecField label="名称" value={spec.name} />
            <SpecField label="描述" value={spec.description} />
            <SpecField
              label="触发词"
              value={spec.triggers.length ? spec.triggers.join(', ') : null}
            />
            <SpecField
              label="工具"
              value={spec.tools.length ? spec.tools.join(', ') : null}
            />
          </dl>
        </aside>
      </div>
    </div>
  )
}

function resolveVersionId(
  versions: VersionItem[],
  currentVersionId: string | null,
  selectedVersionId: string | null,
): string {
  if (
    selectedVersionId &&
    versions.some((version) => version.id === selectedVersionId)
  ) {
    return selectedVersionId
  }
  if (
    currentVersionId &&
    versions.some((version) => version.id === currentVersionId)
  ) {
    return currentVersionId
  }
  return versions[0]?.id ?? ''
}

function SpecField({
  label,
  value,
}: {
  label: string
  value: string | null
}) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-0.5 break-words whitespace-pre-wrap">
        {value ?? '—'}
      </dd>
    </div>
  )
}
