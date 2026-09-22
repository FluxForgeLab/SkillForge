# 检索层设计：从 SQLite FTS5 到 LanceDB 的无重构演进

> 状态：已拍板（对应执行方案 R12）
> 适用：`skillforge/knowledge/retrieval/`，以及所有调用检索的模块（Compiler pass 2、Failure Analyzer 证据检索、Knowledge Lab）
> 一句话：**索引是投影，不是数据。** SQLite 永远是 system of record；检索后端只是可丢弃、可重建的派生物。换后端 = 换一个实现类 + 重建索引，业务代码零改动。

---

## 1. 目标与非目标

目标：

- MVP（Hackathon，15 步 DoD 之前）只用 SQLite FTS5 + BM25，不引入任何向量库依赖，不加载任何 embedding 模型（R1 内存约束）。
- 优化阶段切到 LanceDB（关键词 + 向量 + hybrid），**不改** Compiler / Evolution / API 的任何调用代码，**不迁移** SQLite 中的任何数据。
- 两个后端通过同一套契约测试，切换的验收标准是机械的：契约测试全绿 + 召回评测不低于 FTS5。

非目标：

- 不把 SQLite 的关系数据（项目、版本、状态机、trace、evals）搬进 LanceDB。LanceDB 不擅长事务和状态机，这样做是重写不是优化。
- MVP 不做 hybrid、不做 rerank、不做 embedding。这些全部属于优化阶段。
- 不引入 LangChain / LlamaIndex 一类的检索框架。端口只有三个方法，自己写更少的代码、更少的隐藏行为。

---

## 2. 数据归属：谁是真相

```text
                SQLite（system of record，永久）
   ┌──────────────────────────────────────────────────────┐
   │ source_documents  chunks  knowledge_units  ...       │
   │  - 全文内容、page/line、sha256、type、confidence     │
   └──────────────────────────────┬───────────────────────┘
                                  │ Indexer（投影，可随时 rebuild）
                                  ▼
                RetrievalIndex（派生物，可丢弃）
   ┌──────────────────────────┐   ┌──────────────────────────┐
   │ SqliteFtsIndex (MVP)     │   │ LanceDbIndex (优化阶段)   │
   │ idx_fts_documents        │   │ data/index/lancedb/      │
   │ FTS5 + BM25              │   │ keyword + vector + hybrid│
   └──────────────────────────┘   └──────────────────────────┘
```

规则：

1. `chunks`、`knowledge_units` 是**普通表**，在 `db/schema.sql` 里；它们的内容、位置、来源关系全在 SQLite。
2. `db/schema.sql` **不包含**任何 FTS5 虚拟表、trigger 或索引专用表。索引后端自己在 `ensure_schema()` 里创建自己的表（前缀 `idx_`）或自己的目录（`data/index/<backend>/`）。删掉后端 = 删掉 `idx_*` 表或那个目录，核心库不受影响。
3. 检索命中只返回 `id + kind + score + 少量展示字段`；调用方要拿完整对象时回 SQLite 仓储读（`chunks_repo.get(id)`）。这样后端里存什么字段是后端的私事，换后端不会影响调用方拿到的数据形状。
4. `Indexer.rebuild(project_id)` 必须是幂等的：drop + 从 SQLite 全量重建。这是"迁移"的唯一形式。

---

## 3. 端口（Port）定义

位置：`skillforge/knowledge/retrieval/base.py`。所有类型是 pydantic 模型，字段一旦进 MVP 就只增不删。

```python
IndexKind = Literal["chunk", "knowledge_unit"]
RetrievalMode = Literal["keyword", "vector", "hybrid"]


class IndexDocument(BaseModel):
    """写入索引的最小单元。由 Indexer 从 SQLite 行构造，后端不得反向依赖 SQLite。"""
    id: str                      # 与 SQLite 主键一致：chunk_id 或 ku_id
    kind: IndexKind
    project_id: str
    document_id: str
    text: str                    # 用于关键词索引与 embedding 的正文
    title: str | None = None
    type: str | None = None      # knowledge_unit 的 §8.2 类型；chunk 为 None
    page: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    metadata: dict[str, str] = {} # 只允许 str→str，避免后端 schema 漂移
    vector: list[float] | None = None  # MVP 恒为 None；优化阶段由 Indexer 经 Embedder 填充


class RetrievalQuery(BaseModel):
    text: str
    project_id: str
    kinds: tuple[IndexKind, ...] = ("chunk", "knowledge_unit")
    type: str | None = None      # 只对 knowledge_unit 生效
    document_ids: tuple[str, ...] | None = None
    k: int = 10
    mode: RetrievalMode = "keyword"   # 后端不支持时降级并在 hit.mode_used 里说明
    vector: list[float] | None = None # 由 Retriever 门面填充，调用方不碰


class RetrievalHit(BaseModel):
    id: str
    kind: IndexKind
    score: float                 # 归一化到 [0, 1]，越大越相关；调用方只能用来排序和设阈值
    text: str                    # 摘要/原文，展示用；权威内容回 SQLite 取
    title: str | None = None
    type: str | None = None
    document_id: str
    page: int | None = None
    line_start: int | None = None
    backend: str                 # "sqlite_fts" | "lancedb" | "memory"
    mode_used: RetrievalMode     # 实际使用的模式


class RetrievalIndex(Protocol):
    name: str
    capabilities: frozenset[RetrievalMode]

    async def ensure_schema(self) -> None: ...
    async def upsert(self, docs: Sequence[IndexDocument]) -> None: ...
    async def delete(self, *, project_id: str, document_id: str | None = None) -> None: ...
    async def search(self, query: RetrievalQuery) -> list[RetrievalHit]: ...
```

设计要点：

- **`score` 归一化**是弹性的关键。FTS5 的 `bm25()` 是负数且越小越好，cosine 是 [-1, 1]，hybrid 是 RRF 分数。每个后端负责把自己的原始分数映射到 [0, 1] 越大越好；调用方永远不写 `if score < -2.0` 这类依赖后端语义的代码。
- **`capabilities` + 降级**：调用方可以请求 `hybrid`，`SqliteFtsIndex` 会降级为 `keyword` 并在 `mode_used` 里如实返回。这让 Compiler / Analyzer 的代码在两个阶段一字不改。
- **`vector` 在 `IndexDocument` 和 `RetrievalQuery` 上都是可选字段**，MVP 恒为 `None`。优化阶段 Indexer 与 Retriever 门面负责填充，后端拿到就用，拿不到就退回关键词。
- **`delete` 按 `project_id/document_id` 粒度**而不是按单条 id：重新上传文档版本时整体替换，与 `SourceDocument.version` 语义对齐，也避免后端必须支持单条删除。

---

## 4. 三个角色，各归其位

```text
调用方（compiler / evolution / api）
      │  只 import 这个
      ▼
Retriever 门面        knowledge/retrieval/retriever.py
  search(text, project_id, *, kinds, type, k, mode) -> list[RetrievalHit]
  - 读 Settings 决定 mode 默认值
  - 若 mode 需要向量则调 Embedder.embed_query()
  - emit TraceEvent(type="retrieval_query", backend, mode_used, k, hit_ids)
      │
      ▼
RetrievalIndex 后端   knowledge/retrieval/backends/{sqlite_fts,lancedb,memory}.py
      ▲
      │  upsert / delete / rebuild
Indexer               knowledge/retrieval/indexer.py
  index_document(document_id)   # C5.3 chunk 落库后调用
  index_knowledge_units(document_id)   # C5.5 抽取落库后调用
  rebuild(project_id)             # CLI `skillforge index rebuild`
  - 从 SQLite 仓储读行 → IndexDocument
  - 若 Embedder 不是 Null 则批量 embed 后填 vector
```

`Embedder` 端口（`knowledge/retrieval/embedder.py`）在 MVP 只有 `NullEmbedder`（`embed()` 抛 `NotImplementedError`，`dimension = None`）。接口先定下来，字段先留好，优化阶段只加实现类：

```python
class Embedder(Protocol):
    name: str
    dimension: int | None
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...
```

工厂：`knowledge/retrieval/factory.py` 按 `Settings.retrieval_backend` / `Settings.embedder` 返回实例。业务代码通过 FastAPI 依赖或显式传参拿到 `Retriever`，不自己 new 后端。

---

## 5. 导入边界（用 ruff 锁死）

| 模块 | 允许 import |
|---|---|
| `knowledge/retrieval/backends/sqlite_fts.py` | `sqlite3`、`db.connection` |
| `knowledge/retrieval/backends/lancedb.py` | `lancedb`、`pyarrow` |
| `knowledge/retrieval/backends/memory.py` | 标准库 |
| `knowledge/retrieval/{retriever,indexer,factory}.py` | `base`、`embedder`、`db.repositories`、`tracing` |
| 其余所有模块 | 只允许 `from skillforge.knowledge.retrieval import Retriever, RetrievalHit, RetrievalQuery` |

在 `pyproject.toml` 加 `[tool.ruff.lint.flake8-tidy-imports.banned-api]` 禁止 `lancedb`、`pyarrow` 在 `backends/` 之外被 import；`sqlite3` 只允许在 `db/` 与 `backends/sqlite_fts.py`。C5.4 落地时一并配置。

---

## 6. 契约测试：切换的验收标准

`tests/unit/retrieval/test_contract.py`，`pytest.mark.parametrize("backend", [...])`，所有后端必须全绿：

| 用例 | 断言 |
|---|---|
| upsert → search | 写入 5 条，关键词查询 top-1 是预期 id |
| project 隔离 | 同文本不同 project_id，只召回本 project |
| kind 过滤 | `kinds=("knowledge_unit",)` 不返回 chunk |
| type 过滤 | `type="diagnostic_rule"` 只返回该类型 |
| document_ids 过滤 | 限定后不返回其他文档 |
| 幂等 upsert | 同 id 写两次，结果集不重复 |
| delete by document | 删除后不再召回，其他文档不受影响 |
| score 契约 | 所有 hit 的 `0 <= score <= 1`，且列表按 score 降序 |
| 模式降级 | 请求 `hybrid`，不支持的后端返回 `mode_used="keyword"` 且不抛错 |
| Appendix B 召回 | 用 `demo/docs` runbook 的 fixture 建索引，查询 `"502 upstream nginx -t"` top-3 含 Appendix B（这是 R5 演示的命门） |
| rebuild 幂等 | rebuild 两次，结果与一次相同 |

新后端加入的流程：实现类 → 加进 parametrize → 全绿 → 才允许在 `factory.py` 注册。

召回评测（优化阶段 C12.5）：`tests/fixtures/retrieval_evalset.jsonl`，20–30 条 `(query, expected_ids)`，计算 recall@5 / MRR。LanceDB 成为默认的门槛：**每个模式的 recall@5 ≥ FTS5 keyword**。

---

## 7. MVP 阶段的具体约束（写进 C2.1 / C5.4 / C5.5）

1. `db/schema.sql`：`chunks(id, document_id, project_id, ordinal, text, title, page, line_start, line_end)`、`knowledge_units(...)` 普通表 + 普通索引。**不建 FTS**。
2. `SqliteFtsIndex.ensure_schema()` 建 `idx_fts_documents` 一张 FTS5 表（contentless 或 external content 均可，字段：`id UNINDEXED, kind UNINDEXED, project_id UNINDEXED, document_id UNINDEXED, type UNINDEXED, title, text`），`tokenize='unicode61 remove_diacritics 2'`。BM25 → `m = max(0, -bm25)`，`score = m / (1 + m)`。
3. `Retriever` 门面就是执行方案里的 `search()`；C6.2、C7.2、C9.11 只 import 门面。
4. `Settings` 新增（MVP 默认值）：`retrieval_backend: Literal["sqlite_fts","lancedb","memory"] = "sqlite_fts"`、`retrieval_default_mode: RetrievalMode = "keyword"`、`index_dir: Path = Path("data/index")`、`embedder: Literal["null","openai_compatible"] = "null"`、`embedding_base_url`、`embedding_model`、`embedding_dimension: int | None = None`。
5. `pyproject.toml`：`lancedb` 放在 optional extra `[project.optional-dependencies] lancedb = ["lancedb>=0.x", "pyarrow"]`，MVP 不安装。
6. Trace 事件枚举新增 `retrieval_query`（对设计文档 §19 的补充），payload：`backend, mode_used, k, query_len, hit_ids[:k]`。Knowledge Lab 与 Failure Analyzer 的证据链靠它可视化。

---

## 8. 优化阶段切换步骤（对应执行方案 Phase 12）

```text
C12.0 spike     DGX 上 pip install lancedb（aarch64 wheel 是否可用）；embedding 模型选型与内存实测
C12.1 feat      OpenAICompatibleEmbedder（llama.cpp /v1/embeddings 或 NeMo Retriever 兼容端点）
C12.2 feat      LanceDbIndex：keyword（Lance 内建 FTS）+ vector；通过契约测试
C12.3 feat      hybrid 模式（RRF 融合）；契约测试加 hybrid 用例
C12.4 feat      CLI `skillforge index rebuild --project <id> [--backend lancedb]`；切后端 = 改 Settings + rebuild
C12.5 test      召回评测集 + 双后端对比报告；门槛：LanceDB ≥ FTS5
C12.6 chore     默认切到 lancedb；sqlite_fts 保留为 fallback（Settings 一行切回）
C12.7 feat [P2] NeMo Retriever Embedder adapter
```

切换过程中**不会**发生：改 `schema.sql`、写数据迁移脚本、改 Compiler / Evolution / API 任何一行、改前端。

---

## 9. 内存预算提醒（R1 延伸）

DGX Spark 128 GB 统一内存里 Step 3.7 Flash 已占 ~111 GB。优化阶段的 embedding 模型必须满足其一：

- 极小模型（≤ 0.5 GB，如 bge-small / nomic-embed-text 量化版），或
- 纯 CPU 推理（ONNX / llama.cpp `--n-gpu-layers 0`），或
- 外部端点（NeMo Retriever 部署在另一台机器）。

`Embedder` 是端点式接口，三种方式对业务层无差别。LanceDB 本身是嵌入式库，磁盘存储、内存占用与索引大小成正比，对本项目的文档规模（万级 chunk）可忽略。

---

## 10. 常见误操作（禁止）

- 在 `schema.sql` 里加 FTS 表或 trigger。
- 在 compiler / evolution 里写 `MATCH` 查询或 `import lancedb`。
- 让 `RetrievalHit` 携带完整领域对象（后端 schema 会因此被业务耦合）。
- 用 `score` 的绝对值做跨后端比较。
- 把 LanceDB 当主库存 `knowledge_units`。
- MVP 阶段"顺手"装上 `lancedb` 或 embedding 模型。
