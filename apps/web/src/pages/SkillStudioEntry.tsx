import { useState } from 'react'
import { Link, useNavigate } from 'react-router'

/** Landing when nav hits /skills without an id. */
export default function SkillStudioEntry() {
  const navigate = useNavigate()
  const [draftId, setDraftId] = useState('')

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
        用技能编号打开。工作室看 SKILL.md，评测页看用例矩阵，时间线看版本链和差值。
      </p>
      <form
        className="flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          open('')
        }}
      >
        <input
          className="min-w-0 w-full rounded-md border bg-background px-3 py-2 text-sm"
          placeholder="skill_…"
          value={draftId}
          onChange={(event) => setDraftId(event.target.value)}
        />
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
