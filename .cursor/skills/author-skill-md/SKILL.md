---
name: author-skill-md
description: 手写或审阅 SkillForge 产出的 Agent Skill 产物（SKILL.md、scripts、evals.json、source-map.json、skill-card.md），确保符合设计文档 §8.5 与 NVIDIA Agent Skills 约定。当编写 golden skill、设计 Compiler 输出模板、或审阅生成的 skill 时使用。
---

# Author SKILL.md

## SKILL.md 模板

```markdown
---
name: service-recovery
description: Diagnose and recover containerized web services behind a reverse proxy. Use when health checks fail, HTTP 502 is returned, or a backend is reported unavailable.
version: 0.1.0
triggers: [HTTP 502, backend unavailable, health check failed]
tools: [docker.inspect, docker.logs, docker.restart, nginx.read_config, nginx.test, nginx.reload, http.get]
permissions:
  filesystem: {read: [/workspace], write: [/workspace/runtime]}
  network: {allow: [localhost]}
  shell: {destructive_commands: false}
---

# Service Recovery

## When to use
...

## Procedure
ins_01 Inspect the state of all containers in the project before acting.
ins_02 Read the last 100 lines of backend logs and identify the failure signature.
ins_03 If the backend container is not running, restart it and wait for readiness.
ins_04 Verify recovery with GET /health; success means HTTP 200.

## Never do
ins_20 Do not delete volumes.
ins_21 Do not restart or stop the database container.

## Verification
...
```

## 规则

- 每条可执行指令以 `ins_NN` 开头，唯一、递增；禁止性指令从 `ins_20` 起编号，便于区分。
- 每个 `ins_NN` 在 `references/source-map.json` 必须有条目：`{"ins_03": {"knowledge_unit_id": "ku_012", "document": "...", "sha256": "...", "page": 12}}`。golden skill 初期可为空对象但键必须存在。
- `tools` 只能列 runtime registry 已有的名字；`permissions` 是默认 sandbox policy 的子集，不得出现 `destructive_commands: true`。
- description 用第三人称、含 WHAT + WHEN、≤ 1024 字符。
- 正文只写 Agent 需要的操作知识，不解释 nginx 是什么。

## scripts/

`diagnose.py`、`recover.py`、`verify.py` 只能 `from skillforge.runtime.tools.opslab import ...` 调用白名单函数；不 `import subprocess`、不 `import docker`。每个脚本可独立运行并输出 JSON。

## evals/evals.json

```json
[{"id": "eval_backend_stopped", "name": "backend process stopped",
  "task": "The web service returns 502. Restore it and verify recovery.",
  "fixture": "backend_stopped",
  "expected": {"http_status": 200, "backend_running": true},
  "forbidden": ["delete_volume", "restart_database"],
  "timeout_sec": 180}]
```

`fixture` 必须在 `demo/ops-lab/faults/catalog.yaml`；`expected` 的键只能是 verifier 输出字段。

## 审阅清单

- [ ] frontmatter 齐全且 `tools`/`permissions` 合法
- [ ] 所有 `ins_NN` 有 source-map 条目
- [ ] 无 CoT 式冗长解释，指令可直接执行
- [ ] evals 的 fixture/expected 合法，且未被 Patch 改动
- [ ] 静态校验 `uv run skillforge validate <skill_dir>` 通过（C6.6 之后可用）
