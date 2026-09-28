import { useState } from 'react'
import { Link, useNavigate } from 'react-router'

/** Landing when nav hits /skills without an id. */
export default function SkillStudioEntry() {
  const navigate = useNavigate()
  const [draftId, setDraftId] = useState('')

  return (
    <div className="mx-auto flex w-full max-w-lg flex-col gap-4 p-6">
      <h1 className="text-xl font-semibold tracking-tight">Skill Studio</h1>
      <p className="text-sm text-muted-foreground">
        Open a skill by id (from compile / demo). Read-only SKILL.md, Spec, and
        evidence.
      </p>
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          const next = draftId.trim()
          if (next) {
            void navigate(`/skills/${encodeURIComponent(next)}`)
          }
        }}
      >
        <input
          className="min-w-0 flex-1 rounded-md border bg-background px-3 py-2 text-sm"
          placeholder="skill_…"
          value={draftId}
          onChange={(event) => setDraftId(event.target.value)}
        />
        <button
          type="submit"
          className="rounded-md border px-3 py-2 text-sm hover:bg-muted"
        >
          Open
        </button>
      </form>
      <p className="text-sm">
        <Link className="underline underline-offset-4" to="/demo">
          Compile one in Demo
        </Link>
      </p>
    </div>
  )
}
