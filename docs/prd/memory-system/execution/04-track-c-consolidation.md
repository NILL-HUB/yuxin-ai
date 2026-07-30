# Track C：巩固引擎 -- 任务执行文档

> **创建日期**：2026-07-09
> **Track**：C（巩固引擎，C1-C5）
> **关联架构**：[03-consolidation-skill-policy-api.md](../../03-consolidation-skill-policy-api.md) | [02-storage-and-retrieval.md](../../02-storage-and-retrieval.md) | [architecture-design.md Ch16](../../architecture-design.md) | [00-overview.md](./00-overview.md)
> **执行原则**：二开阶段，无生产数据，不做向后兼容，旧代码直接删除；Track C 任务在 Track A（写入路径）完成后启动（T2 时机），与 Track B 并行。
> **子代理**：Agent-Consolidate

---

## 0. 背景与依赖关系

### 0.1 背景

Track C 实现记忆系统的巩固引擎，灵感来自睡眠记忆巩固理论——睡眠期间海马体将日间经验转移到新皮层进行长期存储。该 Track 通过后台 Celery 定时任务执行五个阶段的记忆整理：

- **阶段 1**：Episodic → Semantic（情景记忆转语义记忆）
- **阶段 2**：Conflict Detection（冲突检测：矛盾/更新/互补）
- **阶段 3**：Weight Scan（权重扫描与层级迁移）
- **阶段 4**：Redundancy Merge（冗余合并）
- **阶段 5**：Stats Summary（统计摘要）

并实现表征排斥（RepresentationRepulsion）拉开过近向量距离，避免灾难性遗忘。Celery 定时任务每日凌晨 3 点全量巩固，每 6 小时权重扫描。

### 0.2 任务依赖与执行顺序

```
前置任务         →  可启动的 C 任务
─────────────────────────────────────
I6 完成          →  C1, C2, C3（数据模型统一）
A2 完成          →  C1（操作 Neo4j 边/节点）、C2（操作 SemanticMemory）
B1 完成          →  C1 阶段 3（调用 HebbianDecay.batch_update_weights）
C1 + C2          →  C4（Celery 任务调用 ConsolidationEngine）
C1 完成          →  C5（巩固 API 调用 run_consolidation）
```

| 任务 | 时机 | 类型 | 前置条件 |
|---|---|---|---|
| C1 | T2 | 新建文件 | I6, A2, B1 |
| C2 | T2 | 新建文件 | I6, A2 |
| C3 | T2 | 新建文件 | I6, A2 |
| C4 | T2 末 | 新建文件 | C1, C2 |
| C5 | T2 末 | 追加到 A4/B7 文件 | C1 |

### 0.3 与 Track B 的并行关系

Track C 与 Track B 在 T2 时段并行启动。两者共享 I6 统一数据模型与 A2 写入路径，但职责不同：

- Track B 负责**实时读写**（检索、Digest、漏斗压缩）
- Track C 负责**后台整理**（巩固、冲突解决、表征排斥、定时任务）

唯一交叉点：C1 阶段 3 调用 B1 的 `HebbianDecay.batch_update_weights`，因此 C1 需在 B1 完成后启动。

---

## C1：ConsolidationEngine（五阶段巩固引擎）

- **执行时机**：T2，I6 + A2 + B1 完成后
- **前置条件**：`ConsolidationConfig`、`ConsolidationReport`、`ConsolidationPhase` 模型在 I6 已定义；Neo4j Episode/SemanticMemory/MemoryNode 节点已建（I4）；pgvector `user_memory.embedding` 列与 HNSW 索引已建（I5）；HebbianDecay（B1）已实现；ConflictDetector（C2）已实现（阶段 2 委托）
- **类型**：新建文件

### 目标

实现五阶段巩固引擎，作为后台定时任务执行记忆整理。五个阶段顺序执行，单个阶段失败不影响后续阶段，最终返回完整的执行报告。灵感来自睡眠记忆巩固理论——睡眠期间海马体将日间经验转移到新皮层进行长期存储。

### 输入

- Neo4j 异步驱动、SQLAlchemy `AsyncSession`（pgvector 向量检索）、LLM 客户端
- `ConsolidationConfig` 配置（episode_age_days=7, semantic_min_examples=3, semantic_similarity_threshold=0.8, conflict_check_batch_size=50, conflict_similarity_threshold=0.85, cold_threshold=0.3, merge_similarity_threshold=0.9, llm_model, llm_temperature）
- 用户 ID `user_id`

### 输出

- **文件路径**：`api/internal/service/memory/consolidation_engine.py`
- **关键类/函数签名**：

```python
class ConsolidationEngine:
    def __init__(
        self,
        neo4j: AsyncDriver,
        db_session: AsyncSession,
        llm_client: AsyncOpenAI,
        config: Optional[ConsolidationConfig] = None,
    ) -> None: ...

    async def run_consolidation(self, user_id: str) -> ConsolidationReport:
        """
        执行完整的五阶段巩固流程。
        按顺序执行每个阶段，单个阶段失败不影响后续阶段。
        返回包含 phase_results 与 errors 的 ConsolidationReport。
        """

    async def _phase1_episodic_to_semantic(self, user_id: str) -> dict:
        """
        阶段 1：7 天以上 Episode → LLM 提取共性 → 创建 SemanticMemory 节点 + IS_ABSTRACTION_OF 边。
        返回 {"count": int, "semantics_created": int}。
        """

    async def _phase2_conflict_detection(self, user_id: str) -> dict:
        """
        阶段 2：调用 ConflictDetector.detect(user_id)。
        返回 {"count", "contradictions", "updates", "complements"}。
        """

    async def _phase3_weight_scan(self, user_id: str) -> dict:
        """
        阶段 3：调用 HebbianDecay.batch_update_weights + tier 降级。
        返回 {"edges_scanned": int, "tier_migrations": {"HOT", "WARM", "COLD"}}。
        """

    async def _phase4_redundancy_merge(self, user_id: str) -> dict:
        """
        阶段 4：相似度 > 0.9 的节点合并（创建 MERGED_INTO 边）。
        返回 {"count": int, "merged": int}。
        """

    async def _phase5_stats_summary(self, user_id: str) -> dict:
        """
        阶段 5：更新统计计数器。
        返回 {"total_nodes", "total_edges", "tier_distribution"}。
        """
```

### 实现步骤

1. 在 `api/internal/service/memory/consolidation_engine.py` 新建文件，导入 I6 的 `ConsolidationConfig`/`ConsolidationReport`/`ConsolidationPhase`，B1 的 `HebbianDecay`/`DecayConfig`/`MemoryEdge`，C2 的 `ConflictDetector`
2. 实现 `__init__`，保存 neo4j、db_session、llm、config（默认 `ConsolidationConfig()`）
3. 实现 `run_consolidation(user_id)`：
   - 创建 `ConsolidationReport(user_id=user_id)`
   - 定义阶段列表 `[("episodic_to_semantic", _phase1), ("conflict_detection", _phase2), ("weight_scan", _phase3), ("redundancy_merge", _phase4), ("stats_summary", _phase5)]`
   - 顺序执行每个阶段，try/except 包裹，失败时将错误追加到 `report.errors` 并继续下一阶段
   - 每阶段结果存入 `report.phase_results[phase_name]`
   - 设置 `report.completed_at`，返回 report
4. 实现 `_phase1_episodic_to_semantic(user_id)`：
   - Cypher 查找 `storage_tier='HOT'` 且 `duration.between(date(e.created_at), date()).days >= episode_age_days` 的 Episode
   - 对每个 Episode 用 pgvector 搜索相似 Episode 簇（`ORDER BY embedding <=> :query_vec`，相似度 >= `semantic_similarity_threshold`）
   - 簇内数量 >= `semantic_min_examples` 时，调 LLM 提取共性语义
   - 创建 `SemanticMemory` 节点 + `IS_ABSTRACTION_OF` 边连接簇内 Episode
   - 标记已处理 Episode 避免重复
5. 实现 `_phase2_conflict_detection(user_id)`：
   - 实例化 `ConflictDetector(self._neo4j, self._llm, self._config)`
   - 调用 `detector.detect(user_id)` 返回结果
6. 实现 `_phase3_weight_scan(user_id)`：
   - Cypher 读取用户所有边，构造 `MemoryEdge` 列表
   - 实例化 `HebbianDecay(DecayConfig())`，调用 `batch_update_weights(edges, self._neo4j)`
   - 返回 `{"edges_scanned", "tier_migrations": {"HOT", "WARM", "COLD"}}`
7. 实现 `_phase4_redundancy_merge(user_id)`：
   - Cypher 查询 HOT 层 MemoryNode
   - 对每个节点用 pgvector 搜索相似度 >= `merge_similarity_threshold`（0.9）的其他节点（`ORDER BY embedding <=> :query_vec`）
   - 保留分数最高的为主节点，其余标记 `status='merged'` + `merged_to=primary_id` + 创建 `MERGED_INTO` 边
8. 实现 `_phase5_stats_summary(user_id)`：
   - Cypher 统计用户总节点数、总边数、各 tier 分布
   - 返回 `{"total_nodes", "total_edges", "tier_distribution"}`
9. 编写单元测试 `api/test/internal/service/memory/test_consolidation_engine.py`，mock Neo4j/pgvector/LLM/HebbianDecay/ConflictDetector

### 验收标准

- 五阶段顺序执行：phase_results 包含全部 5 个阶段的结果
- 单阶段失败不阻断后续：某阶段抛异常时记录到 errors，后续阶段仍执行
- 阶段 1：能从 7 天以上 Episode 簇提取 SemanticMemory 并建立 IS_ABSTRACTION_OF 边
- 阶段 2：正确委托 ConflictDetector.detect
- 阶段 3：正确调用 HebbianDecay.batch_update_weights 并返回 tier_migrations
- 阶段 4：相似度 > 0.9 的节点合并，创建 MERGED_INTO 边
- 阶段 5：返回正确的节点/边/tier 统计
- `ConsolidationReport.is_success` 在无错误时为 True，`total_items_processed` 正确汇总
- 单元测试通过：`cd api && python -m pytest test/internal/service/memory/test_consolidation_engine.py -v`

### 关联架构文档章节

- [03-consolidation-skill-policy-api.md §7.1 ConsolidationEngine 完整 Python 实现](../../03-consolidation-skill-policy-api.md)
- [03-consolidation-skill-policy-api.md §7 巩固引擎（五阶段流程）](../../03-consolidation-skill-policy-api.md)
- [architecture-design.md §16.2 脑启发架构映射（睡眠巩固）](../../architecture-design.md)

---

## C2：ConflictDetector（冲突检测器）

- **执行时机**：T2，I6 + A2 完成后
- **前置条件**：`ConflictType`、`ConflictResult`、`ConsolidationConfig` 模型在 I6 已定义；Neo4j SemanticMemory 节点已建（I4）；LLM 客户端可用
- **类型**：新建文件

### 目标

实现记忆冲突检测器，使用 LLM 判定记忆对之间的关系（CONTRADICTION/UPDATE/COMPLEMENT），并根据判定结果执行相应解决操作。批量检测（batch_size=50），相似度 > 0.85 的对调 LLM 判定，置信度 > 0.7 才执行解决。

### 输入

- Neo4j 异步驱动、LLM 客户端
- `ConsolidationConfig` 配置（conflict_check_batch_size=50, conflict_similarity_threshold=0.85, llm_model, llm_temperature）
- 用户 ID `user_id`

### 输出

- **文件路径**：`api/internal/service/memory/conflict_detector.py`
- **关键类/函数签名**：

```python
class ConflictDetector:
    def __init__(
        self,
        neo4j: AsyncDriver,
        llm_client: AsyncOpenAI,
        config: ConsolidationConfig,
    ) -> None: ...

    async def detect(self, user_id: str) -> dict:
        """
        批量检测用户的所有潜在冲突记忆对（batch_size=50）。
        相似度 > 0.85 的对调 LLM 判定。
        返回 {"count", "contradictions", "updates", "complements"}。
        """

    async def _detect_pair(
        self,
        a_id: str,
        a_content: str,
        b_id: str,
        b_content: str,
        a_ts,
        b_ts,
    ) -> Optional[ConflictResult]:
        """
        LLM 返回 CONTRADICTION/UPDATE/COMPLEMENT。
        置信度 < 0.7 返回 None（不处理）。
        """

    async def _resolve_conflict(self, conflict: ConflictResult) -> None:
        """
        根据冲突类型执行解决操作：
        - CONTRADICTION → 旧节点 t_invalidated_at=now
        - UPDATE → 旧节点 t_invalidated_at + 新节点 SUPERSEDED_BY 旧节点
        - COMPLEMENT → 创建 COMPLEMENTARY 边
        LLM 置信度 > 0.7 才执行解决。
        """
```

### 实现步骤

1. 在 `api/internal/service/memory/conflict_detector.py` 新建文件，导入 I6 的 `ConflictType`/`ConflictResult`/`ConsolidationConfig` 与 `CONFLICT_DETECTION_PROMPT` 模板
2. 实现 `__init__`，保存 neo4j、llm、config
3. 实现 `detect(user_id)`：
   - Cypher 查询用户的热 SemanticMemory 对（`a.id < b.id`，`storage_tier='HOT' OR IS NULL`），`LIMIT $batch_size`（默认 50）
   - 初始化 stats `{"count": 0, "contradictions": 0, "updates": 0, "complements": 0}`
   - 对每对调用 `_detect_pair`，返回 None 则 continue
   - 调用 `_resolve_conflict(conflict)` 执行解决
   - 根据 `conflict.conflict_type` 累加对应计数
   - 返回 stats
4. 实现 `_detect_pair(a_id, a_content, b_id, b_content, a_ts, b_ts)`：
   - 用 `CONFLICT_DETECTION_PROMPT.format(memory_a=a_content[:500], memory_b=b_content[:500])` 渲染 prompt
   - 调 LLM `chat.completions.create(model, messages, temperature=0, max_tokens=200, response_format={"type": "json_object"})`
   - 解析 JSON，取 `type`/`confidence`/`explanation`
   - `confidence < 0.7` 返回 None
   - 构造 `ConflictResult(memory_a_id, memory_b_id, conflict_type, confidence, resolution=explanation)` 返回
   - 异常时记录 warning 并返回 None
5. 实现 `_resolve_conflict(conflict)`：
   - **CONTRADICTION**：Cypher 找到较旧节点（`a.created_at < b.created_at`），SET `status='deprecated'`, `deprecated_reason`, `deprecated_at=datetime()`，旧节点 `t_invalidated_at=now`
   - **UPDATE**：旧节点 SET `status='superseded'`, `superseded_by=newer.id`, `t_invalidated_at=now` + 创建 `(older)-[:SUPERSEDED_BY]->(newer)` 边
   - **COMPLEMENT**：创建双向 `(a)-[:COMPLEMENTARY {confidence}]->(b)` 与 `(b)-[:COMPLEMENTARY]->(a)` 边
6. 编写单元测试 `api/test/internal/service/memory/test_conflict_detector.py`，mock Neo4j/LLM

### 验收标准

- 三种冲突类型的解决：
  - CONTRADICTION：旧节点被标记 `t_invalidated_at` 与 `deprecated`
  - UPDATE：旧节点 `t_invalidated_at` + 创建 `SUPERSEDED_BY` 边
  - COMPLEMENT：创建双向 `COMPLEMENTARY` 边
- 置信度过滤：`confidence < 0.7` 的判定不执行解决（`_detect_pair` 返回 None）
- 批量检测：`batch_size=50` 限制每批处理的记忆对数
- LLM 异常时跳过该对（不阻断整体检测）
- stats 计数正确（contradictions + updates + complements <= count）
- 单元测试通过：`cd api && python -m pytest test/internal/service/memory/test_conflict_detector.py -v`

### 关联架构文档章节

- [03-consolidation-skill-policy-api.md §7.2 ConflictDetector 完整 Python 实现](../../03-consolidation-skill-policy-api.md)
- [03-consolidation-skill-policy-api.md §7 巩固引擎（阶段 2 冲突检测）](../../03-consolidation-skill-policy-api.md)

---

## C3：RepresentationRepulsion（表征排斥）

- **执行时机**：T2，I6 + A2 完成后
- **前置条件**：Neo4j MemoryNode 节点已建（I4）；pgvector `user_memory.embedding` 列与 HNSW 索引已建（I5）；`numpy` 依赖可用
- **类型**：新建文件

### 目标

实现表征排斥，对语义过近但实际不同的记忆拉开嵌入距离，避免灾难性遗忘。灵感来自神经科学的反向重播（reverse replay）——在学习新记忆时，系统会"反向重播"相关记忆以区分新旧表征。当两条记忆的向量余弦相似度超过阈值时，在嵌入空间中沿连线方向将两者推开。

### 输入

- Neo4j 异步驱动、SQLAlchemy `AsyncSession`（pgvector 向量操作）
- pgvector 表名（默认 `user_memory`）、向量列名（默认 `embedding`）
- 用户 ID `user_id`
- 相似度阈值 `threshold`（默认 0.95）
- 排斥力度 `gamma`（默认 0.1）

### 输出

- **文件路径**：`api/internal/service/memory/representation_repulsion.py`
- **关键类/函数签名**：

```python
class RepresentationRepulsion:
    def __init__(
        self,
        neo4j: AsyncDriver,
        db_session: AsyncSession,
        table_name: str = "user_memory",
        embedding_column: str = "embedding",
    ) -> None: ...

    async def repulse(
        self,
        user_id: str,
        threshold: float = 0.95,
        gamma: float = 0.1,
    ) -> dict:
        """
        找到余弦相似度 > 0.95 的向量对，沿排斥方向微调（gamma=0.1）。
        步骤：
        1. 通过 SQLAlchemy `AsyncSession` 查询 `user_memory` 表该用户全部向量行（含 id 与 embedding 列）
        2. 对每对计算余弦相似度，超过 threshold 的标记
        3. 沿连线方向各推 gamma/2 距离，归一化后批量 UPDATE `user_memory.embedding`
        返回 {"scanned": int, "repulsed_pairs": int}。
        """
```

### 实现步骤

1. 在 `api/internal/service/memory/representation_repulsion.py` 新建文件，导入 `numpy`、`neo4j.AsyncDriver`、`sqlalchemy.ext.asyncio.AsyncSession`、pgvector 类型
2. 实现 `__init__`，保存 neo4j、db_session、table_name、embedding_column
3. 实现 `repulse(user_id, threshold=0.95, gamma=0.1)`：
   - 通过 `AsyncSession` 执行 `SELECT id, embedding FROM user_memory WHERE user_id = :user_id` 获取该用户全部向量行
   - 空列表返回 `{"scanned": 0, "repulsed_pairs": 0}`
   - 构造 `point_map = {row.id: row.embedding}`，`point_ids = list(point_map.keys())`
   - 双重循环遍历所有点对 `(i, j)`，`i < j`：
     - 用 numpy 计算余弦相似度 `cos_sim = dot(a, b) / (norm(a) * norm(b) + 1e-10)`
     - `cos_sim < threshold` 跳过
     - 计算排斥方向 `direction = vec_a - vec_b`，归一化 `norm_dir = direction / (norm(direction) + 1e-10)`
     - `new_a = vec_a + norm_dir * (gamma / 2)`，`new_b = vec_b - norm_dir * (gamma / 2)`
     - 归一化 `new_a` / `new_b` 到单位长度
     - 追加到 `updates` 列表，`repulsed_pairs += 1`
   - 若 `updates` 非空，通过 `AsyncSession` 批量 `UPDATE user_memory SET embedding = :vec WHERE id = :id`（用 `executemany` 或循环执行）
   - 返回 `{"scanned": len(points), "repulsed_pairs": repulsed_pairs}`
4. 编写单元测试 `api/test/internal/service/memory/test_representation_repulsion.py`，mock pgvector/Neo4j

### 验收标准

- 相似向量被拉开：余弦相似度 > 0.95 的向量对经过排斥后距离增大
- 排斥力度：`gamma=0.1` 时各向量沿连线方向移动 `gamma/2 = 0.05` 距离
- 归一化：更新后的向量保持单位长度
- 阈值过滤：相似度 < 0.95 的对不被排斥
- 空用户：查询返回空时返回 `{"scanned": 0, "repulsed_pairs": 0}`
- 单元测试通过：`cd api && python -m pytest test/internal/service/memory/test_representation_repulsion.py -v`

### 关联架构文档章节

- [03-consolidation-skill-policy-api.md §7.3 RepresentationRepulsion 完整 Python 实现](../../03-consolidation-skill-policy-api.md)
- [architecture-design.md §16.2 脑启发架构映射（反向重播）](../../architecture-design.md)

---

## C4：Celery 定时任务

- **执行时机**：T2 末，C1 + C2 完成后
- **前置条件**：ConsolidationEngine（C1）已实现；Celery 在 I1 基础设施中已部署；HebbianDecay（B1）已实现（用于 `run_weight_scan`）；项目已有 Celery 扩展（`api/internal/extension/celery_extension.py`）
- **类型**：新建文件

### 目标

实现巩固引擎的 Celery 定时任务，每日凌晨 3 点执行全量巩固，每 6 小时执行权重扫描。提供错误重试机制，确保任务失败时自动重试，不丢失数据。

### 输入

- Celery app 实例（来自 `api/internal/extension/celery_extension.py`）
- 用户 ID 列表 `user_ids`（可选，None 表示扫描所有活跃用户）
- 单用户 ID `user_id`（用于权重扫描任务）

### 输出

- **文件路径**：`api/internal/task/consolidation_tasks.py`
- **关键类/函数签名**：

```python
# celery_app 来自 api/internal/extension/celery_extension.py

@celery_app.task(bind=True, max_retries=2, default_retry_delay=300)
def run_daily_consolidation(self, user_ids: list[str] | None = None) -> dict:
    """
    Celery 任务：对指定用户或所有活跃用户执行全量巩固。
    max_retries=2, default_retry_delay=300s（5 分钟）。
    遍历所有用户执行 ConsolidationEngine.run_consolidation。
    返回 {user_id: {"success": bool, "items": int}} 执行摘要。
    """

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def run_weight_scan(self, user_id: str) -> dict:
    """
    Celery 任务：单用户权重扫描。
    max_retries=3, default_retry_delay=60s（1 分钟）。
    执行 HebbianDecay.batch_update_weights，返回阶段 3 结果。
    """

# Celery beat 定时配置
celery_app.conf.beat_schedule = {
    "daily-consolidation": {
        "task": "internal.task.consolidation_tasks.run_daily_consolidation",
        "schedule": crontab(hour=3, minute=0),  # 每天凌晨 3 点
        "args": [],
    },
    "weight-scan": {
        "task": "internal.task.consolidation_tasks.run_weight_scan",
        "schedule": crontab(hour="*/6", minute=30),  # 每 6 小时
        "args": [],
    },
}
celery_app.conf.task_routes = {
    "internal.task.consolidation_tasks.*": {"queue": "consolidation"},
}
```

### 实现步骤

1. 在 `api/internal/task/consolidation_tasks.py` 新建文件，导入项目已有的 `celery_app`（来自 `api/internal/extension/celery_extension.py`）、`celery.schedules.crontab`
2. 实现 `run_daily_consolidation(self, user_ids=None)`：
   - 装饰器 `@celery_app.task(bind=True, max_retries=2, default_retry_delay=300)`
   - 在任务内部初始化 `ConsolidationEngine`（注入 Neo4j/pgvector/LLM 客户端，可延迟导入避免循环依赖）
   - `user_ids is None` 时查询所有活跃用户（Cypher `MATCH (u:User) WHERE u.last_active_at >= datetime() - duration({days: 30}) RETURN u.id`）
   - 遍历 `user_ids`，对每个调用 `engine.run_consolidation(uid)`
   - 累计结果到 `results[uid] = {"success": report.is_success, "items": report.total_items_processed}`
   - 异常时记录 `results[uid] = {"success": False, "error": str(e)}`
   - 整体异常时调用 `self.retry(exc=exc)` 触发重试（受 `max_retries=2` 限制）
   - 返回 results
3. 实现 `run_weight_scan(self, user_id)`：
   - 装饰器 `@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)`
   - 初始化 `ConsolidationEngine`，调用 `engine.run_consolidation(user_id)`
   - 仅取阶段 3 结果：`report.phase_results.get("weight_scan", {})`
   - 异常时 `self.retry(exc=exc)` 触发重试（受 `max_retries=3` 限制）
   - 返回阶段 3 结果
4. 配置 `celery_app.conf.beat_schedule`：
   - `daily-consolidation`：`crontab(hour=3, minute=0)`，每天凌晨 3 点
   - `weight-scan`：`crontab(hour="*/6", minute=30)`，每 6 小时
5. 配置 `celery_app.conf.task_routes`：将巩固任务路由到 `consolidation` 队列
6. 编写单元测试 `api/test/internal/task/test_consolidation_tasks.py`，mock Celery app 与 ConsolidationEngine

### 验收标准

- Celery beat 触发任务：`daily-consolidation` 在每天 3:00 触发，`weight-scan` 每 6 小时触发
- `run_daily_consolidation` 遍历所有用户执行 `run_consolidation`，返回每个用户的成功状态与处理条目数
- `run_weight_scan` 仅返回阶段 3（weight_scan）结果
- 重试机制：
  - `run_daily_consolidation`：`max_retries=2`, `default_retry_delay=300s`
  - `run_weight_scan`：`max_retries=3`, `default_retry_delay=60s`
- 任务路由：巩固任务被路由到 `consolidation` 队列
- `user_ids=None` 时正确查询所有活跃用户
- 单元测试通过：`cd api && python -m pytest test/internal/task/test_consolidation_tasks.py -v`

### 关联架构文档章节

- [03-consolidation-skill-policy-api.md §7.1 Celery 任务定义](../../03-consolidation-skill-policy-api.md)
- [03-consolidation-skill-policy-api.md §7 巩固引擎（定时任务）](../../03-consolidation-skill-policy-api.md)
- [02-storage-and-retrieval.md §降级策略（Celery 没跑时的降级行为）](../../02-storage-and-retrieval.md)

---

## C5：巩固 API

- **执行时机**：T2 末，C1 完成后
- **前置条件**：ConsolidationEngine（C1）已实现；A4/B7 已创建 `memory_handler.py` 文件并注册了 `/memory/write`、`/memory/retrieve`、`/memory/digest` 端点
- **类型**：追加到 A4/B7 创建的文件

### 目标

在统一 memory handler 中追加巩固 API 端点，对外暴露手动触发巩固的能力。支持同步等待（直接返回 ConsolidationReport）或异步触发（返回 task_id 由 Celery 后台执行）两种模式。

### 输入

- 用户 ID（path 参数）
- 模式选择 `async_mode`（query 参数，可选，默认 False 同步）
- `ConsolidationResponse` schema

### 输出

- **文件路径**：`api/internal/handler/memory_handler.py`（追加到 A4/B7 创建的文件）
- **关键类/函数签名**：

```python
@router.post("/memory/consolidate/{user_id}", response_model=ConsolidationResponse)
async def consolidate_memory(
    user_id: str,
    async_mode: bool = Query(default=False, description="true 返回 task_id 异步执行"),
) -> ConsolidationResponse:
    """
    POST /memory/consolidate/{user_id}
    手动触发用户的记忆巩固流程（五阶段）。
    - async_mode=False：同步等待 run_consolidation 完成，返回完整报告
    - async_mode=True：返回 task_id，由 Celery 后台执行
    请求：无 body → 响应：ConsolidationResponse
    """
```

### 实现步骤

1. 在 `api/internal/handler/memory_handler.py`（A4/B7 已创建）追加导入 `ConsolidationResponse` schema（来自 I6 或 A4 schema 文件）
2. 在 handler 模块顶部注入 `ConsolidationEngine` 单例（通过依赖注入或模块级初始化）
3. 实现 `POST /memory/consolidate/{user_id}`：
   - `async_mode=False`（默认同步）：
     - 调用 `engine.run_consolidation(user_id)` 同步等待
     - 构造 `ConsolidationResponse(user_id=user_id, success=report.is_success, total_items=report.total_items_processed, phase_results=report.phase_results, errors=report.errors)`
   - `async_mode=True`（异步）：
     - 调用 `run_daily_consolidation.delay([user_id])` 提交 Celery 任务
     - 返回 `ConsolidationResponse(user_id=user_id, success=True, total_items=0, errors=[], phase_results={"task_id": task.id})`
4. 在 router 注册端点（确保与 A4/B7 的 `/memory/write`、`/memory/retrieve`、`/memory/digest` 端点不冲突）
5. 编写 API 测试 `api/test/internal/handler/test_memory_handler.py`（追加 consolidate 用例）

### 验收标准

- `POST /memory/consolidate/{user_id}` 接受请求返回 `ConsolidationResponse`，含 success/total_items/phase_results/errors
- `async_mode=False`（默认）：同步等待 `run_consolidation` 完成，返回完整报告
- `async_mode=True`：返回 task_id，由 Celery 后台执行
- 端点在 router 中正确注册，可通过 FastAPI TestClient 调用
- API 测试通过：`cd api && python -m pytest test/internal/handler/test_memory_handler.py -v`

### 关联架构文档章节

- [03-consolidation-skill-policy-api.md §10 API 接口定义（/memory/consolidate）](../../03-consolidation-skill-policy-api.md)
- [03-consolidation-skill-policy-api.md §10.1 FastAPI 路由定义（consolidate_memory）](../../03-consolidation-skill-policy-api.md)

---

## 附录：Track C 验证命令汇总

每个任务完成后执行以下验证：

```bash
# 后端类型检查（所有 C 任务新建/修改的文件）
cd api && python -m py_compile internal/service/memory/consolidation_engine.py \
  internal/service/memory/conflict_detector.py \
  internal/service/memory/representation_repulsion.py \
  internal/task/consolidation_tasks.py \
  internal/handler/memory_handler.py

# 后端单元测试（Track C 全部）
cd api && python -m pytest test/internal/service/memory/test_consolidation_engine.py -v
cd api && python -m pytest test/internal/service/memory/test_conflict_detector.py -v
cd api && python -m pytest test/internal/service/memory/test_representation_repulsion.py -v
cd api && python -m pytest test/internal/task/test_consolidation_tasks.py -v
cd api && python -m pytest test/internal/handler/test_memory_handler.py -v

# Celery beat 配置验证（检查定时任务注册）
cd api && python -c "from internal.task.consolidation_tasks import celery_app; print(celery_app.conf.beat_schedule)"

# 容器健康检查（依赖 Neo4j/PostgreSQL pgvector/Redis/Celery）
cd docker && docker compose ps
```

---

## 附录：Track C 文件清单

| 任务 | 文件路径 | 类型 |
|---|---|---|
| C1 | `api/internal/service/memory/consolidation_engine.py` | 新建 |
| C1 | `api/test/internal/service/memory/test_consolidation_engine.py` | 新建测试 |
| C2 | `api/internal/service/memory/conflict_detector.py` | 新建 |
| C2 | `api/test/internal/service/memory/test_conflict_detector.py` | 新建测试 |
| C3 | `api/internal/service/memory/representation_repulsion.py` | 新建 |
| C3 | `api/test/internal/service/memory/test_representation_repulsion.py` | 新建测试 |
| C4 | `api/internal/task/consolidation_tasks.py` | 新建 |
| C4 | `api/test/internal/task/test_consolidation_tasks.py` | 新建测试 |
| C5 | `api/internal/handler/memory_handler.py` | 追加（A4/B7 创建） |
| C5 | `api/test/internal/handler/test_memory_handler.py` | 追加测试 |

---

## 附录：五阶段巩固流程图

```
run_consolidation(user_id)
        │
        ▼
┌──────────────────────────────────────────────────┐
│ 阶段 1: Episodic → Semantic                      │
│   7 天以上 Episode → LLM 提取共性                │
│   → 创建 SemanticMemory + IS_ABSTRACTION_OF 边   │
└──────────────────┬───────────────────────────────┘
                   │ (失败不阻断)
                   ▼
┌──────────────────────────────────────────────────┐
│ 阶段 2: Conflict Detection                       │
│   调用 ConflictDetector.detect                   │
│   CONTRADICTION / UPDATE / COMPLEMENT 解决       │
└──────────────────┬───────────────────────────────┘
                   │ (失败不阻断)
                   ▼
┌──────────────────────────────────────────────────┐
│ 阶段 3: Weight Scan                              │
│   调用 HebbianDecay.batch_update_weights         │
│   → tier 降级（HOT→WARM→COLD）                   │
└──────────────────┬───────────────────────────────┘
                   │ (失败不阻断)
                   ▼
┌──────────────────────────────────────────────────┐
│ 阶段 4: Redundancy Merge                         │
│   相似度 > 0.9 的节点合并                        │
│   → 创建 MERGED_INTO 边                          │
└──────────────────┬───────────────────────────────┘
                   │ (失败不阻断)
                   ▼
┌──────────────────────────────────────────────────┐
│ 阶段 5: Stats Summary                            │
│   更新统计计数器（节点/边/tier 分布）            │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
            ConsolidationReport
            (phase_results + errors)
```

---

## 附录：Celery 定时任务调度

```
时间轴（UTC）
─────────────────────────────────────────────────
00:00  03:00  06:30  09:00  12:30  15:00  18:30  21:00
 │      │      │      │      │      │      │      │
 │      ▼      │      │      │      │      │      │
 │  daily-     │      │      │      │      │      │
 │  consolid.  │      │      │      │      │      │
 │             ▼      │      ▼      │      ▼      │
 │         weight-   │   weight-   │   weight-   │
 │          scan     │    scan     │    scan     │
 │                ▼      │      ▼      │      ▼   │
 │            weight-  │   weight-   │   weight-  │
 │             scan    │    scan     │    scan    │
 │                   ...                       ...

daily-consolidation: crontab(hour=3, minute=0)        # 每天凌晨 3 点
weight-scan:         crontab(hour="*/6", minute=30)   # 每 6 小时（00:30, 06:30, 12:30, 18:30）
```

---

> Track C 文档结束。共 5 个任务（C1-C5），覆盖五阶段巩固引擎、冲突检测器、表征排斥、Celery 定时任务与巩固 API。
