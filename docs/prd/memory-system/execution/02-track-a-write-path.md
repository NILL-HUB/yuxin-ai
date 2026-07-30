# Track A：记忆系统写入路径 -- 任务执行文档

> **创建日期**：2026-07-09
> **Track 负责人**：Agent-Write
> **前置条件**：Phase 0（I1-I6）已完成，Neo4j / PostgreSQL pgvector / Redis 容器可用，统一数据模型 `memory_models.py` 已落地
> **关联架构**：[01-data-models-and-write-path.md](../01-data-models-and-write-path.md) §2 写入路径 | [00-overview.md](./00-overview.md)
> **执行原则**：二开阶段，无生产数据，不做向后兼容，旧代码直接删除

---

## 背景与目标

Phase 0 完成后，开始实现记忆系统的写入路径。写入路径是整个记忆系统的入口，负责将对话事件转化为可检索、可巩固的记忆资产。

**核心数据流**：

```
对话事件 (MemoryEvent)
   │
   ▼
SalienceScorer.score() ── 五因子加权评分
   │
   ├─ score > 0.7  ─► WritePath.FULL    ──► LedgerWriter.write_full_path()
   ├─ 0.3 < score ─► WritePath.SUMMARY  ──► LedgerWriter.write_summary_path()
   └─ score ≤ 0.3  ─► WritePath.STATS   ──► LedgerWriter.write_stats_path()
   │
   ▼
LedgerWriter ── 写入 Neo4j TKG (Episode + Entity + Edge) + pgvector 向量
   │
   ▼
entity_resolution ── 三信号融合（vector + BM25 + LLM）判断新实体合并或创建
```

**关键设计决策**：

1. **自动写入替代逐条确认**：SalienceScorer 评分后自动写入，无需用户确认。用户通过图可视化界面事后管理（详见 [02-storage-and-retrieval.md](../02-storage-and-retrieval.md)）。
2. **完全替代旧系统**：旧路径 `assistant_agent_service → LongTermMemoryService → MemoryCandidateExtractor → MemoryConfidenceTracker → 用户确认 → UserMemoryService.remember()` 全部删除，不做向后兼容。
3. **新路径**：`assistant_agent_service → MemoryWriteService.write_from_conversation() → SalienceScorer.score() → LedgerWriter.write_*()`。

**待替换的旧代码**：

| 旧代码位置 | 内容 |
|---|---|
| `api/internal/service/assistant_agent_service.py` 第 404-424 行 | `_extract_long_term_memory` 方法，调用 `LongTermMemoryService.extract_and_store()`，并推送 SSE `MEMORY_CANDIDATE_PROMPT` 事件 |
| `api/internal/service/long_term_memory_service.py` | 整个文件（旧 LongTermMemoryService，由 Track G 清理） |

---

## 任务依赖关系

```
A1 SalienceScorer ─────┐
                       ├─► A4 写入 API 端点 ──► A5 对话后自动触发集成
A2 LedgerWriter ───────┤
                       │
A3 EntityResolution ───┘ (被 A2 内部调用)
```

- **A1、A2、A3 可并行启动**：三者均依赖 Phase 0 的数据模型与基础设施，相互之间通过 `MemoryEvent` / `SalienceResult` 等模型解耦。
- **A4 依赖 A1 + A2**：API 端点需要注入 SalienceScorer 和 LedgerWriter。
- **A5 依赖 A4**：对话后集成复用 A4 的 MemoryWriteService，或直接组装 SalienceScorer + LedgerWriter。

---

## A1：SalienceScorer -- 五因子评分器

### 目标

实现杏仁核显著性评分器，在事件写入 Ledger 之前评估其记忆价值，输出综合显著性得分和写入路径建议。评分基于五个因子的加权求和：情绪强度、新颖性、目标相关性、结果影响力、复述强化。

### 输入（前置依赖）

| 依赖项 | 来源 | 说明 |
|---|---|---|
| `MemoryEvent` 模型 | Phase 0 / I6 `api/internal/model/memory_models.py` | 评分输入事件 |
| `SalienceResult` 模型 | Phase 0 / I6 `api/internal/model/memory_models.py` | 评分输出 |
| `WritePath` 枚举 | Phase 0 / I6 `api/internal/model/memory_models.py` | FULL / SUMMARY / STATS |
| `Settings.salience.weights` | Phase 0 / I2 `api/internal/config/memory_settings.py` | 五因子权重配置 |
| `Settings.salience.thresholds` | Phase 0 / I2 | full_path=0.7, summary_path=0.3 |
| `Settings.llm.*` | Phase 0 / I2 | model, temperature, request_timeout_s |
| Redis 连接 | Phase 0 / I3 `bms:access_count:{user_id}` | 复述强化计数器 |
| `AsyncOpenAI` 客户端 | Phase 0 | LLM 调用 |

### 输出

**文件路径**：`api/internal/service/memory/salience_scorer.py`

**关键类与函数签名**：

```python
class SalienceScorer:
    def __init__(self, settings: Settings, llm_client: AsyncOpenAI) -> None: ...

    async def score(self, event: MemoryEvent) -> SalienceResult: ...

    def route(self, total_score: float) -> WritePath: ...

    def _compute_total(self, factors: ScoreFactors) -> float: ...

    # 四个 LLM 因子（每个返回 (score, rationale) 元组）
    async def _emotion_intensity(self, event: MemoryEvent) -> tuple[float, str]: ...
    async def _novelty(self, event: MemoryEvent) -> tuple[float, str]: ...
    async def _goal_relevance(self, event: MemoryEvent) -> tuple[float, str]: ...
    async def _outcome_impact(self, event: MemoryEvent) -> tuple[float, str]: ...

    # 纯 Redis 计数器因子（不调 LLM）
    async def _rehearsal_boost(self, event: MemoryEvent) -> float: ...

    # 通用结构化 LLM 调用
    async def _call_llm_structured(
        self, prompt: str, response_model: type[BaseModel],
    ) -> BaseModel: ...

# 四个辅助 BaseModel（LLM 结构化输出）
class _EmotionAnalysis(BaseModel): ...      # intensity, valence, reasoning
class _NoveltyAnalysis(BaseModel): ...      # score, reasoning
class _GoalRelevanceAnalysis(BaseModel): ...# score, reasoning
class _OutcomeImpactAnalysis(BaseModel): ...# score, reasoning

# 评分因子明细 dataclass
@dataclass
class ScoreFactors:
    emotion_intensity: float = 0.0
    novelty: float = 0.0
    goal_relevance: float = 0.0
    outcome_impact: float = 0.0
    rehearsal_boost: float = 0.0
```

### 实现步骤

1. **创建模块文件**：`api/internal/service/memory/salience_scorer.py`，确保 `api/internal/service/memory/__init__.py` 存在。
2. **定义四个辅助 BaseModel**：`_EmotionAnalysis`、`_NoveltyAnalysis`、`_GoalRelevanceAnalysis`、`_OutcomeImpactAnalysis`，字段含 `score: float = Field(..., ge=0.0, le=1.0)` 与 `reasoning: str`。`_EmotionAnalysis` 额外含 `valence: str`（positive / negative / neutral）。
3. **定义 `ScoreFactors` dataclass**：五个 float 字段，默认 0.0。
4. **实现 `SalienceScorer.__init__`**：注入 `settings`、`llm_client`，缓存 `settings.salience.weights`。
5. **实现 `score()` 主方法**：
   - 用 `asyncio.gather(..., return_exceptions=True)` 并行计算四个 LLM 因子。
   - 单个因子异常时降级为 0.5，记 warning 日志。
   - 调 `_rehearsal_boost()` 取累积因子。
   - 调 `_compute_total()` 加权求和。
   - 调 `route()` 决定 WritePath。
   - 组装 `SalienceResult` 返回。
6. **实现四个 LLM 因子方法**：每个方法构造 prompt（含 `event.content` 与最近 3 条 `context_messages`），调 `_call_llm_structured()`，返回 `(score, reasoning)` 元组。
7. **实现 `_rehearsal_boost()`**：
   - Redis key: `bms:access_count:{event.user_id}`
   - 公式：`min(1.0, log(1 + access_count) / log(100))`
   - 异常时降级为 0.0。
   - **不调用 LLM**。
8. **实现 `_compute_total()`**：
   - `total = w1*E + w2*N + w3*G + w4*O + w5*F`
   - 权重从 `Settings.salience.weights` 读取。
   - 返回 `min(1.0, total)`。
9. **实现 `route()`**：
   - `> thresholds.full_path (0.7)` → `WritePath.FULL`
   - `> thresholds.summary_path (0.3)` → `WritePath.SUMMARY`
   - 否则 → `WritePath.STATS`
10. **实现 `_call_llm_structured()`**：
    - 调 `llm_client.chat.completions.create()`，`response_format={"type": "json_object"}`。
    - 用 `response_model.model_validate_json(content)` 反序列化。
    - 失败抛异常（由上层 `score()` 捕获降级）。

### 验收标准

- [ ] **五因子各自返回正常值**：单元测试 mock LLM 返回不同 score，验证 `SalienceResult` 各字段正确透传。
- [ ] **LLM 超时降级**：mock LLM 抛 `asyncio.TimeoutError`，验证对应因子降级为 0.5，主流程不中断。
- [ ] **rehearsal_boost 纯计算**：mock Redis 返回不同 count（0, 50, 99, 200），验证 boost 分别为 0.0、≈0.85、1.0、1.0；验证不发起 LLM 调用。
- [ ] **route 阈值判断**：传入 total_score = 0.8 / 0.5 / 0.2，分别返回 FULL / SUMMARY / STATS。
- [ ] **加权求和正确**：构造已知 factors 与 weights，验证 `_compute_total()` 数值正确且不超过 1.0。
- [ ] **并行执行**：四个 LLM 因子通过 `asyncio.gather` 并行，总延迟 ≈ 单次 LLM 调用而非 4 倍。
- [ ] **单元测试文件**：`api/test/internal/service/memory/test_salience_scorer.py` 覆盖以上场景。

### 关联架构文档章节

- [01-data-models-and-write-path.md](../01-data-models-and-write-path.md) §1.5 SalienceResult
- [01-data-models-and-write-path.md](../01-data-models-and-write-path.md) §2.1 WritePath 枚举与 ScoreFactors
- [01-data-models-and-write-path.md](../01-data-models-and-write-path.md) §2.2 SalienceScorer

---

## A2：LedgerWriter -- 权威账本写入器

### 目标

实现权威账本层写入总控。根据写入路径（FULL / SUMMARY / STATS），将事件以不同粒度写入 Neo4j TKG 和 PostgreSQL pgvector 向量库（`user_memory.embedding` 列）。所有写入遵循 append-only 原则，事实矛盾通过四时间戳双时间模型保留历史可追溯。

### 输入（前置依赖）

| 依赖项 | 来源 | 说明 |
|---|---|---|
| `MemoryEvent` 模型 | Phase 0 / I6 | 写入输入 |
| `WritePath` 枚举 | Phase 0 / I6 | 路径选择 |
| `Settings.pgvector` | Phase 0 / I2 | pgvector 表/列/索引配置 |
| `AsyncDriver` (neo4j) | Phase 0 / I4 | Neo4j 异步驱动 |
| `AsyncSession` (SQLAlchemy) | Phase 0 / I5 | PostgreSQL 异步会话（操作 `user_memory.embedding` 向量列） |
| A3 `entity_resolution()` | 本 Track A3 | 实体消解（写入时合并同名实体） |
| Neo4j schema | Phase 0 / I4 `neo4j_init.cypher` | Episode / Entity 节点约束、`memoryFullText` 全文索引 |

### 输出

**文件路径**：`api/internal/service/memory/ledger_writer.py`

**关键类与函数签名**：

```python
class LedgerWriter:
    def __init__(
        self,
        neo4j_driver: AsyncDriver,
        db_session: AsyncSession,
        settings: Settings,
    ) -> None: ...

    # 三条写入路径
    async def write_full_path(
        self,
        event: MemoryEvent,
        entities: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        embedding: list[float],
    ) -> dict[str, Any]: ...

    async def write_summary_path(
        self,
        event: MemoryEvent,
        summary: str,
        entities: list[dict[str, Any]],   # 调用方截断为 [:5]
        relations: list[dict[str, Any]],  # 调用方截断为 [:5]
        embedding: list[float],
    ) -> dict[str, Any]: ...

    async def write_stats_path(
        self,
        event: MemoryEvent,
        entities: list[dict[str, Any]],
    ) -> dict[str, Any]: ...

    # Neo4j 内部方法
    async def _create_episode_node(
        self, event: MemoryEvent, now: datetime,
        content_override: Optional[str] = None,
    ) -> UUID: ...

    async def _merge_entity_node(
        self, entity: dict[str, Any], now: datetime, user_id: str,
    ) -> UUID: ...

    async def _create_edge(
        self, source_id: UUID, target_id: UUID, relation_type: str,
        t_valid_at: datetime, properties: Optional[dict[str, Any]] = None,
    ) -> None: ...

    async def _increment_entity_access(
        self, entity_name: str, now: datetime,
    ) -> None: ...

    async def _increment_cooccurrence(
        self, entity_a: str, entity_b: str, now: datetime,
    ) -> None: ...

    # pgvector 内部方法
    async def _upsert_vector(
        self, point_id: str, vector: list[float], payload: dict[str, Any],
    ) -> None: ...
```

### 实现步骤

1. **创建模块文件**：`api/internal/service/memory/ledger_writer.py`。
2. **实现 `__init__`**：注入 neo4j_driver、db_session、settings；缓存 `settings.pgvector.table_name` 与 `settings.pgvector.embedding_column`。
3. **实现 `write_full_path()`**：
   - 调 `_create_episode_node(event, now)` 创建 Episode 节点（content=完整原文，tier=hot）。
   - 遍历 entities，对每个调 `_merge_entity_node()`（内部调 A3 `entity_resolution` 决定合并或新建），再调 `_create_edge(episode → entity, "CONTAINS")`。
   - 遍历 relations，对每个 (subject, relation, object) 调 `_merge_entity_node` 拿两端节点，调 `_create_edge(subject → object, relation_type)`。
   - 调 `_upsert_vector(point_id=episode_id, vector=embedding, payload={content, event_type="episode", tier="hot", timestamp, user_id, node_id})`。
   - 返回 `{episode_node_id, entity_count, edge_count, vector_id}`。
4. **实现 `write_summary_path()`**：
   - 调 `_create_episode_node(event, now, content_override=summary)` 创建 Episode 节点（content=摘要，tier=hot，但 pgvector 记录 tier=warm）。
   - 仅处理 `entities[:5]` 与 `relations[:5]`。
   - 调 `_upsert_vector(payload={content: summary, event_type="episode_summary", tier="warm", ...})`。
   - 返回结果摘要。
5. **实现 `write_stats_path()`**：
   - **不写 Neo4j Episode 节点，不写 pgvector 向量**。
   - 对每个 entity 调 `_increment_entity_access()` 更新 access_count 与 last_accessed。
   - 对实体两两调 `_increment_cooccurrence()` 更新 CO_OCCUR_WITH 边的 count 与 last_seen。
   - 返回 `{updated_entities, vector_id: None}`。
6. **实现 `_create_episode_node()`**：
   - Cypher `CREATE (e:Episode {...})`，字段含 `node_id, content, summary, source, tier="hot", created_at, last_accessed, access_count=0, is_active=true, user_id, session_id`。
   - `content_override` 非空时用其替代 `event.content`，summary 取前 200 字符。
7. **实现 `_merge_entity_node()`**：
   - Cypher `MERGE (e:Entity {name: $name, user_id: $user_id})`（name+user_id 唯一约束）。
   - `ON CREATE SET` node_id/type/summary/tier="hot"/created_at/last_accessed/access_count=0/is_active=true/user_id。
   - `ON MATCH SET` last_accessed=now, access_count=access_count+1。
   - **集成 A3**：在 MERGE 前先调 `entity_resolution()` 判断是否合并到已有实体；若匹配则返回 matched_node_id，否则走 MERGE 创建。
8. **实现 `_create_edge()`**：
   - Cypher `MATCH (s {node_id: $source_id}), (t {node_id: $target_id}) CREATE (s)-[r:{relation_type} {...}]->(t)`。
   - 四时间戳双时间模型字段：`t_valid_at`, `t_invalidated_at=null`, `t_transaction_start`, `t_transaction_end=null`。
   - 其他字段：`weight=1.0`, `is_active=true`, `edge_id`, `invalidated_by=null`。
9. **实现 `_increment_entity_access()`**：`MATCH (e:Entity {name: $name}) SET e.access_count=e.access_count+1, e.last_accessed=$now`。
10. **实现 `_increment_cooccurrence()`**：`MERGE (a)-[r:CO_OCCUR_WITH]->(b) ON MATCH SET r.count=r.count+1, r.last_seen=$now ON CREATE SET r.count=1, r.last_seen=$now, r.weight=0.1`。
11. **实现 `_upsert_vector()`**：通过 SQLAlchemy `AsyncSession` 对 `user_memory` 表执行 INSERT ... ON CONFLICT DO UPDATE（upsert），将 `embedding` 列设为 `vector`（pgvector `Vector` 类型），其余 payload 字段写入对应列（content/event_type/tier/timestamp/user_id/node_id），`point_id` 对应 `user_memory.id`。

### 验收标准

- [ ] **节点创建**：用 Neo4j testcontainer 验证 `write_full_path` 后 Episode 节点存在，字段（node_id/content/summary/source/tier/created_at/last_accessed/access_count=0/is_active=true/user_id/session_id）完整。
- [ ] **实体 MERGE**：写入两个同名 entity，验证 Neo4j 中仅一个 Entity 节点，且 `access_count=2`。
- [ ] **边四时间戳**：验证创建的边含 `t_valid_at`, `t_invalidated_at=null`, `t_transaction_start`, `t_transaction_end=null`, `weight=1.0`, `is_active=true`, `edge_id`, `invalidated_by=null`。
- [ ] **pgvector 向量写入**：验证 `write_full_path` 与 `write_summary_path` 后 `user_memory` 表存在对应行，`embedding` 列非空且 payload 字段完整。
- [ ] **STATS 路径不写存储**：验证 `write_stats_path` 后 Neo4j 无新 Episode 节点，`user_memory` 表无新行，但 Entity.access_count 增加、CO_OCCUR_WITH 边 count 增加。
- [ ] **SUMMARY 路径截断**：传入 10 个 entities，验证仅创建 5 个 Entity 节点与 5 条 CONTAINS 边。
- [ ] **append-only**：重复写入同一事件，验证不删除旧数据，新 Episode 节点独立创建。
- [ ] **单元测试文件**：`api/test/internal/service/memory/test_ledger_writer.py` 用 Neo4j testcontainer + PostgreSQL pgvector testcontainer 覆盖以上场景。

### 关联架构文档章节

- [01-data-models-and-write-path.md](../01-data-models-and-write-path.md) §1.3 MemoryNode（Episode / Entity）
- [01-data-models-and-write-path.md](../01-data-models-and-write-path.md) §1.4 MemoryEdge（四时间戳双时间模型）
- [01-data-models-and-write-path.md](../01-data-models-and-write-path.md) §2.3 LedgerWriter

---

## A3：EntityResolution -- 实体消解三信号融合

### 目标

实现 TKG 实体消解模块，对新提取的实体判断是创建新节点还是合并到已有实体。融合向量相似度、BM25 文本匹配、LLM 判定三信号，加权求和后与 `merge_threshold` 比较。

### 输入（前置依赖）

| 依赖项 | 来源 | 说明 |
|---|---|---|
| `Settings.write.entity_resolution` | Phase 0 / I2 | vector_weight, bm25_weight, llm_judge_weight, merge_threshold, edit_distance_threshold |
| `AsyncDriver` (neo4j) | Phase 0 / I4 | 全文索引 `memoryFullText` 检索候选实体 |
| `AsyncSession` (SQLAlchemy) | Phase 0 / I5 | pgvector 向量相似度检索（`ORDER BY embedding <=> :query_vec`） |
| `AsyncOpenAI` | Phase 0 | LLM 判定 |
| Neo4j `memoryFullText` 全文索引 | Phase 0 / I4 `neo4j_init.cypher` | Entity.name + Entity.summary 全文索引 |
| A2 LedgerWriter | 本 Track A2 | A2 调用本模块（反向依赖，通过函数参数注入驱动/客户端） |

### 输出

**文件路径**：`api/internal/service/memory/entity_resolution.py`

**关键类与函数签名**：

```python
@dataclass
class EntityCandidate:
    node_id: str
    name: str
    vector_score: float = 0.0
    bm25_score: float = 0.0
    llm_score: float = 0.0
    fused_score: float = 0.0

@dataclass
class EntityResolutionResult:
    is_new_entity: bool
    matched_entity_id: Optional[UUID] = None
    confidence: float = 0.0
    candidates: list[EntityCandidate] = None

# 模块级主函数
async def entity_resolution(
    entity_name: str,
    entity_type: str,
    entity_summary: str,
    embedding: list[float],
    user_id: str,
    neo4j_driver: AsyncDriver,
    db_session: AsyncSession,
    llm_client: AsyncOpenAI,
    settings: Settings,
) -> EntityResolutionResult: ...

# 三信号计算
async def _compute_vector_scores(
    candidates: list[EntityCandidate],
    query_embedding: list[float],
    db_session: AsyncSession,
    settings: Settings,
) -> list[EntityCandidate]: ...

def _compute_bm25_scores(
    candidates: list[EntityCandidate],
    query_name: str,
    edit_distance_threshold: int,
) -> list[EntityCandidate]: ...

async def _compute_llm_scores(
    candidates: list[EntityCandidate],
    new_name: str,
    new_summary: str,
    llm_client: AsyncOpenAI,
    settings: Settings,
) -> list[EntityCandidate]: ...

# 纯 Python 编辑距离
def _levenshtein_distance(s1: str, s2: str) -> int: ...
```

### 实现步骤

1. **创建模块文件**：`api/internal/service/memory/entity_resolution.py`。
2. **定义 `EntityCandidate` dataclass**：node_id, name, 四个 score 字段。
3. **定义 `EntityResolutionResult` dataclass**：`is_new_entity: bool`, `matched_entity_id: Optional[UUID]`, `confidence: float`, `candidates: list[EntityCandidate]`。
4. **实现主函数 `entity_resolution()`**：
   - Step 1：Cypher `MATCH (e:Entity {type: $type, is_active: true, user_id: $user_id})` 检索同类型候选实体；同时用 `memoryFullText` 全文索引检索（`CALL db.index.fulltext.queryNodes('memoryFullText', $query)`）补充候选。
   - 候选为空 → 直接返回 `EntityResolutionResult(is_new_entity=True, confidence=1.0)`。
   - Step 2：调 `_compute_vector_scores()`。
   - Step 3：调 `_compute_bm25_scores()`。
   - Step 4：调 `_compute_llm_scores()`（仅对 `0.5*vector + 0.5*bm25 >= 0.6` 的候选调 LLM，节省成本）。
   - Step 5：融合 `fused = w1*vector + w2*bm25 + w3*llm`。
   - 取最高分候选，若 `fused_score >= merge_threshold` → 合并（`is_new_entity=False, matched_entity_id=best.node_id, confidence=best.fused_score`）；否则 → 新建（`is_new_entity=True, confidence=1.0 - best.fused_score`）。
5. **实现 `_compute_vector_scores()`**：
   - 对每个候选，通过 SQLAlchemy `AsyncSession` 执行 pgvector HNSW 查询：`SELECT id, embedding <=> :query_vec AS distance FROM user_memory WHERE id = :candidate_node_id LIMIT 1`，取 `1 - distance` 作为 vector_score；异常时降级为 0.0。
6. **实现 `_compute_bm25_scores()`**：
   - 用 Neo4j `memoryFullText` 全文索引检索的 score 作为 BM25 主体。
   - 结合 Levenshtein 编辑距离：`raw_score = 1 - min(1, dist / max_len)`。
   - 编辑距离 < `edit_distance_threshold` 时额外 +0.2（封顶 1.0）。
   - 综合两者取加权或取 max（按 settings 配置）。
7. **实现 `_compute_llm_scores()`**：
   - 跳过 `0.5*vector + 0.5*bm25 < 0.6` 的候选（llm_score=0.0）。
   - 对剩余候选构造 prompt：`判断实体 A("new_name" -- new_summary) 与 实体 B("candidate.name") 是否同一实体，输出 JSON {"score": float, "reasoning": str}`。
   - 调 LLM，解析 JSON，clamp 到 [0, 1]；异常时降级为 0.0。
8. **实现 `_levenshtein_distance()`**：
   - 纯 Python 单行 DP 实现，时间复杂度 O(m*n)。
   - 不引入第三方库。

### 验收标准

- [ ] **新实体创建**：Neo4j 中无同类型候选时，返回 `is_new_entity=True, confidence=1.0`。
- [ ] **已有实体合并**：候选中存在高相似度实体（vector + bm25 都高分），LLM 判定同一，`fused_score >= merge_threshold`，返回 `is_new_entity=False, matched_entity_id=<已有节点ID>`。
- [ ] **三信号分歧决策**：vector 高分但 bm25 低分（如语义相似但名称不同），验证 LLM 判定起决定作用；三信号都低分时返回 `is_new_entity=True`。
- [ ] **LLM 调用裁剪**：低分候选（preliminary < 0.6）不触发 LLM 调用，llm_score=0.0。
- [ ] **Levenshtein 正确性**：`_levenshtein_distance("kitten", "sitting") == 3`，`_levenshtein_distance("same", "same") == 0`。
- [ ] **降级**：pgvector/LLM 异常时对应信号降级为 0.0，主流程不中断。
- [ ] **多用户隔离**：候选检索带 `user_id` 过滤，不跨用户合并。
- [ ] **单元测试文件**：`api/test/internal/service/memory/test_entity_resolution.py` 覆盖以上场景。

### 关联架构文档章节

- [01-data-models-and-write-path.md](../01-data-models-and-write-path.md) §2.4 TKG 实体消解

---

## A4：写入 API 端点

### 目标

新建统一的记忆写入 API 端点 `POST /memory/write`，供外部系统或调试工具直接写入记忆（绕过对话流程）。端点内部构建 `MemoryEvent`，调 `SalienceScorer.score()` 评分，根据 `WritePath` 调用 `LedgerWriter` 对应方法。

### 输入（前置依赖）

| 依赖项 | 来源 | 说明 |
|---|---|---|
| A1 `SalienceScorer` | 本 Track A1 | 评分 |
| A2 `LedgerWriter` | 本 Track A2 | 写入 |
| A3 `entity_resolution` | 本 Track A3 | 由 A2 内部调用 |
| `MemoryEvent` 模型 | Phase 0 / I6 | 事件构造 |
| Embedding 服务 | Phase 0 | 生成 content 向量 |
| LLM 实体/关系抽取 | 新增辅助（可复用旧 MemoryCandidateExtractor 的 LLM prompt） | FULL/SUMMARY 路径需要 |
| Flask 路由注册 | 现有 `api/internal/router/router.py` | 端点挂载 |

### 输出

**文件路径**：`api/internal/handler/memory_handler.py`（新建文件）

**关键类与函数签名**：

```python
# 请求/响应 Schema（Pydantic 或 marshmallow，按现有项目规范）
class MemoryWriteRequest(BaseModel):
    user_id: str
    content: str
    memory_type: str = "user_message"   # 对应 EventSource
    metadata: dict[str, Any] = {}
    tags: list[str] = []

class MemoryWriteResponse(BaseModel):
    memory_id: str          # episode_node_id 或 stats 更新计数
    status: str             # "full" | "summary" | "stats"
    created_at: datetime

# Handler
class MemoryHandler:
    def __init__(
        self,
        salience_scorer: SalienceScorer,
        ledger_writer: LedgerWriter,
        embedding_service,        # 生成 content embedding
        entity_extractor,         # LLM 抽取 entities + relations
        settings: Settings,
    ) -> None: ...

    async def write_memory(
        self, request: MemoryWriteRequest,
    ) -> MemoryWriteResponse: ...

# 路由注册（在 router.py 中）
# POST /memory/write  →  MemoryHandler.write_memory
```

### 实现步骤

1. **创建 handler 文件**：`api/internal/handler/memory_handler.py`。
2. **定义 `MemoryWriteRequest` / `MemoryWriteResponse` schema**：遵循项目现有 handler 规范（参考 `api/internal/handler/user_memory_handler.py` 与 `api/internal/schema/user_memory_schema.py`）。
3. **实现 `MemoryHandler.__init__`**：注入 `SalienceScorer`、`LedgerWriter`、embedding 服务、entity 抽取器、settings。
4. **实现 `write_memory()`**：
   - 用 request 字段构建 `MemoryEvent`（event_id 自动生成，timestamp=now，source=memory_type，content=request.content，metadata=request.metadata + {tags}，user_id=request.user_id）。
   - 调 `salience_scorer.score(event)` 得 `SalienceResult`。
   - 根据 `result.write_path`：
     - **FULL**：调 embedding_service 生成 content 向量；调 entity_extractor 抽取 entities + relations；调 `ledger_writer.write_full_path(event, entities, relations, embedding)`。
     - **SUMMARY**：调 LLM 生成 summary；调 embedding_service 生成 summary 向量；调 entity_extractor 抽取（精简）；调 `ledger_writer.write_summary_path(event, summary, entities[:5], relations[:5], embedding)`。
     - **STATS**：调 entity_extractor 仅抽取 entities（轻量）；调 `ledger_writer.write_stats_path(event, entities)`。
   - 组装 `MemoryWriteResponse(memory_id, status, created_at)` 返回。
5. **注册路由**：在 `api/internal/router/router.py` 中挂载 `POST /memory/write`，通过 `current_app.injector` 注入 MemoryHandler 依赖。
6. **依赖注入配置**：在 `api/app/module.py`（或对应 DI 配置）中绑定 `SalienceScorer`、`LedgerWriter`、`MemoryHandler` 的单例。

### 验收标准

- [ ] **FULL 路径**：POST 高 salience content（mock LLM 返回高分），验证响应 status="full"，Neo4j 有 Episode 节点 + Entity + 边，`user_memory` 表有向量行。
- [ ] **SUMMARY 路径**：POST 中等 salience content，验证 status="summary"，Neo4j Episode content 为摘要，实体数 ≤ 5。
- [ ] **STATS 路径**：POST 低 salience content，验证 status="stats"，Neo4j 无新 Episode，`user_memory` 表无新行，Entity.access_count 增加。
- [ ] **响应字段完整**：memory_id 非空，created_at 为当前时间。
- [ ] **错误处理**：Neo4j/pgvector 不可用时返回 503，并记 warning 日志（不 crash）。
- [ ] **API 测试文件**：`api/test/internal/handler/test_memory_handler.py` 覆盖三条路径。

### 关联架构文档章节

- [00-overview.md](./00-overview.md) §代码目录结构规划（memory_handler.py 定位）
- [01-data-models-and-write-path.md](../01-data-models-and-write-path.md) §2 写入路径

---

## A5：对话后自动触发集成

### 目标

将新写入路径集成到首页助手对话流程，替换旧的 `_extract_long_term_memory` 方法。对话结束后自动触发记忆写入，不再推送 SSE `MEMORY_CANDIDATE_PROMPT` 事件（旧系统的确认弹窗）。支持降级：当 `memory_engine_enabled=False` 或 Neo4j/pgvector 不可用时跳过写入。

### 输入（前置依赖）

| 依赖项 | 来源 | 说明 |
|---|---|---|
| A1 `SalienceScorer` | 本 Track A1 | |
| A2 `LedgerWriter` | 本 Track A2 | |
| A4 `MemoryWriteService` | 本 Track A4 | 复用 write 逻辑，封装为 `write_from_conversation()` |
| `Settings.memory_engine_enabled` | Phase 0 / I2 | 降级开关 |
| 现有 `assistant_agent_service.py` | 现有代码 | 第 397 行调用点 + 第 404-424 行待替换方法 |
| `QueueEvent` 枚举 | 现有代码 | 旧 `MEMORY_CANDIDATE_PROMPT` 事件（停止使用） |

### 输出

**修改文件**：

1. `api/internal/service/memory/memory_write_service.py`（新建）-- 封装 `MemoryWriteService.write_from_conversation()`
2. `api/internal/service/assistant_agent_service.py`（修改）-- 替换第 404-424 行

**关键类与函数签名**：

```python
# api/internal/service/memory/memory_write_service.py
class MemoryWriteService:
    def __init__(
        self,
        salience_scorer: SalienceScorer,
        ledger_writer: LedgerWriter,
        embedding_service,
        entity_extractor,
        summary_generator,       # LLM 摘要生成（SUMMARY 路径用）
        settings: Settings,
    ) -> None: ...

    async def write_from_conversation(
        self,
        account: Account,
        query: str,
        ai_response: str,
        conversation_id: str,
    ) -> Optional[dict[str, Any]]:
        """
        从对话内容构建 MemoryEvent 并写入。

        Returns:
            写入结果摘要；降级或失败时返回 None。
        """
        ...

# api/internal/service/assistant_agent_service.py（修改）
class AssistantAgentService:
    # 替换 _extract_long_term_memory 为：
    def _write_memory_from_conversation(self, account, query, ai_response, conversation_id):
        """对话后自动写入记忆，无需用户确认。降级时跳过。"""
        ...
```

### 实现步骤

1. **新建 `MemoryWriteService`**：`api/internal/service/memory/memory_write_service.py`。
   - `__init__` 注入 SalienceScorer、LedgerWriter、embedding_service、entity_extractor、summary_generator、settings。
   - 实现 `write_from_conversation(account, query, ai_response, conversation_id)`：
     - 构建 `MemoryEvent`：content = `f"User: {query}\nAssistant: {ai_response}"`，source=USER_MESSAGE，user_id=account.id，session_id=conversation_id，context_messages=[]（或从 conversation 历史取最近 N 条）。
     - 调 `salience_scorer.score(event)` 得 `SalienceResult`。
     - 根据 `write_path` 调用对应 `ledger_writer.write_*()`（逻辑同 A4，可复用 A4 的私有方法或抽公共函数）。
     - 返回写入结果摘要 dict。
     - 全程异常捕获，失败时记 warning 日志并返回 None（不影响主对话流）。
2. **修改 `assistant_agent_service.py`**：
   - 删除第 404-424 行的 `_extract_long_term_memory` 方法。
   - 新增 `_write_memory_from_conversation(self, account, query, ai_response, conversation_id)` 方法：
     - 检查 `settings.memory_engine_enabled`，若 False 则 `logger.warning("记忆引擎已禁用，跳过写入")` 并 return。
     - 通过 `current_app.injector.get(MemoryWriteService)` 获取服务实例。
     - 调 `await memory_write_service.write_from_conversation(...)`。
     - 异常时 `logger.warning("记忆写入失败，不影响主流程", exc_info=True)`。
   - 将第 397 行 `yield from self._extract_long_term_memory(...)` 改为 `yield from self._write_memory_from_conversation(...)`。
   - **注意**：新方法不再 yield SSE 事件（旧方法会 yield `MEMORY_CANDIDATE_PROMPT`）。若需保持 generator 签名兼容，方法可以是空 generator（`yield from ()`）或返回后 `return`。保持 generator 形式以最小化调用方改动。
3. **移除 SSE 事件**：
   - 确认不再 yield `QueueEvent.MEMORY_CANDIDATE_PROMPT` 事件。
   - 前端 `MemoryConfirmationCard.vue` 的清理归 Track F / Track G，本任务仅移除后端推送。
4. **依赖注入配置**：在 `api/app/module.py` 中绑定 `MemoryWriteService` 单例，注入其依赖（SalienceScorer、LedgerWriter 等）。
5. **降级路径验证**：
   - `memory_engine_enabled=False` → 跳过写入，仅 warning 日志。
   - Neo4j 不可用 → `LedgerWriter` 抛异常 → `MemoryWriteService` 捕获 → 返回 None → 主流程继续。
   - pgvector 不可用（PostgreSQL 向量检索不可用）→ 同上。

### 验收标准

- [ ] **自动写入**：完成一次对话后，Neo4j 中出现新 Episode 节点（FULL/SUMMARY）或 Entity.access_count 增加（STATS），`user_memory` 表有对应向量行（FULL/SUMMARY）。
- [ ] **无 SSE 候选事件**：对话 SSE 流中不再出现 `MEMORY_CANDIDATE_PROMPT` 事件，前端不弹确认框。
- [ ] **降级 - 引擎禁用**：`memory_engine_enabled=False` 时，对话正常完成，无记忆写入，日志含 warning。
- [ ] **降级 - Neo4j 不可用**：模拟 Neo4j 连接失败，对话正常完成，记忆写入静默失败，日志含 warning，无异常上抛。
- [ ] **降级 - pgvector 不可用（PostgreSQL 向量检索不可用）**：同上。
- [ ] **主流程不受影响**：记忆写入失败时，对话回答正常返回，billing 事件正常。
- [ ] **旧方法已删除**：`_extract_long_term_memory` 方法不再存在，`LongTermMemoryService` 不再被 `assistant_agent_service` 引用（旧 service 文件本身由 Track G 清理）。
- [ ] **集成测试文件**：`api/test/internal/service/test_assistant_agent_memory_integration.py` 覆盖正常写入 + 三种降级场景。

### 关联架构文档章节

- [01-data-models-and-write-path.md](../01-data-models-and-write-path.md) §旧系统替代说明
- [00-overview.md](./00-overview.md) §子代理委派策略（Agent-Write 负责 Track A）

---

## 验证命令

每个任务完成后执行以下验证：

```bash
# 后端类型检查
cd api && python -m py_compile internal/service/memory/salience_scorer.py internal/service/memory/ledger_writer.py internal/service/memory/entity_resolution.py internal/service/memory/memory_write_service.py internal/handler/memory_handler.py

# 后端单元测试（按任务）
cd api && python -m pytest test/internal/service/memory/test_salience_scorer.py -v
cd api && python -m pytest test/internal/service/memory/test_ledger_writer.py -v
cd api && python -m pytest test/internal/service/memory/test_entity_resolution.py -v
cd api && python -m pytest test/internal/handler/test_memory_handler.py -v
cd api && python -m pytest test/internal/service/test_assistant_agent_memory_integration.py -v

# 集成验证（A5 完成后）
cd api && python -m pytest test/internal/service/memory/ -v

# 容器健康检查
cd docker && docker compose ps
```

---

## 完成定义（Definition of Done）

Track A 全部完成的标志：

- [ ] A1-A5 五个任务的所有验收标准通过。
- [ ] `api/internal/service/memory/` 目录下含 `salience_scorer.py`、`ledger_writer.py`、`entity_resolution.py`、`memory_write_service.py` 四个文件。
- [ ] `api/internal/handler/memory_handler.py` 存在并注册路由 `POST /memory/write`。
- [ ] `assistant_agent_service.py` 中 `_extract_long_term_memory` 已被 `_write_memory_from_conversation` 替换，不再引用 `LongTermMemoryService`。
- [ ] 对话后记忆自动写入 Neo4j + pgvector，无 SSE 候选事件。
- [ ] 降级逻辑（引擎禁用 / Neo4j 不可用 / pgvector 不可用）全部验证通过。
- [ ] 所有单元测试与集成测试通过。
- [ ] Track B（检索）、Track C（巩固）可基于本 Track 产出的 LedgerWriter 与 entity_resolution 继续开发。
