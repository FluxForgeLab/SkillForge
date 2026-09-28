import { useEffect, useId, useRef, useState } from 'react'

import { Benchmark } from '@/components/Benchmark'
import type { BenchmarkData } from '@/components/benchmarkModel'
import { DgxRuntimePanel } from '@/components/DgxRuntimePanel'
import { LiveTrace } from '@/components/LiveTrace'
import { PipelineStepper } from '@/components/PipelineStepper'
import { SkillDiff } from '@/components/SkillDiff'
import {
  emptySkillDiffFailure,
  failureFromEvolve,
  type SkillDiffFailure,
  type SkillDiffPayload,
} from '@/components/skillDiffModel'
import { Button } from '@/components/ui/button'
import { useEvents, type TraceEventWire } from '@/hooks/useEvents'
import { API_BASE, apiRequest, type ApiResult } from '@/lib/api'
import {
  FAULT_IDS,
  buildBenchmarkFromRuns,
  defaultEvolveForm,
  prefillEvolveFromEvents,
  shortBody,
  type EvaluationRunWire,
  type EvolveFormState,
  type FaultId,
  type StepLogEntry,
} from '@/pages/demoJudgeModel'

type ProjectResponse = {
  id: string
  name: string
  description: string | null
  created_at: string
}

type SourceResponse = {
  id: string
  project_id: string
  filename: string
  sha256: string
  version: string
  parser: string
  created_at: string
}

type KnowledgeResponse = {
  id: string
  document_id: string
  type: string
  title: string
  confidence: number
}

type CompileResponse = {
  skill_id: string
  version_id: string
  status: string
}

type EvaluateJobResponse = { job_id: string }

type EvolveResponse = {
  skill_id: string
  version_id: string
  status: string
  parent_version_id: string
  failure_class?: string
  symptom?: string
  evidence?: string[]
  source_support?: string[]
}

type DiffApiResponse = {
  version_id: string
  parent_version_id: string | null
  has_parent: boolean
  diff: string
}

type HealthResponse = { status: string; service?: string }

type ApiHealth = 'checking' | 'online' | 'offline'

function nextLogId(): string {
  return `log_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`
}

function logFromResult(
  step: string,
  result: ApiResult<unknown>,
  okDetail: (data: unknown) => string,
): StepLogEntry {
  const at = new Date().toISOString()
  if (result.ok) {
    return {
      id: nextLogId(),
      step,
      status: result.status,
      detail: okDetail(result.data),
      at,
    }
  }
  return {
    id: nextLogId(),
    step,
    status: result.status,
    detail: shortBody(result.body),
    at,
  }
}

export default function DemoPage() {
  const { events, status: wsStatus, error: wsError } = useEvents(200)
  const [apiHealth, setApiHealth] = useState<ApiHealth>('checking')
  const [stepLog, setStepLog] = useState<StepLogEntry[]>([])
  const [busy, setBusy] = useState<string | null>(null)

  const [projectId, setProjectId] = useState('')
  const [projectName, setProjectName] = useState('service-recovery-demo')
  const [projectDescription, setProjectDescription] = useState(
    'Judge Mode live demo project',
  )
  const [sources, setSources] = useState<SourceResponse[]>([])
  const [knowledgeCount, setKnowledgeCount] = useState<number | null>(null)
  const [skillId, setSkillId] = useState('')
  const [versionId, setVersionId] = useState('')
  const [skillName, setSkillName] = useState('service-recovery')
  const [skillDescription, setSkillDescription] = useState(
    'Recover nginx upstream and backend from common outages',
  )
  const [triggersText, setTriggersText] = useState(
    'HTTP 502\nbackend unavailable\nhealth check failed',
  )
  const [faultId, setFaultId] = useState<FaultId>('backend_stopped')
  const [evalJobId, setEvalJobId] = useState<string | null>(null)
  const [benchmark, setBenchmark] = useState<BenchmarkData | undefined>(
    undefined,
  )
  const [approver, setApprover] = useState('judge')
  const [evolveForm, setEvolveForm] = useState<EvolveFormState>(defaultEvolveForm)
  const [skillDiff, setSkillDiff] = useState<SkillDiffPayload | null>(null)
  const [skillDiffFailure, setSkillDiffFailure] = useState<SkillDiffFailure>(
    emptySkillDiffFailure,
  )
  const fileInputRef = useRef<HTMLInputElement>(null)
  const fileInputId = useId()
  const handledEvalJobs = useRef(new Set<string>())

  const pushLog = (entry: StepLogEntry) => {
    setStepLog((prev) => [entry, ...prev].slice(0, 40))
  }

  // API health badge — real GET /health only; no invented DGX tokens/s (C9.10).
  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      try {
        const result = await apiRequest<HealthResponse>('/health')
        if (cancelled) return
        setApiHealth(
          result.ok && result.data.status === 'ok' ? 'online' : 'offline',
        )
      } catch {
        if (!cancelled) setApiHealth('offline')
      }
    }
    void tick()
    const id = window.setInterval(() => void tick(), 5000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  // evaluation_completed → fetch run payloads → Benchmark (existing GET evaluations).
  useEffect(() => {
    const completed = events.find(
      (e) =>
        e.type === 'evaluation_completed' &&
        !handledEvalJobs.current.has(e.run_id),
    )
    if (!completed || !skillId) {
      return
    }
    const jobKey = completed.run_id
    const status = completed.output.status
    if (status === 'failed') {
      handledEvalJobs.current.add(jobKey)
      const err =
        typeof completed.output.error === 'string'
          ? completed.output.error
          : JSON.stringify(completed.output)
      // Defer setState out of the sync effect body.
      queueMicrotask(() => {
        pushLog({
          id: nextLogId(),
          step: 'evaluate',
          status: null,
          detail: `evaluation_completed failed job=${jobKey}: ${shortBody(err)}`,
          at: new Date().toISOString(),
        })
      })
      return
    }
    if (status !== 'completed' || !Array.isArray(completed.output.run_ids)) {
      return
    }
    const runIds = (completed.output.run_ids as unknown[]).filter(
      (id): id is string => typeof id === 'string',
    )
    if (runIds.length === 0) {
      return
    }
    handledEvalJobs.current.add(jobKey)
    let cancelled = false
    void (async () => {
      const runs: EvaluationRunWire[] = []
      for (const runId of runIds) {
        const result = await apiRequest<EvaluationRunWire>(
          `/api/skills/${skillId}/evaluations/${runId}`,
        )
        if (cancelled) return
        if (result.ok) {
          runs.push(result.data)
        } else {
          pushLog({
            id: nextLogId(),
            step: 'evaluate',
            status: result.status,
            detail: `fetch run ${runId}: ${shortBody(result.body)}`,
            at: new Date().toISOString(),
          })
        }
      }
      if (cancelled) return
      pushLog({
        id: nextLogId(),
        step: 'evaluate',
        status: null,
        detail: `evaluation_completed job=${jobKey} run_ids=${runIds.join(',')}`,
        at: new Date().toISOString(),
      })
      const data = buildBenchmarkFromRuns(runs)
      if (data) {
        setBenchmark(data)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [events, skillId])

  const suggestedRunId = (() => {
    const filled = prefillEvolveFromEvents(events, defaultEvolveForm())
    return filled.run_id
  })()

  const runAction = async (
    step: string,
    action: () => Promise<void>,
  ): Promise<void> => {
    if (busy) return
    setBusy(step)
    try {
      await action()
    } catch (err) {
      pushLog({
        id: nextLogId(),
        step,
        status: null,
        detail: err instanceof Error ? err.message : String(err),
        at: new Date().toISOString(),
      })
    } finally {
      setBusy(null)
    }
  }

  const onCreateProject = () =>
    void runAction('create', async () => {
      const result = await apiRequest<ProjectResponse>('/api/projects', {
        method: 'POST',
        body: JSON.stringify({
          name: projectName,
          description: projectDescription,
        }),
      })
      pushLog(
        logFromResult('create', result, (data) => {
          const p = data as ProjectResponse
          return `project ${p.id}`
        }),
      )
      if (result.ok) {
        setProjectId(result.data.id)
        setSources([])
        setKnowledgeCount(null)
      }
    })

  const onUpload = () =>
    void runAction('upload', async () => {
      if (!projectId) {
        pushLog({
          id: nextLogId(),
          step: 'upload',
          status: null,
          detail: 'Create a project first',
          at: new Date().toISOString(),
        })
        return
      }
      const file = fileInputRef.current?.files?.[0]
      if (!file) {
        pushLog({
          id: nextLogId(),
          step: 'upload',
          status: null,
          detail: 'Choose a file first',
          at: new Date().toISOString(),
        })
        return
      }
      const form = new FormData()
      form.append('file', file)
      const result = await apiRequest<SourceResponse>(
        `/api/projects/${projectId}/sources`,
        { method: 'POST', body: form },
      )
      pushLog(
        logFromResult('upload', result, (data) => {
          const s = data as SourceResponse
          return `${s.filename} (${s.id})`
        }),
      )
      if (result.ok) {
        setSources((prev) => [result.data, ...prev])
      }
    })

  const onExtract = () =>
    void runAction('extract', async () => {
      if (!projectId) {
        pushLog({
          id: nextLogId(),
          step: 'extract',
          status: null,
          detail: 'Create a project first',
          at: new Date().toISOString(),
        })
        return
      }
      const result = await apiRequest<KnowledgeResponse[]>(
        `/api/projects/${projectId}/extract`,
        { method: 'POST' },
      )
      pushLog(
        logFromResult(
          'extract',
          result,
          (data) => `${(data as KnowledgeResponse[]).length} knowledge unit(s)`,
        ),
      )
      if (result.ok) {
        setKnowledgeCount(result.data.length)
      }
    })

  const onCompile = () =>
    void runAction('compile', async () => {
      if (!projectId) {
        pushLog({
          id: nextLogId(),
          step: 'compile',
          status: null,
          detail: 'Create a project first',
          at: new Date().toISOString(),
        })
        return
      }
      const triggers = triggersText
        .split('\n')
        .map((t) => t.trim())
        .filter(Boolean)
      const result = await apiRequest<CompileResponse>(
        `/api/projects/${projectId}/skills/compile`,
        {
          method: 'POST',
          body: JSON.stringify({
            name: skillName,
            description: skillDescription,
            triggers,
          }),
        },
      )
      pushLog(
        logFromResult('compile', result, (data) => {
          const c = data as CompileResponse
          return `skill=${c.skill_id} version=${c.version_id} status=${c.status}`
        }),
      )
      if (result.ok) {
        setSkillId(result.data.skill_id)
        setVersionId(result.data.version_id)
        handledEvalJobs.current.clear()
        setBenchmark(undefined)
        setEvalJobId(null)
      }
    })

  const onInject = () =>
    void runAction('inject', async () => {
      const result = await apiRequest<{ fault_id: string }>(
        `/api/demo/faults/${faultId}/inject`,
        { method: 'POST' },
      )
      pushLog(
        logFromResult(
          'inject',
          result,
          (data) => `fault ${(data as { fault_id: string }).fault_id}`,
        ),
      )
    })

  const onReset = () =>
    void runAction('reset', async () => {
      const result = await apiRequest<{ status: string }>('/api/demo/reset', {
        method: 'POST',
      })
      pushLog(
        logFromResult(
          'reset',
          result,
          (data) => (data as { status: string }).status,
        ),
      )
    })

  const onEvaluate = () =>
    void runAction('evaluate', async () => {
      if (!skillId) {
        pushLog({
          id: nextLogId(),
          step: 'evaluate',
          status: null,
          detail: 'Compile a skill first',
          at: new Date().toISOString(),
        })
        return
      }
      const result = await apiRequest<EvaluateJobResponse>(
        `/api/skills/${skillId}/evaluate`,
        {
          method: 'POST',
          body: JSON.stringify({ repeats: 1 }),
        },
      )
      pushLog(
        logFromResult('evaluate', result, (data) => {
          const j = data as EvaluateJobResponse
          return `202 accepted job_id=${j.job_id} (await evaluation_completed)`
        }),
      )
      if (result.ok) {
        setEvalJobId(result.data.job_id)
      }
    })

  const onEvolve = () =>
    void runAction('evolve', async () => {
      if (!skillId) {
        pushLog({
          id: nextLogId(),
          step: 'evolve',
          status: null,
          detail: 'Compile a skill first',
          at: new Date().toISOString(),
        })
        return
      }
      let assertion: unknown
      let verifier: unknown
      let source_map_updates: unknown
      try {
        assertion = JSON.parse(evolveForm.assertionJson) as unknown
        verifier = JSON.parse(evolveForm.verifierJson) as unknown
        source_map_updates = JSON.parse(
          evolveForm.sourceMapUpdatesJson,
        ) as unknown
      } catch (err) {
        pushLog({
          id: nextLogId(),
          step: 'evolve',
          status: null,
          detail: `Invalid JSON: ${err instanceof Error ? err.message : String(err)}`,
          at: new Date().toISOString(),
        })
        return
      }
      if (!evolveForm.run_id.trim()) {
        pushLog({
          id: nextLogId(),
          step: 'evolve',
          status: null,
          detail: 'run_id is required',
          at: new Date().toISOString(),
        })
        return
      }
      const runEvents: TraceEventWire[] = events.filter(
        (e) => e.run_id === evolveForm.run_id.trim(),
      )
      const body = {
        version: evolveForm.version.trim() || 'v0.2',
        run_id: evolveForm.run_id.trim(),
        assertion,
        verifier,
        source_map_updates,
        ...(runEvents.length > 0 ? { events: runEvents } : {}),
      }
      const result = await apiRequest<EvolveResponse>(
        `/api/skills/${skillId}/evolve`,
        {
          method: 'POST',
          body: JSON.stringify(body),
        },
      )
      pushLog(
        logFromResult('evolve', result, (data) => {
          const e = data as EvolveResponse
          return `version=${e.version_id} status=${e.status} class=${e.failure_class ?? '—'}`
        }),
      )
      if (result.ok) {
        setVersionId(result.data.version_id)
        setSkillDiffFailure(failureFromEvolve(result.data))
        const diffResult = await apiRequest<DiffApiResponse>(
          `/api/skills/${skillId}/versions/${result.data.version_id}/diff`,
        )
        pushLog(
          logFromResult('diff', diffResult, (data) => {
            const d = data as DiffApiResponse
            return `has_parent=${d.has_parent} lines=${d.diff.split('\n').length}`
          }),
        )
        if (diffResult.ok) {
          setSkillDiff({
            version_id: diffResult.data.version_id,
            parent_version_id: diffResult.data.parent_version_id,
            has_parent: diffResult.data.has_parent,
            diff: diffResult.data.diff,
          })
        }
      }
    })

  const onApprove = () =>
    void runAction('approve', async () => {
      if (!skillId || !versionId) {
        pushLog({
          id: nextLogId(),
          step: 'approve',
          status: null,
          detail: 'Need skill_id and version_id',
          at: new Date().toISOString(),
        })
        return
      }
      const result = await apiRequest<{ version_id: string; status: string }>(
        `/api/skills/${skillId}/versions/${versionId}/approve`,
        {
          method: 'POST',
          body: JSON.stringify({ approver }),
        },
      )
      pushLog(
        logFromResult(
          'approve',
          result,
          (data) =>
            `version=${(data as { version_id: string }).version_id} status=${(data as { status: string }).status}`,
        ),
      )
    })

  const onPublish = () =>
    void runAction('publish', async () => {
      if (!skillId || !versionId) {
        pushLog({
          id: nextLogId(),
          step: 'publish',
          status: null,
          detail: 'Need skill_id and version_id',
          at: new Date().toISOString(),
        })
        return
      }
      const result = await apiRequest<{
        version_id: string
        status: string
        published_path: string
      }>(`/api/skills/${skillId}/versions/${versionId}/publish`, {
        method: 'POST',
      })
      pushLog(
        logFromResult(
          'publish',
          result,
          (data) =>
            `status=${(data as { status: string }).status} path=${(data as { published_path: string }).published_path}`,
        ),
      )
    })

  const onPrefillEvolve = () => {
    setEvolveForm((prev) => prefillEvolveFromEvents(events, prev))
  }

  const onLoadDiff = () =>
    void runAction('diff', async () => {
      if (!skillId.trim() || !versionId.trim()) {
        pushLog({
          id: nextLogId(),
          step: 'diff',
          status: null,
          detail: 'Enter skill_id and version_id',
          at: new Date().toISOString(),
        })
        return
      }
      // Diff-only load: do not invent failure fields.
      setSkillDiffFailure(emptySkillDiffFailure())
      const result = await apiRequest<DiffApiResponse>(
        `/api/skills/${skillId.trim()}/versions/${versionId.trim()}/diff`,
      )
      pushLog(
        logFromResult('diff', result, (data) => {
          const d = data as DiffApiResponse
          return `has_parent=${d.has_parent} parent=${d.parent_version_id ?? 'none'}`
        }),
      )
      if (result.ok) {
        setSkillDiff({
          version_id: result.data.version_id,
          parent_version_id: result.data.parent_version_id,
          has_parent: result.data.has_parent,
          diff: result.data.diff,
        })
      }
    })

  const healthLabel =
    apiHealth === 'online'
      ? 'Online'
      : apiHealth === 'offline'
        ? 'Offline'
        : 'Checking…'
  const healthDot =
    apiHealth === 'online'
      ? 'bg-emerald-600'
      : apiHealth === 'offline'
        ? 'bg-destructive'
        : 'bg-muted-foreground'

  return (
    <div className="mx-auto flex w-full max-w-[90rem] flex-col gap-4 p-4 sm:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b pb-4">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
          SkillForge — Live Demo
        </h1>
        <div className="flex flex-wrap items-center gap-2">
          <div
            className="flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm"
            title={`GET ${API_BASE}/health`}
          >
            <span
              className={`size-2.5 rounded-full ${healthDot}`}
              aria-hidden
            />
            <span className="text-muted-foreground">API</span>
            <span className="font-medium">{healthLabel}</span>
          </div>
          <DgxRuntimePanel variant="header" />
        </div>
      </header>

      <DgxRuntimePanel variant="section" />

      <p className="text-xs text-muted-foreground">
        WS <code className="text-foreground">/api/events</code>:{' '}
        <span className="text-foreground">{wsStatus}</span>
        {wsError ? (
          <span className="text-destructive"> — {wsError}</span>
        ) : null}
        {evalJobId ? (
          <span>
            {' '}
            · pending eval job <code className="text-foreground">{evalJobId}</code>
          </span>
        ) : null}
        {skillId ? (
          <span>
            {' '}
            · skill <code className="text-foreground">{skillId}</code>
            {versionId ? (
              <>
                {' '}
                / <code className="text-foreground">{versionId}</code>
              </>
            ) : null}
          </span>
        ) : null}
      </p>

      <section
        aria-label="Judge Mode controls"
        className="flex flex-col gap-3 rounded-md border p-3"
      >
        <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
          <div className="flex flex-col gap-2">
            <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Project
            </label>
            <input
              className="h-8 rounded-md border bg-background px-2 text-sm"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="name"
            />
            <input
              className="h-8 rounded-md border bg-background px-2 text-sm"
              value={projectDescription}
              onChange={(e) => setProjectDescription(e.target.value)}
              placeholder="description"
            />
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                disabled={busy !== null}
                onClick={onCreateProject}
              >
                Create project
              </Button>
              {projectId ? (
                <span className="self-center font-mono text-xs text-muted-foreground">
                  {projectId}
                </span>
              ) : null}
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <label
              className="text-xs font-medium uppercase tracking-wide text-muted-foreground"
              htmlFor={fileInputId}
            >
              Upload source
            </label>
            <input
              id={fileInputId}
              ref={fileInputRef}
              type="file"
              className="text-sm"
            />
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={busy !== null}
                onClick={onUpload}
              >
                Upload
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={busy !== null}
                onClick={onExtract}
              >
                Extract
              </Button>
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Compile skill
            </label>
            <input
              className="h-8 rounded-md border bg-background px-2 text-sm"
              value={skillName}
              onChange={(e) => setSkillName(e.target.value)}
              placeholder="skill name"
            />
            <input
              className="h-8 rounded-md border bg-background px-2 text-sm"
              value={skillDescription}
              onChange={(e) => setSkillDescription(e.target.value)}
              placeholder="description"
            />
            <textarea
              className="min-h-[4.5rem] rounded-md border bg-background px-2 py-1 font-mono text-xs"
              value={triggersText}
              onChange={(e) => setTriggersText(e.target.value)}
              placeholder="triggers (one per line)"
            />
            <Button
              type="button"
              size="sm"
              disabled={busy !== null}
              onClick={onCompile}
            >
              Compile
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-2 border-t pt-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Fault
            </label>
            <select
              className="h-8 rounded-md border bg-background px-2 text-sm"
              value={faultId}
              onChange={(e) => setFaultId(e.target.value as FaultId)}
            >
              {FAULT_IDS.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy !== null}
            onClick={onInject}
          >
            Inject Fault
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy !== null}
            onClick={onReset}
          >
            Reset lab
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={busy !== null}
            onClick={onEvaluate}
          >
            Evaluate
          </Button>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Approver
            </label>
            <input
              className="h-8 w-32 rounded-md border bg-background px-2 text-sm"
              value={approver}
              onChange={(e) => setApprover(e.target.value)}
            />
          </div>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={busy !== null}
            onClick={onApprove}
          >
            Approve
          </Button>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={busy !== null}
            onClick={onPublish}
          >
            Publish
          </Button>
        </div>

        <div className="grid gap-2 border-t pt-3 lg:grid-cols-2">
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Analyze &amp; Improve (EvolveRequest)
              </label>
              <Button
                type="button"
                size="xs"
                variant="ghost"
                onClick={onPrefillEvolve}
              >
                Prefill from trace
              </Button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <input
                className="h-8 rounded-md border bg-background px-2 font-mono text-xs"
                value={evolveForm.version}
                onChange={(e) =>
                  setEvolveForm((p) => ({ ...p, version: e.target.value }))
                }
                placeholder="version"
              />
              <input
                className="h-8 rounded-md border bg-background px-2 font-mono text-xs"
                value={evolveForm.run_id}
                onChange={(e) =>
                  setEvolveForm((p) => ({ ...p, run_id: e.target.value }))
                }
                placeholder={
                  suggestedRunId
                    ? `run_id (e.g. ${suggestedRunId})`
                    : 'run_id (editable)'
                }
              />
            </div>
            <textarea
              className="min-h-[5rem] rounded-md border bg-background px-2 py-1 font-mono text-xs"
              value={evolveForm.assertionJson}
              onChange={(e) =>
                setEvolveForm((p) => ({
                  ...p,
                  assertionJson: e.target.value,
                }))
              }
              aria-label="assertion JSON"
            />
            <textarea
              className="min-h-[3.5rem] rounded-md border bg-background px-2 py-1 font-mono text-xs"
              value={evolveForm.verifierJson}
              onChange={(e) =>
                setEvolveForm((p) => ({
                  ...p,
                  verifierJson: e.target.value,
                }))
              }
              aria-label="verifier JSON"
            />
            <textarea
              className="min-h-[2.5rem] rounded-md border bg-background px-2 py-1 font-mono text-xs"
              value={evolveForm.sourceMapUpdatesJson}
              onChange={(e) =>
                setEvolveForm((p) => ({
                  ...p,
                  sourceMapUpdatesJson: e.target.value,
                }))
              }
              aria-label="source_map_updates JSON"
            />
            <Button
              type="button"
              size="sm"
              disabled={busy !== null}
              onClick={onEvolve}
            >
              Analyze &amp; Improve
            </Button>
            <div className="mt-2 flex flex-col gap-2 border-t pt-2">
              <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Skill Diff lookup
              </label>
              <input
                className="h-8 rounded-md border bg-background px-2 font-mono text-xs"
                value={skillId}
                onChange={(e) => setSkillId(e.target.value)}
                placeholder="skill_id"
                aria-label="skill_id for diff"
              />
              <input
                className="h-8 rounded-md border bg-background px-2 font-mono text-xs"
                value={versionId}
                onChange={(e) => setVersionId(e.target.value)}
                placeholder="version_id"
                aria-label="version_id for diff"
              />
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={busy !== null}
                onClick={onLoadDiff}
              >
                Load Diff
              </Button>
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Step log
            </h2>
            <ul className="max-h-64 overflow-y-auto rounded-md border font-mono text-xs">
              {stepLog.length === 0 ? (
                <li className="px-3 py-2 text-muted-foreground">
                  No API calls yet
                </li>
              ) : (
                stepLog.map((entry) => (
                  <li
                    key={entry.id}
                    className="border-b px-3 py-1.5 last:border-b-0"
                  >
                    <span className="text-muted-foreground">
                      {entry.at.slice(11, 19)}
                    </span>{' '}
                    <span className="font-sans font-medium">{entry.step}</span>{' '}
                    {entry.status !== null ? (
                      <span
                        className={
                          entry.status >= 200 && entry.status < 300
                            ? 'text-emerald-700'
                            : 'text-destructive'
                        }
                      >
                        HTTP {entry.status}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                    <div className="break-words text-muted-foreground">
                      {entry.detail}
                    </div>
                  </li>
                ))
              )}
            </ul>
            {busy ? (
              <p className="text-xs text-muted-foreground">Busy: {busy}…</p>
            ) : null}
          </div>
        </div>
      </section>

      {/* Four zones — architecture §10.1 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section
          aria-label="Source Knowledge"
          className="flex flex-col gap-2 rounded-md border p-3"
        >
          <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
            Source Knowledge
          </h2>
          <p className="text-xs text-muted-foreground">
            Uploaded runbooks and extracted knowledge units for the active
            project.
          </p>
          {projectId ? (
            <p className="font-mono text-xs text-muted-foreground">
              project {projectId}
              {knowledgeCount !== null
                ? ` · ${knowledgeCount} KU(s)`
                : null}
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">
              Create a project and upload a source to populate this zone.
            </p>
          )}
          <ul className="divide-y rounded-md border text-sm">
            {sources.length === 0 ? (
              <li className="px-3 py-2 text-muted-foreground">No sources yet</li>
            ) : (
              sources.map((s) => (
                <li key={s.id} className="px-3 py-2">
                  <div className="font-medium">{s.filename}</div>
                  <div className="font-mono text-xs text-muted-foreground">
                    {s.parser} · {s.sha256.slice(0, 12)}…
                  </div>
                </li>
              ))
            )}
          </ul>
        </section>

        <PipelineStepper
          events={events}
          placeholder="empty"
          className="rounded-md border p-3"
        />

        <LiveTrace
          events={events}
          placeholder="empty"
          className="rounded-md border p-3"
        />

        <Benchmark
          data={benchmark}
          placeholder="empty"
          className="rounded-md border p-3"
        />
      </div>

      <SkillDiff
        data={skillDiff}
        failure={skillDiffFailure}
        placeholder="empty"
        className="rounded-md border p-3"
      />
    </div>
  )
}
