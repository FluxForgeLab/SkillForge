# SkillForge 执行方案 v0.1

> 依据：`docs/SkillForge_Architecture_Design_v0.1.md`（下称"架构文档"）
> 粒度：一个功能点 = 一个 commit。每个 commit 有明确的完成标准（DoD），可独立验证。
> 顺序：遵循架构文档 §32 的实现顺序（Ops Lab → Verifier → Runtime → Compiler → Evaluator → Evolution → Frontend），而不是 §25 按天的顺序。原因见 §0.2。

---

## 0. 架构审阅结论与本计划的调整

架构文档整体成立：核心创新点（Knowledge → Skill → Evaluation → Evolution 闭环）清晰，非目标和 Cut Line 明确，Evidence First / Evaluation Before Evolution 两条原则是正确的护栏。以下是审阅中发现的、会直接影响实施的问题，以及本计划采取的调整。

### 0.1 需要在实施前拍板的问题

| # | 问题 | 影响 | 本计划的处理 |
|---|---|---|---|
| R1 | **模型内存预算过紧。** Step 3.7 Flash GGUF Q4_K_S ≈ 111.5 GB，DGX Spark 统一内存 128 GB，还要留 KV cache、OS、Docker、API、前端。 | 现场可能 OOM 或吞吐极低（demo 单次 agent run 可能要数分钟）。 | Day 1 在 DGX 上做 spike 测实际 tokens/s 与常驻内存；`ModelGateway` 从第一天起就是 OpenAI-compatible，本地开发用云端 API；准备 `StepFunAPIAdapter` 做 fallback；Judge Mode 提供"预计算 Benchmark + 现场单次 live run"的 replay 模式（C8.4）。 |
| R2 | **Agent Loop 本身没有定义。** 架构文档提到 `LocalHarnessAdapter / OpenCodeAdapter`，但 "Without Skill" 基线到底是什么 agent、用什么工具集、多少步预算，没有说明。这是隐藏的最大工程量。 | A/B 对比的公平性和可解释性全靠它。 | 明确 Control 与 Treatment 使用**同一模型、同一工具集、同一步数/时间预算**，唯一差异是 system prompt 中是否注入 SKILL.md。自研一个最小 ReAct tool-calling loop（C3.6），不引入 agent framework。 |
| R3 | **Docker 操作与 "禁止模型接触 docker.sock" 冲突。** Agent 要重启 ops-lab 容器、reload nginx，但 §21 禁止 docker.sock 进沙箱。 | 不解决就会在 Day 4 卡住。 | 拆成两个执行面：(a) `Sandbox` 只跑生成的脚本与只读 shell；(b) `OpsLabToolAdapter` 运行在控制面，以白名单方式暴露 `docker.inspect / docker.logs / docker.restart / nginx.test / nginx.reload / nginx.read_config / nginx.write_config`，只允许作用于 ops-lab compose project 内的容器。（C3.4、C3.5） |
| R4 | **两套状态机混在一起。** §5.3 是 pipeline 状态（INGESTED→…→PUBLISHED），§9 是 SkillVersion 状态（DRAFT/CANDIDATE/…）。 | 实现时容易混淆。 | 分开：`PipelineRun.state` 与 `SkillVersion.status` 是两个枚举、两个状态机（C2.2、C8.1）。 |
| R5 | **Fault 3 "Unknown Failure" 与 Runbook 的关系未设计。** §15.3 的 patch 加的是 "verify upstream"，但 §15.2 Fault 2 已经是 upstream mismatch。若 v0.1 已能处理 F2，则 F3 演示不成立。且 v0.1 "必然失败" 不能靠模型随机性。 | 这是整个 demo 最关键 30 秒，必须可复现。 | 重新设计 fault 与 runbook 的对应关系（见 §0.3）。核心思路：**知识在文档里但没被编译进 v0.1**（Appendix 段落触发词不匹配），Failure Analyzer 通过检索门面（MVP 为 FTS5 关键词）找回证据 → 生成 patch。这是一个诚实且确定性的故事。 |
| R6 | **非确定性与评测成本。** 3 cases × 2 arms × N 次重复，本地大模型每次数分钟。 | 现场无法实时跑完整 benchmark。 | Evaluator 支持 `repeats` 参数与结果缓存；demo 前预跑，现场只 live 跑一条（R1 同一处理）。temperature 固定，记录 seed。 |
| R7 | **前端 8 个页面超出 Day 7 一天的容量。** | 分散注意力。 | P0 只做 Judge Mode + Live Trace + Benchmark + Diff；Skill Studio / Evaluation Lab / Timeline 做 lite 版；Dashboard、Knowledge Lab 放 P1。 |
| R8 | **仓库结构 Python 打包不便。** `services/api`、`skillforge/`、`adapters/` 三个顶层目录，需要多 pyproject 或 path hack。 | 浪费时间在 plumbing。 | 合并为**单一 Python 包 `skillforge/`**，`api/`、`models/`、`sandbox/` 都在包内；单一 `pyproject.toml`（uv）。见 §1。 |
| R9 | **NVIDIA SkillEvaluator / OpenShell 可用性未知。** | 不能成为核心路径依赖。 | 都做成 adapter + mock，P1；Demo 主路径不依赖（C10.4、C10.6）。 |
| R10 | **DGX Spark 是 aarch64（Grace CPU）。** 架构文档没提。 | Docker 镜像必须 multi-arch；本地 Windows 开发是 x86_64。 | ops-lab 只用官方 multi-arch 基础镜像（`nginx:alpine`、`python:3.12-slim`）；不引入 x86-only 二进制。 |
| R11 | **`docs/` 内含登录信息表（xlsx）与硬件手册（docx）。** | 一旦进 git 就是凭据泄露。 | 建仓第一个 commit 的 `.gitignore` 排除 `docs/*.xlsx`、`docs/*.docx`，并在 AGENTS.md 明确禁止提交。 |
| R12 | **检索存储：MVP 用 SQLite FTS5，优化阶段换 LanceDB。** 若 FTS 表进了核心 schema、业务层直接写 `MATCH`、评分语义暴露给调用方、或没有跨后端契约测试，"换后端"就会变成重构。 | 优化阶段可能被迫重写 Compiler / Evolution 的检索调用与数据迁移。 | 设计见 **`docs/retrieval-layer.md`**（已拍板）。要点：(1) **索引是投影**——SQLite 永远是 system of record，`chunks`/`knowledge_units` 是普通表，`schema.sql` 不含 FTS；后端自建 `idx_*` 表或 `data/index/<backend>/`，可随时 `rebuild`。(2) **端口固定**——`RetrievalIndex{ensure_schema,upsert,delete,search}` + `IndexDocument/RetrievalQuery/RetrievalHit`，`score` 归一化 [0,1]，`mode` 请求 `keyword|vector|hybrid` 不支持即降级并回报 `mode_used`；`vector` 字段 MVP 恒为 None。(3) **调用方只 import `Retriever` 门面**，ruff banned-api 锁死 `lancedb`/`sqlite3` 的导入边界。(4) **契约测试** parametrize 全部后端，LanceDB 加入的验收 = 契约全绿 + 召回评测 ≥ FTS5。(5) `Embedder` 端口 MVP 只有 `NullEmbedder`。MVP 不安装 `lancedb`，不加载 embedding 模型。切换在 Phase 12（DoD 之后），不改 schema、不迁数据、不改调用方。 |

### 0.2 为什么不按 §25 的 Day 顺序

§25 把 Knowledge（Day 2）和 Compiler（Day 3）放在 Runtime（Day 4）和 Evaluator（Day 5）之前。这意味着到 Day 5 才能第一次验证"Skill 到底有没有用"。§32 自己也说了应该先做 Ops Lab → Verifier → Runtime。

本计划的关键手法：**Day 2 先手写一个 golden `service-recovery` Skill**（C3.1）。有了它，Runtime、Sandbox、Evaluator 全部可以在 Compiler 存在之前完成并验证；Compiler 的验收标准也随之变成"生成物通过与 golden 相同的静态校验，并在评测中达到相近 uplift"。这把最大的不确定性（LLM 生成质量）从关键路径上摘下来。

### 0.3 Demo 故障集与 Runbook 的确定性设计

| Fault | 注入方式 | Runbook 覆盖 | v0.1 预期 | v0.2 预期 |
|---|---|---|---|---|
| F1 `backend_stopped` | `docker stop backend` | 主章节 "Service Down" | ✅ | ✅ |
| F2 `nginx_wrong_upstream` | nginx.conf upstream 改为 `backend:8081` | 主章节 "502 from proxy" 提到"检查 upstream"（不提端口对比与 `nginx -t`） | ✅（模型大概率能猜到）— 用作稳定案例 | ✅ |
| F3 `nginx_bad_config_reload` | 注入一个 nginx 配置语法错误 + upstream 指向 `backend:8081`，reload 会失败 | **仅** Appendix B "Reverse Proxy Troubleshooting"：必须先 `nginx -t`，且对比 upstream 端口与 backend 实际监听端口 | ❌（v0.1 编译时 Appendix B 的 trigger 不匹配 "service recovery" scope，未被纳入） | ✅ |

Control（无 Skill）预期：F1 ✅ / F2 ❌或不稳定 / F3 ❌ → 1/3；v0.1 → 2/3；v0.2 → 3/3。与架构文档 §16 的数字一致。

Runbook 的写法要保证：Appendix B 在 Knowledge Extractor 中被抽为独立的 `diagnostic_rule` 类型 KU，`trigger` 是 "nginx reload failed / upstream mismatch"；Compiler pass 2 按 SkillSpec triggers 筛 KU 时不会选中它；Failure Analyzer 通过 `Retriever` 门面用 `"502 upstream nginx -t"` 检索时能召回它（这一条同时是检索层契约测试的固定用例，任何后端都必须通过）。这三点各有一个测试锁定（C5.9、C6.9、C7.8）。

---

## 1. 目标仓库结构（对架构文档 §17 的简化）

```text
SkillForge/
├── AGENTS.md
├── README.md
├── .cursor/                     # 开发 harness（rules / skills）
├── .gitignore  .editorconfig  .env.example
├── pyproject.toml               # 单一 Python 项目（uv + ruff + pytest）
├── docker-compose.yml           # 全栈：api + web (+ llama.cpp profile)
├── justfile                     # 统一开发命令（或 scripts/dev.ps1）
│
├── skillforge/                  # 唯一的 Python 包
│   ├── config.py                # pydantic-settings
│   ├── domain/                  # pydantic 领域模型 + 状态机枚举
│   ├── db/                      # schema.sql（普通表，不含 FTS）、connection、repositories
│   ├── tracing/                 # TraceEvent、EventBus、sqlite sink
│   ├── models/                  # ModelGateway + adapters (openai_compatible / stepfun_local / stepfun_api / fake)
│   ├── ingestion/               # 上传、解析、chunk
│   ├── knowledge/               # KnowledgeExtractor
│   │   └── retrieval/           # 检索端口（见 docs/retrieval-layer.md）
│   │       ├── base.py          #   RetrievalIndex / IndexDocument / RetrievalQuery / RetrievalHit
│   │       ├── embedder.py      #   Embedder 端口 + NullEmbedder
│   │       ├── retriever.py     #   门面：业务层唯一入口
│   │       ├── indexer.py       #   SQLite → 索引 的投影与 rebuild
│   │       ├── factory.py       #   按 Settings 选后端
│   │       └── backends/        #   sqlite_fts.py (MVP) / memory.py (测试) / lancedb.py (Phase 12)
│   ├── compiler/                # SkillSpec + 8 passes
│   ├── sandbox/                 # Sandbox 接口 + DockerSandbox (+ OpenShell)
│   ├── runtime/                 # AgentRuntime、tools、OpsLabToolAdapter、skill loader
│   ├── evaluator/               # EvalCase、assertions、A/B runner、benchmark (+ nvidia adapter)
│   ├── evolution/               # FailureAnalyzer、Patcher、Gate
│   ├── registry/                # SkillVersion 存储与状态转移
│   ├── orchestrator/            # Pipeline 状态机、job runner
│   ├── api/                     # FastAPI app + routers + ws
│   └── cli.py                   # `skillforge run|eval|demo`
│
├── apps/web/                    # React + TS + Vite + Tailwind + shadcn
├── demo/
│   ├── ops-lab/                 # compose、backend、nginx、faults、verifier
│   └── docs/                    # demo 用 runbook（md + pdf）
├── skills/
│   ├── golden/service-recovery/ # 手写参考 Skill（进 git）
│   ├── generated/               # 编译产物（gitignore）
│   └── published/               # 发布产物（gitignore）
├── data/                        # sqlite、sources、index（gitignore，保留 .gitkeep）
├── tests/
│   ├── unit/
│   ├── integration/             # 需要 Docker，pytest -m integration
│   └── fixtures/
└── docs/
```

---

## 2. Commit 约定

- 格式：Conventional Commits，`<type>(<scope>): <summary>`，type ∈ `feat|fix|test|docs|chore|refactor|spike`；scope 使用下表中的模块名。
- 一个 commit 只做一个功能点；实现 + 该功能点的测试 + 必要的文档更新在同一 commit。
- commit message body 第一行引用本计划编号，如 `Plan: C3.5`。
- 每个 commit 提交前：`uv run ruff check . && uv run ruff format --check . && uv run pytest -m "not integration"` 必须通过；涉及前端时 `pnpm -C apps/web lint && pnpm -C apps/web build` 必须通过。
- 主干开发（trunk-based）。多人并行时用短生命周期分支，当天合回 `main`。
- 标记：**[P0]** 必须，**[P1]** 尽量，**[P2]** 决赛。未标记默认 P0。**[opt]** 可跳过。

---

## 3. Commit 清单

### Phase 0 — Bootstrap（Day 1 上午）

| # | Commit | 内容 | 完成标准 |
|---|---|---|---|
| C0.1 | `chore: init repo, gitignore, editorconfig` | `git init`；`.gitignore` 排除 `data/`、`skills/generated/`、`skills/published/`、`.env`、`docs/*.xlsx`、`docs/*.docx`、`node_modules/`、`.venv/`、`__pycache__/`；`.editorconfig`；README 占位 | `git status` 干净且 xlsx/docx 不在追踪列表 |
| C0.2 | `chore(harness): add AGENTS.md and .cursor rules/skills` | 本次产出的 harness 文件 | Cursor 能加载规则；AGENTS.md 中命令与本计划一致 |
| C0.3 | `chore(py): pyproject with uv, ruff, pytest; package skeleton; settings` | `pyproject.toml`（fastapi、uvicorn、pydantic、pydantic-settings、httpx、docker、pypdf、pyyaml、python-multipart、websockets；dev: pytest、pytest-asyncio、ruff）；`skillforge/__init__.py`、`config.py`；`.env.example`；pytest markers `integration` | `uv sync && uv run pytest` 通过（含一个 smoke test） |
| C0.4 | `chore(web): scaffold vite react ts tailwind shadcn` | `apps/web`，pnpm，一个 Hello 页面，`lint`/`build` 脚本 | `pnpm -C apps/web build` 通过 |
| C0.5 | `chore(dev): justfile with api/web/lab/test commands` | `just api`、`just web`、`just lab-up/down/reset`、`just test`、`just lint`（Windows 下同时提供 `scripts/dev.ps1`） | 每条命令可运行 |
| C0.6 | `chore(ci): lint + unit test workflow` **[opt]** | GitHub Actions | PR 上跑 |

### Phase 1 — Demo Ops Lab（Day 1）

| # | Commit | 内容 | 完成标准 |
|---|---|---|---|
| C1.1 | `feat(ops-lab): backend service with /health and Dockerfile` | `demo/ops-lab/backend/`：FastAPI，`/health`、`/api/items`，端口由 `PORT` env 控制（默认 8080），`HEALTH_PATH` env 可改；multi-arch 基础镜像 | `docker build` 成功；容器内 `curl :8080/health` 200 |
| C1.2 | `feat(ops-lab): nginx proxy, mock-db and compose topology` | `nginx/nginx.conf.tpl`（upstream 端口模板化）、`docker-compose.yml`（nginx:80→backend:8080、mock-db）、compose project name 固定为 `skillforge-lab` | `docker compose up -d` 后 `curl localhost:8088/health` 200 |
| C1.3 | `feat(ops-lab): deterministic verifier` | `verifier/verify.py` 输出 JSON：`http_status`、`backend_running`、`nginx_config_valid`、`upstream_port_matches`、`db_running`；exit code 0/1 | 健康态输出全 true，exit 0 |
| C1.4 | `feat(ops-lab): fault F1 backend_stopped inject/reset` | `faults/inject.py backend_stopped`、`faults/reset.py` | 注入后 verifier `http_status=502, backend_running=false`；reset 后恢复 |
| C1.5 | `feat(ops-lab): fault F2 nginx_wrong_upstream inject/reset` | 渲染 nginx.conf 使 upstream=`backend:8081` 并 reload | 注入后 502，`upstream_port_matches=false` |
| C1.6 | `feat(ops-lab): fault F3 nginx_bad_config_reload inject/reset` | 注入语法错误 + 错误 upstream；`reset-all` | 注入后 `nginx_config_valid=false`；直接 reload 失败 |
| C1.7 | `feat(ops-lab): fault catalog and incident_context generator` | `faults/catalog.yaml`（id、描述、fixture 名、预期 verifier 结果）；`faults/incident.py <fault>` 输出模拟告警 JSON | catalog 被 inject/reset/evaluator 共用 |
| C1.8 | `test(ops-lab): integration test inject→verify→reset for all faults` | `tests/integration/test_ops_lab.py` | `pytest -m integration` 通过 |

### Phase 2 — Core Foundations（Day 1 下午 – Day 2 上午）

| # | Commit | 内容 | 完成标准 |
|---|---|---|---|
| C2.1 | `feat(db): sqlite schema and connection` | `db/schema.sql`：§9 全部表 + `chunks`（普通表：`id, document_id, project_id, ordinal, text, title, page, line_start, line_end`）+ 普通索引。**不含任何 FTS5 虚拟表 / trigger**（R12：索引是后端自建的投影，见 `docs/retrieval-layer.md` §7）；`db/connection.py`（WAL、外键）；`db/init.py` 幂等建表 | 空库初始化两次无报错；`schema.sql` 中 grep 不到 `fts5` |
| C2.2 | `feat(domain): pydantic models and state machine enums` | `domain/`：Project、SourceDocument、Chunk、KnowledgeUnit、SkillSpec（占位）、Skill、SkillVersion、EvalCase、EvaluationRun、TraceEvent、Failure、PatchProposal；`SkillVersionStatus`、`PipelineState` 两个枚举 + 合法转移表 | 非法转移抛异常的单测 |
| C2.3 | `feat(tracing): TraceEvent emitter, in-process bus, sqlite sink` | `tracing/`：`emit(run_id, type, name, input, output, duration_ms)`；async pub/sub；写库 | 单测：emit → 订阅者收到 → 库中可查 |
| C2.4 | `feat(api): FastAPI app factory, health, ws /api/events` | `api/main.py`、`api/deps.py`、CORS、统一错误结构、`WS /api/events` 订阅 bus | `uvicorn` 起来；ws 客户端能收到 emit 的事件 |
| C2.5 | `feat(models): ModelGateway with OpenAICompatible and Fake adapters` | `models/gateway.py`（`ModelRequest/Response`，含 tool-calling 字段、usage）；`openai_compatible.py`（httpx，base_url/api_key 来自 settings）；`fake.py`（按脚本回放响应，供测试）；每次调用 emit `model_request/model_response` | 单测用 Fake；手工用云端 API 跑通一次 |
| C2.6 | `feat(models): structured output helper with schema retry` | `models/structured.py`：给定 pydantic schema → prompt 附加 JSON schema → 解析 → 失败重试 N 次并携带错误 | 单测覆盖坏 JSON 重试 |
| C2.7 | `feat(registry): skill artifact store and version transitions` | `registry/`：`skills/generated/<skill>/<version>/` 落盘；`manifest.json` + sha256；SkillVersion CRUD；状态转移走 C2.2 的合法表；父子版本链 | 单测：创建 v0.1→v0.2，parent 正确，非法 publish 被拒 |
| C2.8 | `feat(api): projects endpoints` | `POST/GET /api/projects` | API 测试通过 |

### Phase 3 — Golden Skill + Sandbox + Runtime（Day 2 – Day 3）

| # | Commit | 内容 | 完成标准 |
|---|---|---|---|
| C3.1 | `feat(skills): hand-authored golden service-recovery skill` | `skills/golden/service-recovery/`：`SKILL.md`（frontmatter + 带 `ins_xx` 编号的指令）、`skill-card.md`、`scripts/diagnose.py|recover.py|verify.py`、`references/source-map.json`（先留空引用）、`evals/evals.json`（F1/F2/F3 三个 case，格式按 §8.10）| 结构与 NVIDIA Agent Skills 约定一致；这是 Compiler 的验收参照 |
| C3.2 | `feat(sandbox): Sandbox interface and policy model` | `sandbox/base.py`（§8.8 接口）；`SandboxPolicy` pydantic（network/filesystem/process/dangerous_operations）；`policies/default.yaml` | 单测加载默认策略 |
| C3.3 | `feat(sandbox): DockerSandbox implementation` | 基于 docker SDK：从 `skillforge-sandbox` 镜像创建容器、只挂载 workspace、`network_mode` 受限、不挂 docker.sock、`exec` 超时、`destroy` 必执行；emit `sandbox_created` | 集成测试：exec `echo`、写读文件、`sudo` 被拒 |
| C3.4 | `feat(runtime): tool registry and in-sandbox tools` | `runtime/tools/base.py`（`ToolSpec`、权限声明）；`shell.read`（只读命令白名单）、`file.read`、`file.write`（限 policy 写路径）、`http.get`（限 allow 列表）；每次调用 emit `tool_call/tool_result` | 单测：越权路径被拒并记 `policy_violation` |
| C3.5 | `feat(runtime): OpsLab control-plane tool adapter` | `runtime/tools/opslab.py`：`docker.inspect/logs/restart`、`nginx.read_config/write_config/test/reload`；只允许 `skillforge-lab` project 内容器；deny：volume 删除、`database` 容器重启、任何 `rm`；违规 emit `policy_violation` | 集成测试：restart backend 成功；restart mock-db 被拒 |
| C3.6 | `feat(runtime): AgentRuntime interface and LocalHarness ReAct loop` | `runtime/agent.py`：`run(task, skill_path, workspace) -> RunResult`；tool-calling 循环；`max_steps`、`max_seconds`、`temperature` 来自 settings；结束条件：模型声明完成或预算耗尽；RunResult 含 steps、tool_errors、tokens、latency、policy_violations | 单测用 FakeModel 跑完整循环 |
| C3.7 | `feat(runtime): skill loader injects SKILL.md into system prompt` | 解析 frontmatter、正文、references；`skill_path=None` 时为 Control arm 的裸 prompt（同一工具集） | 单测：两种 prompt 仅差 skill 段 |
| C3.8 | `feat(cli): skillforge run command` | `skillforge run --task "..." [--skill path] --fault F1` 手工调试入口 | 命令能打印 trace 与 RunResult |
| C3.9 | `test(runtime): F1 recovered end-to-end with scripted model` | FakeModel 按 golden skill 脚本调用 `docker.inspect→docker.logs→docker.restart→http.get` | 集成测试：verifier 全 true |
| C3.10 | `feat(api): demo fault inject/reset and runs endpoints` | `POST /api/demo/faults/:id/inject`、`POST /api/demo/reset`、`GET /api/runs/:id`、`GET /api/runs/:id/events` | API 测试 |
| C3.11 | `spike(runtime): real model recovers F1 with golden skill` | 用真实 OpenAI-compatible 端点跑 `skillforge run`，记录 tokens/步数；把 transcript 存 `tests/fixtures/transcripts/` | 至少 1 次成功；产出调参结论写入 commit body |

### Phase 4 — Evaluator（Day 3 – Day 4）

| # | Commit | 内容 | 完成标准 |
|---|---|---|---|
| C4.1 | `feat(evaluator): EvalCase schema, loader and fixture mapping` | 读取 `evals/evals.json`；`fixture` 映射到 `faults/catalog.yaml` | 单测：golden evals 加载 |
| C4.2 | `feat(evaluator): deterministic assertions` | `expected` 对比 verifier 输出；`forbidden` 检查 trace 中 tool_call（`delete_volume`、`restart_database` 等）；输出 `assertion` 事件 | 单测覆盖通过/失败/禁止动作 |
| C4.3 | `feat(evaluator): single case runner` | reset → inject → run agent → verify → assert → 落 EvaluationRun；timeout 处理；失败也要 destroy sandbox | 集成测试 F1 with golden |
| C4.4 | `feat(evaluator): A/B suite runner with uplift` | Control + Treatment，`repeats` 参数，聚合 `success_rate`、`uplift_pp`、`avg_latency`、`tool_error_count`、`policy_violations`；`baseline=true/false` 标记 | 单测聚合逻辑；集成 1 case × 2 arms |
| C4.5 | `feat(evaluator): evals read-only guard` | CANDIDATE 时记录 `evals.json` sha256；评测前校验；Patcher 产物若改动 evals 直接 reject（防 reward hacking，§22） | 单测：篡改后被拒 |
| C4.6 | `feat(api): evaluate endpoint as background job` | `POST /api/skills/:id/evaluate` 返回 job_id；job 进度走 bus；结果 `GET /api/skills/:id/evaluations/:run_id` | API 测试 |
| C4.7 | `feat(evaluator): BENCHMARK.md and benchmark.json writer` | 写入版本目录；含 5 个关键指标（§23）与 per-case 矩阵 | 文件生成快照测试 |
| C4.8 | `feat(evaluator): result cache and replay` | 按 (version_hash, case, arm, model) 缓存；`--replay` 直接读缓存 | 单测 |

### Phase 5 — Knowledge Plane（Day 4 – Day 5 上午）

| # | Commit | 内容 | 完成标准 |
|---|---|---|---|
| C5.1 | `feat(ingestion): upload storage and markdown/txt parser` | `data/sources/<project>/<sha>/`；SourceDocument 记录（sha256、version 递增）；md/txt 解析保留行号 | 单测 |
| C5.2 | `feat(ingestion): pdf and yaml/json/openapi parsers` | pypdf 页级文本；yaml/json 直读；OpenAPI 每个 operation 成一段 | 单测用 fixtures |
| C5.3 | `feat(ingestion): chunking with source locations` | 标题感知切块；每块记 `page/line_start/line_end`；写 `chunks` 表（只写 SQLite，不碰索引；索引由 C5.4 的 Indexer 负责） | 单测：行号可回溯 |
| C5.4 | `feat(knowledge): retrieval port, in-memory backend, indexer and contract tests` | `knowledge/retrieval/base.py`（`RetrievalIndex` Protocol、`IndexDocument/RetrievalQuery/RetrievalHit`，字段按 `docs/retrieval-layer.md` §3）；`embedder.py`（`Embedder` + `NullEmbedder`）；`backends/memory.py`（测试用，纯 Python 关键词匹配）；`indexer.py`（从 SQLite 仓储投影 → `upsert`，`rebuild(project_id)` 幂等）；`retriever.py` 门面 `search(text, project_id, *, kinds, type, k, mode)`，emit `retrieval_query` 事件；`factory.py`；`tests/unit/retrieval/test_contract.py` 覆盖 §6 全部用例，parametrize 后端列表 | 契约测试对 `memory` 后端全绿；`domain` 中 `TraceEventType` 增加 `retrieval_query` |
| C5.5 | `feat(knowledge): SqliteFtsIndex backend` | `backends/sqlite_fts.py`：`ensure_schema()` 自建 `idx_fts_documents`（FTS5，`unicode61 remove_diacritics 2`），`capabilities={"keyword"}`，BM25 → `score = 1/(1+max(0,-bm25))`；`Settings` 新增 `retrieval_backend="sqlite_fts"`、`retrieval_default_mode`、`index_dir`、`embedder="null"`、`embedding_*`；`pyproject` 加 `[project.optional-dependencies] lancedb`（MVP 不安装）与 ruff banned-api（`lancedb`/`pyarrow` 仅限 `backends/`；`sqlite3` 仅限 `db/` 与 `backends/sqlite_fts.py`）；接入 C5.3：chunk 落库后调用 `Indexer.index_document()` | 契约测试对 `sqlite_fts` 全绿（含 `hybrid` 请求降级为 `keyword`）；`ruff` 对越界 import 报错 |
| C5.6 | `feat(knowledge): LLM knowledge extractor` | 每 chunk → structured output → `KnowledgeUnit[]`（§8.2 类型枚举、`source_refs`、`confidence`）；按 title 去重合并；落库后调用 `Indexer.index_knowledge_units()` | 单测 FakeModel；golden 期望 KU 集合快照 |
| C5.7 | `feat(api): sources upload/list, extract, knowledge units, index rebuild` | `POST/GET /api/projects/:id/sources`、`POST /api/projects/:id/extract`、`GET /api/projects/:id/knowledge`、`GET /api/projects/:id/knowledge/search?q=`（走门面）、`POST /api/projects/:id/index/rebuild`；CLI `skillforge index rebuild --project <id>` | API 测试（multipart 上传；search 返回 `backend`/`mode_used`） |
| C5.8 | `feat(demo): service recovery runbook (md + pdf)` | `demo/docs/service-recovery-runbook.md` 按 §0.3 设计：主章节 Service Down / 502；Appendix B 独立触发词；导出 PDF | 人工检查 + C5.9 锁定 |
| C5.9 | `test(knowledge): runbook extraction yields Appendix B as diagnostic_rule` | 端到端（FakeModel 或录制响应）：Appendix B 成为独立 KU，type=`diagnostic_rule`；同时把 runbook 构建成 `tests/fixtures/retrieval/runbook_index.json`，供契约测试的 "Appendix B 召回" 用例使用 | 测试通过；契约测试新增用例对 `memory`/`sqlite_fts` 全绿 |

### Phase 6 — Skill Compiler（Day 5）

| # | Commit | 内容 | 完成标准 |
|---|---|---|---|
| C6.1 | `feat(compiler): SkillSpec schema and validation` | §8.4 YAML → pydantic；tools 必须在 registry 中；permissions ⊆ 默认 policy | 单测 |
| C6.2 | `feat(compiler): pass 1-3 knowledge → capability boundary → SkillSpec` | 按 task scope 选 KU：先按 `type`/`trigger` 从 SQLite 仓储过滤，需要相关性排序时经 `Retriever` 门面（`kinds=("knowledge_unit",)`）；LLM 生成 spec 草稿；规则层收紧 permissions（永不放宽） | FakeModel 单测；F3 的 Appendix B **不被选入**（锁定 §0.3）；测试用 `memory` 后端 |
| C6.3 | `feat(compiler): pass 4 SKILL.md generator with instruction ids and source-map` | 模板 + LLM 填充；每条指令 `ins_xx`；`references/source-map.json` 记 `ins → ku → doc/page/sha` | 生成物通过 C6.6 校验 |
| C6.4 | `feat(compiler): pass 5 scripts generator` | 受约束模板：`diagnose/recover/verify.py` 只能调用 tool adapter 提供的函数；LLM 只填充步骤 | `py_compile` 通过；无黑名单调用 |
| C6.5 | `feat(compiler): pass 6 eval case generator` | 从 KU 的 `success_criteria` + fault catalog 生成 `evals.json`；fixture 必须存在于 catalog | 单测 |
| C6.6 | `feat(compiler): pass 7 static validation` | frontmatter schema、指令 source_ref 覆盖率阈值、禁用命令扫描、permissions 校验、脚本语法；输出 `validation_result` 事件 | golden 通过；构造的坏样本失败 |
| C6.7 | `feat(compiler): pass 8 package to registry and skill-card` | 写入 registry 为 DRAFT→（校验通过）CANDIDATE；生成 `skill-card.md` | 单测 |
| C6.8 | `feat(api): compile, skill, versions, validate endpoints` | `POST /api/projects/:id/skills/compile`、`GET /api/skills/:id`、`GET /api/skills/:id/versions`、`POST /api/skills/:id/validate` | API 测试 |
| C6.9 | `test(compiler): compiled skill meets golden acceptance` | 用录制模型响应编译 → 通过静态校验 → evals 含 F1/F2 → 不含 Appendix B 指令 | 测试通过 |
| C6.10 | `spike(compiler): real model compile from runbook` | 真实模型编译，记录质量问题，调 prompt；录制响应进 fixtures | 生成物评测 uplift ≥ 0（对比 Control） |

### Phase 7 — Evolution（Day 6）

| # | Commit | 内容 | 完成标准 |
|---|---|---|---|
| C7.1 | `feat(evolution): FailureAnalyzer produces structured Failure` | 输入 trace + assertion + verifier；LLM 分类到 §8.12 的 class 枚举；`evidence` 只能来自 trace/verifier 原文 | FakeModel 单测；F3 失败 → `missing_instruction` |
| C7.2 | `feat(evolution): evidence retrieval for failure` | 用 symptom/failed_assertion 经 `Retriever` 门面检索（`mode` 取 Settings 默认，MVP 为 keyword）→ `source_support`（doc#page）；只 import 门面，不写任何后端 SQL | 单测：F3 召回 Appendix B（用 `memory` 后端，不依赖 FTS） |
| C7.3 | `feat(evolution): SkillPatcher generates PatchProposal as unified diff` | 输入 previous skill + Failure + evidence + benchmark；输出对 `SKILL.md`/scripts 的 unified diff；**禁止**触碰 `evals/`（配合 C4.5） | 单测：diff 可 apply；对 evals 的 diff 被拒 |
| C7.4 | `feat(evolution): apply patch to new SkillVersion` | 新版本目录、parent 链、`source-map.json` 增量更新（新指令必须有 source_ref） | 单测 |
| C7.5 | `feat(evolution): regression run and EvolutionGate` | 跑全部 case；§8.14 五条件；输出 gate 报告 | 单测五条件各自失败路径 |
| C7.6 | `feat(registry): approve and publish transitions require human` | `approve` 只能由 API 调用（带 approver）；`publish` 复制到 `skills/published/`；系统任何自动路径不得调用 | 单测：evolution 流程结束状态最多为 CANDIDATE |
| C7.7 | `feat(api): evolve, approve, publish, version diff endpoints` | `POST /api/skills/:id/evolve`、`.../versions/:v/approve`、`.../versions/:v/publish`、`GET .../versions/:v/diff` | API 测试 |
| C7.8 | `test(evolution): v0.1 fails F3 → patch → v0.2 passes gate` | 端到端（录制响应）：完整 self-evolution 一轮 | 测试通过；这是 DoD 步骤 8–12 的自动化验证 |

### Phase 8 — Orchestrator + 演示脚本（Day 6 晚 – Day 7 上午）

| # | Commit | 内容 | 完成标准 |
|---|---|---|---|
| C8.1 | `feat(orchestrator): pipeline state machine with events` | `PipelineRun`：INGESTED→EXTRACTED→DRAFTED→VALIDATING→CANDIDATE→EVALUATING→PASSED/FAILED→APPROVED→PUBLISHED；每步 emit `workflow_*` | 单测转移 |
| C8.2 | `feat(orchestrator): background job runner and status api` | asyncio task 管理、取消、`GET /api/jobs/:id` | API 测试 |
| C8.3 | `feat(cli): skillforge demo runs the 15-step DoD headless` | 串起上传→抽取→编译→注入→执行→评测→失败→patch→回归→approve→publish；打印每步结果 | 用录制响应全绿；真实模型至少跑通一次 |
| C8.4 | `feat(demo): judge-mode replay profile` | 预计算 benchmark 缓存 + 现场只 live 跑 1 条；`DEMO_MODE=replay|live` | 切换有效 |

### Phase 9 — Frontend（Day 7）

| # | Commit | 内容 | 完成标准 |
|---|---|---|---|
| C9.1 | `feat(web): app shell, router, api client, ws hook` | TanStack Query、react-router、`useEvents()` | 能连上 ws 打印事件 |
| C9.2 | `feat(web): LiveTrace component` | 时间线：Action / Tool / Input / Output / Evidence / Verification；不显示 CoT | mock 数据渲染 |
| C9.3 | `feat(web): Benchmark component` | Without / With / Uplift 三行大字 + per-case ✅❌ 矩阵（Recharts 可选） | mock 渲染 |
| C9.4 | `feat(web): PipelineStepper component` | Parse→Extract→Spec→Skill→Tests→Validate，随事件推进 | 事件驱动 |
| C9.5 | `feat(web): Judge Mode page /demo` | 四区布局（§10.1）+ 操作按钮：Upload、Compile、Inject Fault、Evaluate、Analyze & Improve、Approve、Publish；DGX 状态角标 | 与真实 API 联调，跑通 15 步 |
| C9.6 | `feat(web): SkillDiff view` | v(n-1)→v(n) unified diff 高亮；显示 Failure reason 与 evidence | 联调 |
| C9.7 | `feat(web): Skill Studio (lite) /skills/:id` | Monaco 只读 SKILL.md、SkillSpec、版本切换、evidence 侧栏 | 联调 |
| C9.8 | `feat(web): Evaluation Lab (lite) /skills/:id/evaluations` | case 矩阵 + 5 指标 + 点击进 trace | 联调 |
| C9.9 | `feat(web): Evolution Timeline` | 版本链、Reason、Benchmark Delta、Approver | 联调 |
| C9.10 | `feat(web): DGX Runtime panel` | 读 gateway `/api/model/status`（model、backend、tokens/s、内存） | 联调 |
| C9.11 | `feat(web): Knowledge Lab (lite)` **[P1]** | 文档列表、KU 列表、点击 KU 定位页码 | 联调 |
| C9.12 | `feat(web): Dashboard` **[P1]** | 统计卡片 | 联调 |

### Phase 10 — DGX Spark / NVIDIA 集成（Day 8；C10.1 的 spike 提前到 Day 1）

| # | Commit | 内容 | 完成标准 |
|---|---|---|---|
| C10.0 | `spike(deploy): measure Step 3.7 Flash on DGX Spark` **（Day 1 执行）** | llama.cpp 起模型；记录常驻内存、tokens/s、并发 1 的单次 agent step 延迟；结论写入 `docs/deployment.md` | 有数据；决定 live/replay 策略 |
| C10.1 | `feat(deploy): llama.cpp compose profile for DGX Spark` | `docker-compose.yml` `profiles: [dgx]`；arm64 + CUDA 镜像；模型下载脚本；ctx/threads 参数 | DGX 上起得来 |
| C10.2 | `feat(models): StepFunLocalAdapter with tool-calling and metrics` | 针对 llama.cpp server 的 tool-call 格式、stop、`/metrics` 采集 tokens/s；`GET /api/model/status` | 与 C9.10 联调 |
| C10.3 | `feat(models): StepFunAPIAdapter fallback` | 云端 API 适配；settings 一键切换 | 切换后 demo 仍通 |
| C10.4 | `feat(evaluator): NVIDIA SkillEvaluator adapter` **[P1]** | 接口 + CLI 包装 + mock；Tier 1/2/3 结果并入 BENCHMARK.md | mock 通；真实工具可用则接 |
| C10.5 | `feat(compiler): NVIDIA Agent Skills convention checks` **[P1]** | 静态校验增加 NVIDIA skills 目录/frontmatter 约定 | golden 通过 |
| C10.6 | `spike(sandbox): OpenShellSandbox adapter skeleton` **[P1]** | 实现接口、feature flag 关闭；文档记录现场稳定性结论 | 不影响主路径 |
| C10.7 | `feat(deploy): full-stack compose and deployment.md` | api + web + lab 在 DGX 一键起 | `docker compose --profile dgx up` 可演示 |

### Phase 11 — Delivery（Day 9，禁止改架构）

| # | Commit | 内容 | 完成标准 |
|---|---|---|---|
| C11.1 | `docs: README with narrative, architecture, official references` | §28 叙事 + §31 引用 + 截图 | — |
| C11.2 | `docs: hackathon-demo.md script and rehearsal checklist` | §16 时间轴、每步点什么、故障恢复预案（模型挂了切 replay） | 排练 2 次 |
| C11.3 | `docs: architecture.md, skill-design.md (from v0.1 design)` | 把设计文档拆到 docs/ 对应文件，同步本计划的调整 | — |
| C11.4 | `fix: ...`（多个小 commit） | 排练中发现的问题 | 每个 fix 一个 commit |
| C11.5 | `docs: article draft and screenshots` | §24 征文主线 | — |

### Phase 12 — 优化阶段：检索层切换到 LanceDB（15 步 DoD 之后，不在 9 天内）

前置：Phase 5 按上述方式落地（端口、门面、契约测试、Indexer 均已存在）。本 Phase 全程**不改** `schema.sql`、不写数据迁移、不改 compiler / evolution / api / web 的调用代码。设计依据 `docs/retrieval-layer.md` §8。

| # | Commit | 内容 | 完成标准 |
|---|---|---|---|
| C12.0 | `spike(knowledge): lancedb on DGX Spark and embedding model budget` | 在 DGX（aarch64）上 `uv sync --extra lancedb` 验证 wheel 可用；候选 embedding 模型（bge-small / nomic-embed 量化 / NeMo Retriever 端点）各自的常驻内存与 CPU 推理延迟；结论写入 `docs/retrieval-layer.md` §9 | 有数据；选定 embedder 方案；模型总内存仍在 R1 预算内 |
| C12.1 | `feat(knowledge): OpenAICompatibleEmbedder` | `embedder.py` 增加实现：调用 `/v1/embeddings`（llama.cpp 或 NeMo Retriever 兼容端点），批量、超时、`dimension` 自检；`Settings.embedder="openai_compatible"` 时由 factory 注入 | 单测（httpx mock）；`Indexer` 在 embedder 非 Null 时填充 `IndexDocument.vector` |
| C12.2 | `feat(knowledge): LanceDbIndex backend with keyword and vector modes` | `backends/lancedb.py`：表 `data/index/lancedb/documents`，schema 由 `IndexDocument` 派生（vector 列维度来自 embedder）；`keyword` 走 Lance 内建 FTS，`vector` 走 ANN；`delete(project_id, document_id)` 用过滤删除；score 归一化；`capabilities={"keyword","vector"}`；加入契约测试 parametrize | 契约测试对 `lancedb` 全绿（在 CI 中以 `-m lancedb` 单独跑，依赖 extra） |
| C12.3 | `feat(knowledge): hybrid mode with RRF fusion` | `LanceDbIndex` 支持 `hybrid`（keyword + vector 各取 2k 后 RRF 融合）；契约测试增加 hybrid 用例（结果集 ⊇ keyword top-1） | 全绿 |
| C12.4 | `feat(cli): index rebuild across backends` | `skillforge index rebuild --project <id> [--backend lancedb] [--all-projects]`；`skillforge index stats` 显示后端、文档数、向量维度 | 切换后端 = 改 `SKILLFORGE_RETRIEVAL_BACKEND` + rebuild，命令幂等 |
| C12.5 | `test(knowledge): retrieval quality evalset and backend comparison` | `tests/fixtures/retrieval_evalset.jsonl`（20–30 条 `query → expected_ids`，含 Appendix B、F1/F2 相关段落、干扰项）；脚本输出 recall@5 / MRR 双后端对比表到 `docs/retrieval-layer.md` §6 | LanceDB 每个模式 recall@5 ≥ FTS5 keyword，否则不得进入 C12.6 |
| C12.6 | `chore(knowledge): make lancedb the default retrieval backend` | `Settings.retrieval_backend` 默认改 `lancedb`，`retrieval_default_mode` 改 `hybrid`；`sqlite_fts` 保留为 fallback；`.env.example`、`deployment.md`、AGENTS.md 同步 | 全部单测 + 契约测试 + C7.8 端到端在两个后端下都通过 |
| C12.7 | `feat(knowledge): NeMo Retriever embedder adapter` **[P2]** | 若 C12.0 选定 NeMo：实现 `NeMoRetrieverEmbedder`，处理其请求格式差异 | 契约测试不变；仅 embedder 替换 |

---

## 4. 关键路径与并行建议

```text
C0.* → C1.* → C2.* → C3.1 ─┬→ C3.2-3.11 → C4.* ──────────────┐
                            │                                  ├→ C7.* → C8.* → C9.5(联调) → C10.7 → C11.*
                            └→ C5.* → C6.* ────────────────────┘
C9.1-9.4（组件用 mock 数据）可与 C4-C7 并行
C10.0 在 Day 1 执行；C10.1-10.3 可在 Day 3 起并行
```

两人分工时：A 走 Runtime/Evaluator/Evolution 主线（C3→C4→C7），B 走 Knowledge/Compiler（C5→C6）+ 前端组件（C9.1-9.4）。C3.1 golden skill 两人一起写，它是双方的契约。

---

## 5. 每日验收（对应架构文档 §30 的 15 步）

| Day | 完成 commit | 可演示的事实 |
|---|---|---|
| 1 | C0.*、C1.*、C10.0 | 按钮/命令注入 502，verifier 判定恢复；知道模型在 DGX 上的真实吞吐 |
| 2 | C2.*、C3.1–C3.5 | golden skill 存在；沙箱与工具能操作 ops-lab |
| 3 | C3.6–C3.11、C4.1–C4.3 | Agent 用 golden skill 真实恢复 F1（DoD 5–7） |
| 4 | C4.4–C4.8、C5.1–C5.5 | Without vs With 数字出来；检索端口与 FTS 后端过契约测试 |
| 5 | C5.6–C5.9、C6.* | 上传 runbook → 自动编译出 skill（DoD 1–4） |
| 6 | C7.*、C8.* | v0.1 失败 F3 → v0.2 通过回归（DoD 8–12），headless 15 步全通 |
| 7 | C9.* | Judge Mode 跑通 15 步（DoD 13–15） |
| 8 | C10.* | 在 DGX Spark 上以 Step 3.7 Flash 跑通 |
| 9 | C11.* | 排练、文档、视频 |

---

## 6. 风险登记

| 风险 | 触发信号 | 预案 |
|---|---|---|
| 模型太慢/OOM（R1） | C10.0 测得 < 10 tok/s 或起不来 | 切 IQ4_XS 或更小 ctx；demo 用 replay + 1 条 live；极端情况 StepFunAPIAdapter |
| 真实模型编译质量差（C6.10） | uplift ≤ 0 | 增强模板约束、减少 LLM 自由度；demo 用录制响应保证可复现，README 诚实说明 |
| Agent 在 Control arm 也能解 F2 | Control 成功率过高，uplift 不明显 | 调整 F2 为需要 `nginx -t` 的变体；或把 F2 归入 F3 类 |
| Docker Desktop（Windows）与 DGX（Linux/arm64）行为差异 | 集成测试仅本地通过 | Day 3 起每日在 DGX 上跑一次 `pytest -m integration` |
| OpenShell / SkillEvaluator 不可用 | 安装失败 | 保留 adapter + mock，Demo 不提或只提"架构已预留" |
| 前端时间不够 | Day 7 结束 Judge Mode 未联调 | 砍 C9.7–C9.12，Judge Mode 一页承担全部演示 |
| 检索层被"顺手"耦合（R12） | PR 中出现 `schema.sql` 含 `fts5`、compiler/evolution 里出现 `MATCH` 或 `import lancedb`、`RetrievalHit` 增加领域对象字段 | ruff banned-api + C2.1 的 grep 完成标准 + 契约测试；review 时对照 `docs/retrieval-layer.md` §10 |
| LanceDB aarch64 wheel 或 embedding 内存超预算（C12.0） | DGX 上装不上或模型总内存 > 120 GB | 保持 `sqlite_fts` 默认；embedding 走外部端点或纯 CPU；Phase 12 整体可推迟，MVP 不受影响 |
