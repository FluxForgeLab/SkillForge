---
name: run-evaluation
description: 对某个 Skill 版本运行 Control vs Treatment 评测、解读 Skill Uplift 与回归结果、定位失败 case 的 trace。当用户要求"跑评测"、"看 uplift"、"为什么这个 case 失败"、"对比 v0.1 和 v0.2"时使用。
---

# Run Evaluation

## 命令（C3.8 / C4.x 之后可用）

```bash
uv run skillforge run --task "..." --fault backend_stopped [--skill skills/golden/service-recovery]  # 单次手动运行
uv run skillforge eval --skill <skill_dir> --repeats 1 [--cases eval_backend_stopped] [--replay]    # A/B 评测
uv run skillforge eval --compare <version_a> <version_b>                                          # 回归对比
```

评测前 ops-lab 必须在运行（见 `ops-lab` skill）。评测会对每个 case 执行 reset → inject → run → verify → assert。

## 解读结果

报告核心是三行，其他指标是辅助：

```text
Without Skill   1/3  (33%)
With Skill      2/3  (67%)
Uplift          +33 pp
```

- `uplift_pp ≤ 0`：先看 Control 是否"过强"（模型不需要 skill 也能解），再看 Treatment 的失败 trace，不要先改 prompt。
- `policy_violations > 0`：无论成功与否都视为失败，找到触发的 tool_call 并检查 skill 指令是否诱导了它。
- `tool_error_count` 高：多为工具参数格式问题，属于 runtime bug 而非 skill 缺陷。
- 非确定性：`repeats ≥ 3` 才能下结论；demo 演示用 `--replay` 读缓存。

## 定位失败 case

```bash
uv run skillforge trace <run_id>            # 按时间打印 tool_call / tool_result / assertion / policy_violation
```

按顺序问三个问题：verifier 哪个字段没达到期望 → agent 最后一次相关 tool_call 是什么 → skill 中是否有指令覆盖这一步。答案落到 §8.12 的 failure class 之一，这也是 FailureAnalyzer 应给出的分类；人工判断与其不一致时优先修 FailureAnalyzer 的 prompt 或规则。

## 禁止

- 为了让 case 通过而修改 `evals/evals.json` 的 `expected`/`forbidden`。
- 为了提高 Control 失败率而削弱 Control arm 的工具集或预算；两臂必须同工具、同预算、同模型。
