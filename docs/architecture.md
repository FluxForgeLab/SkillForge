# SkillForge 架构

这份说明描述**现在在跑的系统**。历史设计在 `docs/SkillForge_Architecture_Design_v0.1.md`。执行方案 `docs/execution-plan.md` §0 已经改过其中几处。两处冲突时以执行方案为准。本文不改代码，也不改那份 v0.1 原文。

## 系统在做什么

企业 Runbook 被编译成 Agent 能执行的 Skill。同一模型、同一套工具、同一预算跑两臂，只差系统提示里有没有这份 Skill。评测算两臂成功率之差。自动流程停在候选版本，批准和发布由人触发。

对应 v0.1 的 §6、§7。图里的模型平面当时画的是 StepFun；现行推理见下文「模型」，不是那张图的 `STEP` 节点。

## 四个平面

| 平面 | 做什么 | 记录在哪 |
|---|---|---|
| 控制面 | FastAPI、编排、编译、评测、失败分析、补丁、注册表、trace | SQLite |
| 知识面 | 上传、解析、切块、抽取、检索 | SQLite 是记录；索引是投影 |
| 模型面 | 只经过 `ModelGateway` | 不在业务模块里直接调 SDK |
| 执行面 | 沙箱跑生成的脚本；ops-lab 白名单操作容器 | 两个面，不能并成一个 |

仓库是单一 Python 包 `skillforge/`，外加 `apps/web`。v0.1 §17 里的 `services/api`、顶层 `adapters/` 没有落地。

## 两个执行面

这是执行方案 §0.1 R3 和 §0.4，用来解开「Agent 要操作 Docker」和「沙箱不能挂 docker.sock」的冲突。

沙箱（`DockerSandbox`）只跑生成脚本和只读 shell：`shell.read`、`file.read`、`file.write`、`http.get`。不挂 `docker.sock`、宿主根目录、SSH 密钥或 `.env`。网络是 bridge，并设置 `host.docker.internal:host-gateway`。不用 `network_mode=host`，也不用 `none`。

`http.get` 只允许 ops-lab 的回环地址，端口必须等于 `opslab_base_url`。沙箱里这个地址改写成 `host.docker.internal`。HTTP 4xx/5xx 返回状态码，不算工具错误；连接失败才算。

控制面的 `OpsLabToolAdapter` 才碰 Docker 和 nginx：`docker.inspect`、`docker.logs`、`docker.restart`、`nginx.read_config`、`nginx.write_config`、`nginx.test`、`nginx.reload`。只作用于指定 compose 项目里的容器。本地 `just lab-up` 的项目名是 `skillforge-lab`。DGX 全栈 `docker compose --profile dgx` 的项目名是 `skillforge`。

`docker.restart` 在调用 Docker 之前拒绝 `mock-db` 和 `database`，违规名是 `restart_database`。`nginx.write_config` 看到 `rm` 不写文件。没有删除 volume 的工具。永久拒绝 `sudo`、`mount`、`shutdown`、`rm -rf`。

OpenShell 在 v0.1 §8.8 里是可选沙箱。这台 Spark 上 `openshell` 不在 PATH。`SKILLFORGE_SANDBOX_BACKEND` 默认 `docker`。选成 `openshell` 时骨架直接失败，不启动二进制。主路径不依赖它。

## 运行时

对应 v0.1 §8.7，循环按 §0.4 落地。

自研 ReAct，不引入 agent framework。一次 `generate` 算一步。Control 与 Treatment 共用 `runtime_tools()`、同一个模型和同一份 Settings 预算。唯一差别是有没有把 `SKILL.md` 追加进系统提示。`skill_path` 为空就是没有 Skill。有 Skill 时追加名称、描述、触发词、正文，以及非空的 source-map。`evals/` 和 `skill-card.md` 不进提示。Skill 前端的 `tools` / `permissions` 不裁剪注册表。

工具名在注册表和 `SKILL.md` 里保持带点，例如 `docker.inspect`。发给不接受点号的 OpenAI 兼容端点时，只在适配器边界换成 `docker_inspect`，响应再映射回来。

策略违规记入 `policy_violations` 并交回模型，循环继续。沙箱在 `finally` 里销毁。Harness 的一次运行写入 `agent_runs`。评测的每一轮写入 `evaluation_runs`。两张表不要混用。`GET /api/runs/{id}` 读前者，`GET /api/runs/{id}/events` 读 `trace_events`。

Live Trace 只展示动作、工具、输入、输出、证据、校验。vLLM 的 `reasoning` 不进入 trace。

## 两条状态机

对应 v0.1 §5 与 §9 的拆分（执行方案 §0.1 R4）。流程状态和版本状态不是同一个枚举。

`PipelineState`：`INGESTED → EXTRACTED → DRAFTED → VALIDATING → CANDIDATE → EVALUATING → PASSED 或 FAILED`。只有 `PASSED` 能到 `APPROVED`，再到 `PUBLISHED`。`FAILED` 与 `PUBLISHED` 没有出边。无头演示把「v0.1 没通过 F3」记成评测结果，流水线仍走 `PASSED`，这样后面的批准还走得通。这不是把失败写成成功。

`SkillVersionStatus`：`DRAFT → CANDIDATE → VALIDATED → APPROVED → PUBLISHED`，前几步也可以 `REJECTED`。静态校验通过才从草稿升到候选。升到候选不会自动写评测封印，也不会批准。批准必须带非空 approver，先到 `VALIDATED` 再到 `APPROVED`。发布只接受已批准的版本。补丁产生新的草稿，校验通过后可以再升到候选，然后停住。进化接口不调用批准。

## 评测与进化

对应 v0.1 §8.9、§8.12–§8.14、§23，计算按 §0.5。

`passed` 只表示断言：`expected` 的每个字段都出现在 verifier 输出里且值相等，并且 trace 没有命中 `forbidden`。`true` 不等于 `1`。禁止项既看 `tool_call.name`，也看 `policy_violation.output.name`。超时的评测行是 `failed`。步数用尽但断言已经跑完时，行可以是 `completed`，过不过仍只看 `passed`。

`uplift_pp = (treatment 成功率 − control 成功率) × 100`。回归数是 Treatment 成功率低于 Control 的 case 个数。`write_benchmark` 把这些写进版本目录的 `BENCHMARK.md` 和 `benchmark.json`。评测 HTTP 任务不会自动写这份文件。

`record_candidate_evals` 把 `evals.json` 的 sha256 写入 `eval_seals`。已有封印不能覆盖。评测前若文件变了，抛 `EvalGuardError`，不注入故障，不写评测行。没有封印时评测仍可跑。补丁改了 `evals/` 会被 `reject_patched_evals` 拒绝。

`POST /api/skills/{id}/evaluate` 返回 `job_id`。`skillforge eval` 目前只有 `--replay`，缺缓存就退出，不跑 Agent。

NVIDIA SkillEvaluator（v0.1 §8.11）是适配器加 mock。校验和去重给出确定性结果，live 档不跑。主评测仍是上面的断言。

失败分析的类别是枚举，例如 `missing_instruction`。补丁是 `SKILL.md` 或 `scripts/` 的 diff，不能放宽权限，不能删掉失败测试。

## 知识与检索

对应 v0.1 §8.1–§8.3，存储按 §0.6 和 `docs/retrieval-layer.md`。

SQLite 里的 `chunks` 和 `knowledge_units` 是记录。`schema.sql` 不含 FTS。全文索引是运行时投影，可以 `skillforge index rebuild` 重建。业务只调用 `Retriever.search`。编译器、进化和 API 不写 `MATCH`，不 `import lancedb`。MVP 不装向量库，不加载 embedding。请求向量或混合模式时降级成关键词，并回报 `mode_used`。

分数越大越好：`m = max(0, -bm25)`，`score = m / (1 + m)`，落在 `[0, 1)`，只用于同一次查询内排序。

模型抽取时只填类型、标题、触发词和步骤。`source_ref` 由代码写入。稳定坐标是文档 sha256 加行号或页码，不是每次重抽都会变的 `chunk_id`。

## 模型

v0.1 §13 的主路径是 llama.cpp + Step 3.7 Flash。执行方案 §0.7 取代了它。业务层仍只走 `ModelGateway` 的 OpenAI 兼容适配器。

DGX 上是 vLLM，模型 `nvidia/Qwen3.6-35B-A3B-NVFP4`，镜像 `nvcr.io/nvidia/vllm:26.08-py3`。上下文 32768，`gpu-memory-utilization` 0.4。工具解析 `qwen3_xml`，reasoning 解析 `qwen3`。服务只听 `127.0.0.1:8001`。

`SKILLFORGE_MODEL_PROFILE=local_vllm` 强制这个端点和温度 0。`kimi` 强制 Moonshot、`kimi-k3` 和温度 1。`custom` 沿用各项字段，仓库默认温度是 0。`stepfun_local` 和 `stepfun_api` 未实现。

2026-09-28 的通过线：容器在 aarch64 上起来；一次 `docker.inspect` 以 OpenAI `tool_calls` 返回并映射回 `docker.inspect`（墙钟 1.047 秒）；单流 128 个 completion token、墙钟 1.089 秒、117.6 tok/s；与 API、网页、ops-lab 同时运行时没有 OOM。`GET /api/model/status` 的 token/秒是 vLLM 直方图的累计均值；没有模型显存指标时 `memory_bytes` 为 null。细节在 `docs/deployment.md`。

Nemotron 没有启动。原因是千问已经通过，不是那两个模型失败。

## 安全与演示环境

对应 v0.1 §15、§21。威胁仍是提示注入、恶意文档、危险 shell、凭据泄露、任意网络、文件系统逃逸和技能供应链。落地手段是：来源引用、静态校验、沙箱策略、控制面白名单、评测 forbidden、人批准。

演示环境是 `demo/ops-lab`：nginx、backend、mock-db。宿主机入口 `8088`。三条故障是 F1 `backend_stopped`、F2 `nginx_wrong_upstream`、F3 `nginx_bad_config_reload`。F3 的修复知识在 Runbook Appendix B，不在 v0.1 正文里。现场 live 只跑 F1。1/3、2/3、3/3 是 §16 的预计算叙述，不是一次现场矩阵的实测。

端口：网页 `5173`，SkillForge API `8000`，DGX 上的 vLLM `8001`，ops-lab nginx `8088`。容器内 backend 才听 `8080`。

登录表和硬件手册不进 git。日志和 trace 不写 API key、主机密码或 SSH 信息。
