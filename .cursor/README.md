# .cursor — SkillForge 开发 Harness

当前 Harness 分成两层：

- **Agent Control Layer**：rules / domain skills，约束 AI 不越界。
- **Human Control Layer**：align → approve → implement → review → commit，让人类开发者持续掌握 Architecture、Contract 与 State。

当前共 8 条 rules、8 个 skills。

## Human Control Loop

```text
阶段切换 / 认知漂移
        ↓
   align-project
        ↓

   align-plan-step Cx.y
        ↓
     HUMAN GATE
        ↓
 implement-plan-step Cx.y
        ↓
  review-plan-step Cx.y
        ↓
 HUMAN COMMIT GATE
        ↓
      git commit
```

默认不把“做 C6.1”解释成直接写代码：如果当前会话还没有 C6.1 Preflight，先对齐并停在 Human Gate。用户始终可以显式说“跳过对齐 / 直接实现”或“跳过 review / 直接提交”。

## 布局

```text
.cursor/
├── rules/
│   ├── project-core.mdc          [always] 北极星、已拍板决策、非目标
│   ├── human-control-loop.mdc    [always] align / implement / review / commit Gate
│   ├── workflow-and-commits.mdc  [always] commit 粒度、验证命令、提交授权
│   ├── safety-boundaries.mdc     [always] 沙箱、Self-Evolution 红线、凭据
│   ├── measure-before-story.mdc  [always] 排障先测量端点
│   ├── python-backend.mdc        [globs skillforge/**, tests/**, demo/**/*.py]
│   ├── web-frontend.mdc          [globs apps/web/**]
│   └── skill-artifacts.mdc       [globs skills/**, demo/**]
└── skills/
    ├── align-project/             只读重建当前系统 Mental Model
    ├── align-plan-step/           C 编号实现前 Preflight
    ├── implement-plan-step/       Human Gate 后按批准范围实现
    ├── review-plan-step/          提交前 Architecture Delta Review
    ├── ops-lab/                   启动/注入/复位/验证 demo 环境
    ├── diagnose-listen/           测量 LISTEN 元组后解释连通性
    ├── author-skill-md/           手写或审阅 SKILL.md 产物
    └── run-evaluation/            跑 A/B 评测并解读 uplift
```

`AGENTS.md` 是总入口；rules 是持久约束；skills 是按需操作手册。

## Human Attention Map

每次 align / review 都按当前变更分类：

- **RED**：Domain Contract、状态机、Agent loop、Tool/Sandbox 权限边界、Evaluator、Compiler/Evolution 核心决策。
- **YELLOW**：Adapter、Repository、API glue、Tracing、Ingestion。
- **GREEN**：boilerplate、机械 CRUD / mapping、样式等。

这不是永久模块标签，而是告诉人类“这次 diff 应该把认知预算花在哪里”。

## 第二轮再加（按需求，不提前膨胀）

- `hooks.json`：pre-commit 自动跑 ruff/pytest；阻止对 `skills/*/evals/` 的编辑。
- 拆 rule：`runtime.mdc`、`evaluator.mdc`、`api.mdc`，在对应模块稳定后再抽出。
- skill：`record-model-transcript`（C3.11 之后）与 `dgx-deploy`（C10.0 之后）。
- 前端组件库约定在 C9.1 之后补。
- `add-retrieval-backend` 在 Phase 12 开始前补。
