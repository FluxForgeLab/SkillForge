import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { apiRequest } from '@/lib/api'
import { readRememberedSkillId } from '@/pages/demoSession'

type SkillListItem = {
  id: string
  project_id: string
  name: string
  description: string | null
  current_version_id: string | null
}

/** Landing when nav hits /skills without an id. */
export default function SkillStudioEntry() {
  const navigate = useNavigate()
  const [draftId, setDraftId] = useState(readRememberedSkillId)

  const skillsQuery = useQuery({
    queryKey: ['skills'],
    queryFn: async () => {
      const result = await apiRequest<SkillListItem[]>('/api/skills')
      if (!result.ok) {
        throw new Error(result.body || `skills ${result.status}`)
      }
      return result.data
    },
  })

  const skills = skillsQuery.data ?? []

  function open(pathSuffix: '' | '/evaluations' | '/timeline') {
    const next = draftId.trim()
    if (next) {
      void navigate(`/skills/${encodeURIComponent(next)}${pathSuffix}`)
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-lg flex-col gap-4 p-6">
      <h1 className="text-xl font-semibold tracking-tight">技能工作室</h1>
      <p className="text-sm text-muted-foreground">
        从已有技能里选择。工作室看 SKILL.md，评测页看用例矩阵，时间线看版本链和差值。
      </p>
      <form
        className="flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          open('')
        }}
      >
        <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          技能
        </label>
        <select
          className="h-10 rounded-md border bg-background px-2 text-sm"
          value={skills.some((skill) => skill.id === draftId) ? draftId : ''}
          onChange={(event) => setDraftId(event.target.value)}
          aria-label="选择技能"
        >
          <option value="">
            {skillsQuery.isLoading ? '正在加载技能…' : '选择技能'}
          </option>
          {skills.map((skill) => (
            <option key={skill.id} value={skill.id}>
              {skill.name}（{skill.id}）
            </option>
          ))}
        </select>
        {skillsQuery.isError ? (
          <p className="text-sm text-destructive">
            {(skillsQuery.error as Error).message}
          </p>
        ) : null}
        {skillsQuery.isSuccess && skills.length === 0 ? (
          <p className="text-sm text-muted-foreground">还没有技能。</p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            className="rounded-md border px-3 py-2 text-sm hover:bg-muted"
          >
            打开工作室
          </button>
          <button
            type="button"
            className="rounded-md border px-3 py-2 text-sm hover:bg-muted"
            onClick={() => open('/evaluations')}
          >
            打开评测
          </button>
          <button
            type="button"
            className="rounded-md border px-3 py-2 text-sm hover:bg-muted"
            onClick={() => open('/timeline')}
          >
            打开时间线
          </button>
        </div>
      </form>
      <p className="text-sm">
        <Link className="underline underline-offset-4" to="/demo">
          去演示里编译一个
        </Link>
      </p>
    </div>
  )
}
