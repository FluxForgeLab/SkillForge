/** User-visible labels. Stored API values stay unchanged. */

const SKILL_STATUS: Record<string, string> = {
  DRAFT: '草稿',
  CANDIDATE: '候选',
  VALIDATED: '已验证',
  APPROVED: '已批准',
  PUBLISHED: '已发布',
  REJECTED: '已拒绝',
}

const KU_TYPE: Record<string, string> = {
  procedure: '步骤',
  diagnostic_rule: '诊断规则',
  constraint: '约束',
  tool_instruction: '工具说明',
  success_criterion: '成功标准',
  failure_pattern: '失败模式',
  dependency: '依赖',
  permission: '权限',
}

const WS_STATUS: Record<string, string> = {
  connecting: '连接中',
  open: '已连接',
  closed: '已断开',
  error: '错误',
}

const DEMO_STEP: Record<string, string> = {
  create: '创建项目',
  upload: '上传',
  extract: '抽取',
  compile: '编译',
  inject: '注入故障',
  reset: '复位',
  evaluate: '评测',
  evolve: '分析改进',
  diff: '差异',
  approve: '批准',
  publish: '发布',
}

export function skillStatusLabel(status: string): string {
  return SKILL_STATUS[status] ?? status
}

export function knowledgeTypeLabel(type: string): string {
  return KU_TYPE[type] ?? type
}

export function wsStatusLabel(status: string): string {
  return WS_STATUS[status] ?? status
}

export function demoStepLabel(step: string): string {
  return DEMO_STEP[step] ?? step
}
