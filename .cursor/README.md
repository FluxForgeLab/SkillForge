# .cursor — SkillForge 开发 Harness

首轮搭建，粒度刻意偏粗：6 条 rules、4 个 skills。随开发推进再拆细。

## 布局

```text
.cursor/
├── rules/
│   ├── project-core.mdc          [always] 北极星、已拍板决策、非目标
│   ├── workflow-and-commits.mdc  [always] 一个 commit 一个功能点的工作流、验证命令、message 格式
│   ├── safety-boundaries.mdc     [always] 沙箱、Self-Evolution 红线、凭据
│   ├── python-backend.mdc        [globs skillforge/**, tests/**, demo/**/*.py]
│   ├── web-frontend.mdc          [globs apps/web/**]
│   └── skill-artifacts.mdc       [globs skills/**, demo/**]
└── skills/
    ├── implement-plan-step/      按执行方案编号实现一个 commit
    ├── ops-lab/                  启动/注入/复位/验证 demo 环境
    ├── author-skill-md/          手写或审阅 SKILL.md 等产物
    └── run-evaluation/           跑 A/B 评测并解读 uplift
```

`AGENTS.md`（仓库根）是总入口，rules 是分主题的持久约束，skills 是按需加载的操作手册。

## 第二轮再加（不要现在做）

- `hooks.json`：pre-commit 自动跑 ruff/pytest；阻止对 `skills/*/evals/` 的编辑。
- 拆 rule：`runtime.mdc`（agent loop 与 tool 契约）、`evaluator.mdc`、`api.mdc`（路由与错误格式）在对应模块稳定后再抽出。
- skill：`record-model-transcript`（录制真实模型响应为测试 fixture）、`dgx-deploy`（DGX Spark 部署与探测）在 C3.11 / C10.0 之后补。
- 前端组件库约定（shadcn 组件使用清单）在 C9.1 之后补。
