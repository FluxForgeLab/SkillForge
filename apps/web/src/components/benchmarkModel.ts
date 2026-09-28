/**
 * Benchmark wire shape aligned with skillforge.evaluator.benchmark payload
 * (task_success_rate, skill_uplift_pp, per-case control/treatment rates).
 * C9.3 renders from mock; API wiring is later (C9.5+).
 */

export type BenchmarkCaseRow = {
  case_id: string
  name: string
  /** True when control arm passed this case (rate >= 1 for single-trial mock). */
  control_passed: boolean
  treatment_passed: boolean
  control_success_rate: number
  treatment_success_rate: number
  uplift_pp: number
}

export type BenchmarkData = {
  task_success_rate: {
    control: number
    treatment: number
  }
  skill_uplift_pp: number
  cases: BenchmarkCaseRow[]
}

/**
 * Deterministic sample so Benchmark is visible with the API offline.
 * Mirrors golden service-recovery story: F1 pass both, F2 control fail /
 * treatment pass, F3 fail both (v0.1 gap).
 */
export const MOCK_BENCHMARK: BenchmarkData = {
  task_success_rate: {
    control: 1 / 3,
    treatment: 2 / 3,
  },
  skill_uplift_pp: (2 / 3 - 1 / 3) * 100,
  cases: [
    {
      case_id: 'eval_backend_stopped',
      name: 'backend process stopped',
      control_passed: true,
      treatment_passed: true,
      control_success_rate: 1,
      treatment_success_rate: 1,
      uplift_pp: 0,
    },
    {
      case_id: 'eval_nginx_wrong_upstream',
      name: 'nginx wrong upstream',
      control_passed: false,
      treatment_passed: true,
      control_success_rate: 0,
      treatment_success_rate: 1,
      uplift_pp: 100,
    },
    {
      case_id: 'eval_nginx_bad_config_reload',
      name: 'nginx bad config reload',
      control_passed: false,
      treatment_passed: false,
      control_success_rate: 0,
      treatment_success_rate: 0,
      uplift_pp: 0,
    },
  ],
}

export function formatSuccessPct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`
}

export function formatUpliftPp(pp: number): string {
  const sign = pp > 0 ? '+' : ''
  return `${sign}${pp.toFixed(1)} pp`
}
