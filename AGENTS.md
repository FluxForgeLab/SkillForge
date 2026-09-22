# AGENTS.md — SkillForge

面向在此仓库工作的 AI 编码 Agent。人类开发者也可读，但语气与内容按 Agent 需要组织。

## 项目一句话

SkillForge 把企业 Runbook 编译为可执行、可评测、可迭代、可治理的 Agent Skill，并通过
"Without Skill vs With Skill" 的确定性评测证明 Skill 让 Agent 变得更好。运行在 NVIDIA DGX Spark（aarch64，128 GB 统一内存）
上，本地推理模型 Step 3.7 Flash（llama.cpp），Hackathon 首个场景是 Service Recovery。

## 先读什么

| 需要 | 读 |
|---|---|
| 为什么这么设计 | `docs/SkillForge_Architecture_Design_v0.1.md` |
| 检索层（FTS5 → LanceDB）怎么做到不重构 | `docs/retrieval-layer.md` |
| 现在做什么、做到什么程度算完成 | `docs/execution-plan.md`（§0 是对设计文档的审阅调整，§3 是 commit 清单） |
| 环境操作、评测、写 Skill 的具体步骤 | `.cursor/skills/*/SKILL.md` |
| 连通性 / 打不开 / connection refused | `.cursor/skills/diagnose-listen/SKILL.md`；约束见 `measure-before-story` |
| 持久约束 | `.cursor/rules/*.mdc`（自动加载） |

设计文档与执行方案冲突时以执行方案为准；执行方案不合理时先提出，不要静默偏离。

## 北极星

设计文档 §30 的 15 步 DoD 跑通之前，不扩展功能。判断任何工作是否值得做的标准：它是否让这 15 步更接近跑通、更稳定、或更可演示。

## 仓库地图（目标结构，随执行方案逐步建立）

```text
skillforge/          唯一 Python 包：domain db tracing models ingestion knowledge compiler
                     sandbox runtime evaluator evolution registry orchestrator api cli.py
apps/web/            React + TS + Vite 前端；/demo Judge Mode 是最重要的页面
demo/ops-lab/        可注入故障的真实 Docker 环境：nginx + backend + mock-db + faults + verifier
demo/docs/           Demo 用 Runbook（md + pdf）
skills/golden/       手写参照 Skill（契约）；skills/generated|published 为产物，不进 git
tests/unit tests/integration tests/fixtures
docs/                设计文档、执行方案、部署与演示脚本
```

## 常用命令

端口不是同一个服务：`5173` Vite 网页；`8000` SkillForge API；`8080` 模型 `/v1` 或 ops-lab backend **容器内**（不是网页）；`8088` ops-lab nginx 宿主机入口。

快捷方式（C0.5）：`just api|web|lint|test|lab-up|lab-down|lab-reset|lab-verify`，`just lab-inject backend_stopped`。Windows 无 just 时：`.\scripts\dev.ps1 lint`。

尚未存在的命令在对应执行方案条目中创建，不要临时发明替代方案。

```bash
# Python
uv sync
uv run uvicorn skillforge.api.main:app --reload --port 8000
uv run pytest -m "not integration"          # 单测（无 Docker、无真实模型）
uv run pytest -m integration                # 需要 ops-lab 运行
uv run ruff check . && uv run ruff format .

# 前端
pnpm -C apps/web install && pnpm -C apps/web dev
pnpm -C apps/web lint && pnpm -C apps/web build

# Demo 环境
docker compose -f demo/ops-lab/docker-compose.yml -p skillforge-lab up -d --build
python demo/ops-lab/faults/inject.py backend_stopped
python demo/ops-lab/verifier/verify.py
python demo/ops-lab/faults/reset.py

# CLI（C3.8 / C4.x / C8.3 后可用）
uv run skillforge run --task "..." --fault backend_stopped --skill skills/golden/service-recovery
uv run skillforge eval --skill <dir> --repeats 1
uv run skillforge demo
```

## 工作方式

1. 工作单位是执行方案中的一个 commit 编号（`C3.5`）。先读该条目的"内容"与"完成标准"。
2. 实现 + 测试 + 文档按同一个 commit 准备；提交前跑上面的 lint 与单测；涉及 Docker/前端时追加对应命令。真正执行 `git commit` 以 `workflow-and-commits.mdc` 为准，需要用户明确要求。
3. Commit message：`<type>(<scope>): <summary>`，body 首行 `Plan: C3.5`。
4. 范围外的发现写在回复末尾作为建议，不顺手改。
5. 真实模型的响应录制到 `tests/fixtures/transcripts/`，测试用回放；本地开发默认用 `FakeModelAdapter` 或 OpenAI-compatible 云端端点，不假设本机有 GPU。
6. 排障先测量 LISTEN 元组（尝试的地址族/IP/端口 vs 实际在听的），再解释原因。Cursor 内置浏览器失败不构成本机失败。

## 已拍板的决策（不重新讨论）

- 单一 Python 包 + 单一 `pyproject.toml`（uv、ruff、pytest）；SQLite 永远是 system of record；无 ORM。
- 检索是投影：`knowledge/retrieval` 端口（`RetrievalIndex` 后端 / `Retriever` 门面 / `Indexer` 重建），MVP 后端 `sqlite_fts`，优化阶段（Phase 12）切 `lancedb`——只改 Settings + `skillforge index rebuild`，不改 schema、不迁数据、不改调用方。MVP 不安装 lancedb、不加载 embedding 模型。设计：`docs/retrieval-layer.md`。
- 所有模型调用经 `ModelGateway`；结构化输出经 `models/structured.py`。
- 两个执行面：`Sandbox`（生成脚本）与 `OpsLabToolAdapter`（控制面白名单 docker/nginx 操作）。
- 两个状态机：`PipelineState` 与 `SkillVersionStatus`。
- 自研最小 ReAct loop；Control 与 Treatment 同模型、同工具、同预算，只差 SKILL.md。
- 先手写 golden skill，再做 Runtime/Evaluator，最后 Compiler 以 golden 为验收参照。
- 确定性能做的不交给 LLM：校验、断言、Gate 全是规则代码。
- Demo 故障集 F1/F2/F3 与 Runbook Appendix B 的对应关系见执行方案 §0.3，这是 self-evolution 演示可复现的基础。

## 红线（详见 `.cursor/rules/safety-boundaries.mdc`）

- 沙箱不挂 docker.sock / 宿主根 / 密钥；ops-lab 操作只走白名单 adapter，永久 deny 删 volume、动 `mock-db`、`rm -rf`、`sudo`。
- 自动流程终点最多 `CANDIDATE`；`approve`/`publish` 必须人工触发。
- `evals/` 对 Patcher 只读（sha256 校验）；Patcher 不得放宽 permissions。
- 每条 SKILL.md 指令必须有 `source_ref`。
- 不提交 `.env`、`data/`、`docs/*.xlsx`、`docs/*.docx`；trace 与日志不含凭据；前端不展示模型 CoT。
- 对 DGX 远程主机只做只读探测，除非条目明确要求部署。
- 排障未量出 LISTEN 元组不得宣布根因（详见 `.cursor/rules/measure-before-story.mdc`）。

## 目标平台注意

- DGX Spark 是 **aarch64**；本地开发机是 Windows x86_64。只用 multi-arch 官方镜像，不下载架构相关二进制。
- Step 3.7 Flash Q4 GGUF ≈ 111 GB，内存极紧。Demo 采用"预计算 Benchmark + 现场 1 条 live run"，不要设计需要现场跑完整评测矩阵的流程。

## 不要做

- 引入 agent framework、ORM、K8s、多 Agent 互聊；MVP 阶段安装 lancedb 或 embedding 模型。
- 在 `schema.sql` 加 FTS 表；在 compiler / evolution / api 里写 `MATCH` 或 `import lancedb`；让 `RetrievalHit` 携带领域对象。
- 为了让 case 通过改 `expected`；为了拉大 uplift 削弱 Control arm。
- 在 Day 9（Delivery）改架构。
- 手动 `docker exec` 修环境来掩盖 inject/reset 的 bug。
