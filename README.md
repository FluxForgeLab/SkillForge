# SkillForge

SkillForge 把企业 Runbook 编译为可执行、可评测、可迭代的 Agent Skill，并通过
Without Skill vs With Skill 的确定性评测证明 Skill 让 Agent 变得更好。

本仓库按 `docs/execution-plan.md` 逐 commit 搭建。设计见
`docs/SkillForge_Architecture_Design_v0.1.md`。

## 状态

Phase 0 — Bootstrap。Python 包、前端脚手架与开发入口已落地。

```bash
just lint
just test
# Windows 无 just 时：
.\scripts\dev.ps1 lint
.\scripts\dev.ps1 test

uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .

pnpm -C apps/web install
pnpm -C apps/web lint
pnpm -C apps/web build
```
