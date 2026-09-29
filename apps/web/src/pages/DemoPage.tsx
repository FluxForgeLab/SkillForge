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
import { demoStepLabel, skillStatusLabel, wsStatusLabel } from '@/lib/labels'
import {
  FAULT_IDS,
  apiErrorDetail,
  buildBenchmarkFromRuns,
  defaultEvolveForm,
  prefillEvolveFromEvents,
  shortBody,
  type EvaluationRunWire,
  type EvolveFormState,
  type FaultId,
  type StepLogEntry,
} from '@/pages/demoJudgeModel'
import { loadDemoSession, saveDemoSession } from '@/pages/demoSession'

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

type EvalJobWire = {
  id: string
  status: string
  error: string | null
  result: unknown
}

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
      detail: apiErrorDetail(result.body),
    at,
  }
}

export default function DemoPage() {
  const [restored] = useState(loadDemoSession)
  const { events, status: wsStatus, error: wsError } = useEvents(
    200,
    restored.events,
  )
  const [apiHealth, setApiHealth] = useState<ApiHealth>('checking')
  const [stepLog, setStepLog] = useState<StepLogEntry[]>(restored.stepLog)
  const [busy, setBusy] = useState<string | null>(null)

  const [projectId, setProjectId] = useState(restored.projectId)
  const [projectName, setProjectName] = useState(restored.projectName)
  const [projectDescription, setProjectDescription] = useState(
    restored.projectDescription,
  )
  const [sources, setSources] = useState<SourceResponse[]>(restored.sources)
  const [knowledgeCount, setKnowledgeCount] = useState<number | null>(
    restored.knowledgeCount,
  )
  const [skillId, setSkillId] = useState(restored.skillId)
  const [versionId, setVersionId] = useState(restored.versionId)
  const [skillName, setSkillName] = useState(restored.skillName)
  const [skillDescription, setSkillDescription] = useState(
    restored.skillDescription,
  )
  const [triggersText, setTriggersText] = useState(restored.triggersText)
  const [faultId, setFaultId] = useState<FaultId>(restored.faultId)
  const [evalJobId, setEvalJobId] = useState<string | null>(restored.evalJobId)
  const [benchmark, setBenchmark] = useState<BenchmarkData | undefined>(
    restored.benchmark,
  )
  const [approver, setApprover] = useState(restored.approver)
  const [evolveForm, setEvolveForm] = useState<EvolveFormState>(
    restored.evolveForm,
  )
  const [skillDiff, setSkillDiff] = useState<SkillDiffPayload | null>(
    restored.skillDiff,
  )
  const [skillDiffFailure, setSkillDiffFailure] = useState<SkillDiffFailure>(
    restored.skillDiffFailure,
  )
  const fileInputRef = useRef<HTMLInputElement>(null)
  const fileInputId = useId()
  const handledEvalJobs = useRef(new Set(restored.handledEvalJobIds))

  const pushLog = (entry: StepLogEntry) => {
    setStepLog((prev) => [entry, ...prev].slice(0, 40))
  }

  useEffect(() => {
    saveDemoSession({
      projectId,
      projectName,
      projectDescription,
      sources,
      knowledgeCount,
      skillId,
      versionId,
      skillName,
      skillDescription,
      triggersText,
      faultId,
      evalJobId,
      benchmark,
      approver,
      evolveForm,
      skillDiff,
      skillDiffFailure,
      stepLog,
      handledEvalJobIds: Array.from(handledEvalJobs.current),
      events,
    })
  }, [
    projectId,
    projectName,
    projectDescription,
    sources,
    knowledgeCount,
    skillId,
    versionId,
    skillName,
    skillDescription,
    triggersText,
    faultId,
    evalJobId,
    benchmark,
    approver,
    evolveForm,
    skillDiff,
    skillDiffFailure,
    stepLog,
    events,
  ])

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
        setEvalJobId(null)
        pushLog({
          id: nextLogId(),
          step: 'evaluate',
          status: null,
          detail: `评测失败 job=${jobKey}：${shortBody(err)}`,
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
    queueMicrotask(() => {
      setEvalJobId(null)
    })
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
            detail: `读取运行 ${runId}：${shortBody(result.body)}`,
            at: new Date().toISOString(),
          })
        }
      }
      if (cancelled) return
      pushLog({
        id: nextLogId(),
        step: 'evaluate',
        status: null,
        detail: `评测完成 job=${jobKey} run_ids=${runIds.join(',')}`,
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

  // The accept log says "等待评测完成" immediately. Job status is the
  // completion signal when the WebSocket event was missed.
  useEffect(() => {
    if (!evalJobId || !skillId) {
      return
    }
    let cancelled = false
    const tick = async () => {
      if (handledEvalJobs.current.has(evalJobId)) {
        setEvalJobId(null)
        return
      }
      const result = await apiRequest<EvalJobWire>(`/api/jobs/${evalJobId}`)
      if (cancelled) {
        return
      }
      if (!result.ok) {
        if (result.status === 404) {
          handledEvalJobs.current.add(evalJobId)
          setEvalJobId(null)
          pushLog({
            id: nextLogId(),
            step: 'evaluate',
            status: 404,
            detail: '评测任务已结束或服务已重启，请再点一次评测',
            at: new Date().toISOString(),
          })
        }
        return
      }
      const status = result.data.status
      if (status === 'pending' || status === 'running') {
        return
      }
      if (handledEvalJobs.current.has(evalJobId)) {
        return
      }
      handledEvalJobs.current.add(evalJobId)
      setEvalJobId(null)
      if (status !== 'completed' || !Array.isArray(result.data.result)) {
        pushLog({
          id: nextLogId(),
          step: 'evaluate',
          status: null,
          detail: `评测失败 job=${evalJobId}：${shortBody(result.data.error ?? status)}`,
          at: new Date().toISOString(),
        })
        return
      }
      const runIds = result.data.result.filter(
        (id): id is string => typeof id === 'string',
      )
      const runs: EvaluationRunWire[] = []
      for (const runId of runIds) {
        const loaded = await apiRequest<EvaluationRunWire>(
          `/api/skills/${skillId}/evaluations/${runId}`,
        )
        if (cancelled) {
          return
        }
        if (loaded.ok) {
          runs.push(loaded.data)
        }
      }
      pushLog({
        id: nextLogId(),
        step: 'evaluate',
        status: null,
        detail: `评测完成 job=${evalJobId} run_ids=${runIds.join(',')}`,
        at: new Date().toISOString(),
      })
      const data = buildBenchmarkFromRuns(runs)
      if (data) {
        setBenchmark(data)
      }
    }
    void tick()
    const id = window.setInterval(() => void tick(), 2000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [evalJobId, skillId])

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
          return `项目 ${p.id}`
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
          detail: '请先创建项目',
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
          detail: '请先选择文件',
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
          detail: '请先创建项目',
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
          (data) => `${(data as KnowledgeResponse[]).length} 条知识单元`,
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
          detail: '请先创建项目',
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
          return `技能=${c.skill_id} 版本=${c.version_id} 状态=${skillStatusLabel(c.status)}`
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
          (data) => `故障 ${(data as { fault_id: string }).fault_id}`,
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
          (data) => {
            const status = (data as { status: string }).status
            return status === 'reset' ? '已复位' : status
          },
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
          detail: '请先编译技能',
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
          return `已接受 job_id=${j.job_id}（等待评测完成）`
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
          detail: '请先编译技能',
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
          detail: `JSON 无效：${err instanceof Error ? err.message : String(err)}`,
          at: new Date().toISOString(),
        })
        return
      }
      if (!evolveForm.run_id.trim()) {
        pushLog({
          id: nextLogId(),
          step: 'evolve',
          status: null,
          detail: '必须填写 run_id',
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
          return `版本=${e.version_id} 状态=${skillStatusLabel(e.status)} 类别=${e.failure_class ?? '—'}`
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
            return `有父版本=${d.has_parent} 行数=${d.diff.split('\n').length}`
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
          detail: '需要 skill_id 和 version_id',
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
            `版本=${(data as { version_id: string }).version_id} 状态=${skillStatusLabel((data as { status: string }).status)}`,
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
          detail: '需要 skill_id 和 version_id',
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
            `状态=${skillStatusLabel((data as { status: string }).status)} 路径=${(data as { published_path: string }).published_path}`,
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
          detail: '请填写 skill_id 和 version_id',
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
          return `有父版本=${d.has_parent} 父版本=${d.parent_version_id ?? '无'}`
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
      ? '在线'
      : apiHealth === 'offline'
        ? '离线'
        : '检查中…'
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
          SkillForge — 现场演示
        </h1>
        <div className="flex flex-wrap items-center gap-2">
          <div
            className="flex items-center gap-2 rounded-md border bg-card px-3 py-1.5 text-sm"
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
        WS <code className="text-foreground">/api/events</code>：
        <span className="text-foreground">{wsStatusLabel(wsStatus)}</span>
        {wsError ? (
          <span className="text-destructive"> — {wsError}</span>
        ) : null}
        {evalJobId ? (
          <span>
            {' '}
            · 评测任务进行中 <code className="text-foreground">{evalJobId}</code>
          </span>
        ) : null}
        {skillId ? (
          <span>
            {' '}
            · 技能 <code className="text-foreground">{skillId}</code>
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
        aria-label="演示操作"
        className="flex flex-col gap-3 rounded-md border bg-card p-3"
      >
        <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
          <div className="flex flex-col gap-2">
            <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              项目
            </label>
            <input
              className="h-8 rounded-md border bg-background px-2 text-sm"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="名称"
            />
            <input
              className="h-8 rounded-md border bg-background px-2 text-sm"
              value={projectDescription}
              onChange={(e) => setProjectDescription(e.target.value)}
              placeholder="描述"
            />
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                disabled={busy !== null}
                onClick={onCreateProject}
              >
                创建项目
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
              上传原文
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
                上传
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={busy !== null}
                onClick={onExtract}
              >
                抽取
              </Button>
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              编译技能
            </label>
            <input
              className="h-8 rounded-md border bg-background px-2 text-sm"
              value={skillName}
              onChange={(e) => setSkillName(e.target.value)}
              placeholder="技能名称"
            />
            <input
              className="h-8 rounded-md border bg-background px-2 text-sm"
              value={skillDescription}
              onChange={(e) => setSkillDescription(e.target.value)}
              placeholder="描述"
            />
            <textarea
              className="min-h-[4.5rem] rounded-md border bg-background px-2 py-1 font-mono text-xs"
              value={triggersText}
              onChange={(e) => setTriggersText(e.target.value)}
              placeholder="触发词（每行一条，需与原文一致）"
            />
            <Button
              type="button"
              size="sm"
              disabled={busy !== null}
              onClick={onCompile}
            >
              编译
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-2 border-t pt-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              故障
            </label>
            <select
              className="h-8 rounded-md border bg-background px-2 text-sm"
              value={faultId}
              onChange={(e) => setFaultId(e.target.value as FaultId)}
            >
              {FAULT_IDS.map((id) => (
                <option key={id} value={id}>
                  {id === 'backend_stopped'
                    ? '后端已停止'
                    : id === 'nginx_wrong_upstream'
                      ? '上游端口错误'
                      : '错误配置导致重载失败'}
                  （{id}）
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
            注入故障
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy !== null}
            onClick={onReset}
          >
            复位实验环境
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={busy !== null}
            onClick={onEvaluate}
          >
            评测
          </Button>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              批准人
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
            批准
          </Button>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={busy !== null}
            onClick={onPublish}
          >
            发布
          </Button>
        </div>

        <div className="grid gap-2 border-t pt-3 lg:grid-cols-2">
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                分析并改进
              </label>
              <Button
                type="button"
                size="xs"
                variant="ghost"
                onClick={onPrefillEvolve}
              >
                从轨迹预填
              </Button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <input
                className="h-8 rounded-md border bg-background px-2 font-mono text-xs"
                value={evolveForm.version}
                onChange={(e) =>
                  setEvolveForm((p) => ({ ...p, version: e.target.value }))
                }
                placeholder="版本号"
              />
              <input
                className="h-8 rounded-md border bg-background px-2 font-mono text-xs"
                value={evolveForm.run_id}
                onChange={(e) =>
                  setEvolveForm((p) => ({ ...p, run_id: e.target.value }))
                }
                placeholder={
                  suggestedRunId
                    ? `run_id（例如 ${suggestedRunId}）`
                    : 'run_id（可编辑）'
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
              aria-label="断言 JSON"
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
              aria-label="校验器 JSON"
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
              aria-label="source_map 更新 JSON"
            />
            <p className="text-xs text-muted-foreground">
              会把旧版本和新版本的全部故障各跑一遍，通常要十几分钟。按钮会一直不可点，结束前不要刷新。
            </p>
            <Button
              type="button"
              size="sm"
              disabled={busy !== null}
              onClick={onEvolve}
            >
              分析并改进
            </Button>
            <div className="mt-2 flex flex-col gap-2 border-t pt-2">
              <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                查找技能差异
              </label>
              <input
                className="h-8 rounded-md border bg-background px-2 font-mono text-xs"
                value={skillId}
                onChange={(e) => setSkillId(e.target.value)}
                placeholder="skill_id"
                aria-label="用于差异的 skill_id"
              />
              <input
                className="h-8 rounded-md border bg-background px-2 font-mono text-xs"
                value={versionId}
                onChange={(e) => setVersionId(e.target.value)}
                placeholder="version_id"
                aria-label="用于差异的 version_id"
              />
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={busy !== null}
                onClick={onLoadDiff}
              >
                加载差异
              </Button>
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              步骤记录
            </h2>
            <ul className="max-h-64 overflow-y-auto rounded-md border font-mono text-xs">
              {stepLog.length === 0 ? (
                <li className="px-3 py-2 text-muted-foreground">
                  还没有接口调用
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
                    <span className="font-sans font-medium">{demoStepLabel(entry.step)}</span>{' '}
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
              <p className="text-xs text-muted-foreground">进行中：{demoStepLabel(busy)}…</p>
            ) : null}
          </div>
        </div>
      </section>

      {/* Four zones — architecture §10.1 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section
          aria-label="原文与知识"
          className="flex flex-col gap-2 rounded-md border bg-card p-3"
        >
          <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
            原文与知识
          </h2>
          <p className="text-xs text-muted-foreground">
            当前项目已上传的操作手册，以及抽取出的知识单元。
          </p>
          {projectId ? (
            <p className="font-mono text-xs text-muted-foreground">
              项目 {projectId}
              {knowledgeCount !== null
                ? ` · ${knowledgeCount} 条知识单元`
                : null}
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">
              先创建项目并上传原文，这里才会有内容。
            </p>
          )}
          <ul className="divide-y rounded-md border bg-card text-sm">
            {sources.length === 0 ? (
              <li className="px-3 py-2 text-muted-foreground">还没有原文</li>
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

        <PipelineStepper events={events} placeholder="empty" />

        <LiveTrace events={events} placeholder="empty" />

        <Benchmark data={benchmark} placeholder="empty" />
      </div>

      <SkillDiff
        data={skillDiff}
        failure={skillDiffFailure}
        placeholder="empty"
      />
    </div>
  )
}
