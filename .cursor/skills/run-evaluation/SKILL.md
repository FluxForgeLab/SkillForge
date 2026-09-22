---
name: run-evaluation
description: 对某个 Skill 版本运行 Control vs Treatment 评测、解读 Skill Uplift 与回归结果、定位失败 case 的 trace。当用户要求"跑评测"、"看 uplift"、"为什么这个 case 失败"、"对比 v0.1 和 v0.2"时使用。
---

# Run Evaluation

契约见 `docs/execution-plan.md` §0.5。在线 A/B 走 `run_suite`，不走一条还不存在的 live `skillforge eval`。

## 现在能跑的命令

```bash
uv run skillforge run --task "..." --fault backend_stopped [--skill skills/golden/service-recovery]
uv run skillforge eval --skill <skill_dir> --version-hash <hex> --model <name> --replay
```

`skillforge run` 是单次调试：注入故障、跑 harness、把结果写入 `agent_runs`。它不写 `evaluation_runs`，也不计算 uplift。

`skillforge eval --replay` 只读缓存，键是 `(version_hash, case_id, arm, model)`。缓存齐全时退出码 0，缺记录时退出码 2。它不跑 Agent，不复位，不注入。

在线评测是 `skillforge.evaluator.suite.run_suite`：每个 case、每一轮先 Control（`skill_path=None`）再 Treatment。两臂共用 `runtime_tools()` 和同一份 `Settings`。评测前 ops-lab 必须在运行（见 `ops-lab` skill）。单条试验的顺序是 reset → inject → run → verify → assert，结果写入 `evaluation_runs`。传入 `version_hash` 和 `model` 时，跑完会写入回放缓存。

`skillforge trace`、`skillforge eval --repeats`、`skillforge eval --compare` 都还没有。看某次试验的事件：读该 `run_id` 的 `trace_events`，或 `GET /api/runs/{id}/events`（这条 API 读的是 trace，对应 harness 的 run id）。

## 解读结果

`metrics.passed` 只表示断言：verifier 对上 `expected`，且 trace 里没有 `forbidden`。`forbidden` 命中 `tool_call.name`，或 `policy_violation.output.name`（`restart_database` 走第二条）。重启 `backend` 的 `docker.restart` 不算禁止动作。

`uplift_pp = (treatment 成功率 − control 成功率) × 100`。回归数是 Treatment 成功率低于 Control 的 case 个数。`write_benchmark` 把五项指标和 per-case 矩阵写入版本目录；评测 HTTP 任务不会自动写这两份文件。

```text
Without Skill   1/3  (33%)
With Skill      2/3  (67%)
Uplift          +33 pp
```

- `uplift_pp ≤ 0`：先看 Control 是否已经能独立完成，再看 Treatment 的失败 trace。
- `policy_violations` 是计数。它本身不把 `passed` 改成假；只有落到 `forbidden` 的动作才会让断言失败。
- `tool_error_count` 高：先查工具参数和运行时错误。
- 缓存键不含重复轮次。`repeats` 大于 1 时，同一 case、同一臂只留下最后一轮。现场演示用 `--replay`。

## 定位失败 case

按顺序看三件事：assertion 的 `mismatches` 里哪个 verifier 字段没对上 → 该 `run_id` 最后一次相关 `tool_call` 是什么 → skill 正文里有没有覆盖这一步的指令。分类名用架构文档 §8.12 的 failure class。Failure Analyzer 还没落地。

## 禁止

- 为了让 case 通过而修改 `evals/evals.json` 的 `expected` 或 `forbidden`。已有 `eval_seals` 记录时，这种修改会在评测前被 `EvalGuardError` 拒绝。
- 为了拉大 uplift 削弱 Control 的工具集或预算。两臂必须同工具、同预算、同模型。
