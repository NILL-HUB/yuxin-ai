# Track B：存储与检索 -- 任务执行文档

> **创建日期**：2026-07-09
> **Track**：B（存储与检索，B1-B8）
> **关联架构**：[02-storage-and-retrieval.md](../../02-storage-and-retrieval.md) | [architecture-design.md Ch16](../../architecture-design.md) | [00-overview.md](./00-overview.md)
> **执行原则**：二开阶段，无生产数据，不做向后兼容，旧代码直接删除；Track B 任务在 Track A（写入路径）完成后启动（T2 时机）。
> **子代理**：Agent-Retrieve

---

## 0. 背景与依赖关系

### 0.1 背景

Track B 实现记忆系统的存储分级、读取路径、漏斗压缩与 Memory Digest。该 Track 替代旧系统的 `recall_relevant_memories`（pgvector 单路向量检索）与 `token_buffer_memory.get_relevant_facts`（实时检索 500 tokens），升级为：

- **存储分级**：四级存储分层（L0 Redis / L1 Neo4j+pgvector 热 / L2 温 / L3 S3 冷），由 HebbianDecay 计算权重决定层级迁移
- **混合检索**：System 1（Digest 缓存快速路径）+ System 2（TKG 图遍历 + pgvector 向量 + SpreadActivation 图扩展 + 混合评分 + 早停）
- **漏斗压缩**：五层漏斗将大量召回结果压缩为可注入的结构化摘要
- **Memory Digest**：用户记忆快照摘要，由 Neo4j 重建 + Redis 缓存（≤2K tokens），注入对话 system prompt

### 0.2 任务依赖与执行顺序

```
前置任务         →  可启动的 B 任务
─────────────────────────────────────
I6 完成          →  B1, B2, B3, B4, B5, B6（数据模型统一）
A2 完成          →  B1（HebbianDecay 操作 Neo4j 边）、B3（TKG 粗召回依赖 Neo4j 全文索引）
A3 完成          →  B3（检索结果与 entity_resolution 数据一致）
B3 + B4 + B5     →  B7（检索 API 依赖三个组件）
B6 完成          →  B8（ResultSynthesizer 集成 DigestManager）
```

| 任务 | 时机 | 类型 | 前置条件 |
|---|---|---|---|
| B1 | T2 | 新建文件 | I6, A2 |
| B2 | T2 | 新建文件 | I6 |
| B3 | T2 | 新建文件 | I6, A2, A3 |
| B4 | T2 | 新建文件 | I6, A2 |
| B5 | T2 | 新建文件 | I6 |
| B6 | T2 | 新建文件 | I6, A2 |
| B7 | T2 末 | 追加到 A4 文件 | B3, B4, B5, B6 |
| B8 | T2 末 | 改代码 | B6 |

---

## B1：HebbianDecay（赫布权重衰减器）

- **执行时机**：T2，I6 与 A2 完成后
- **前置条件**：统一数据模型（`MemoryEdge`、`StorageTier`）已在 I6 定义；Neo4j schema（I4）中 MemoryNode/MemoryEdge 已建索引
- **类型**：新建文件

### 目标

实现赫布权重衰减器，根据时间衰减、共现增强、干扰惩罚动态计算边的综合权重，并据此决定存储层级（HOT/WARM/COLD）。支撑记忆系统的自然遗忘与层级迁移机制。

### 输入

- `DecayConfig` 配置（lambda_decay, alpha_cooccurrence, beta_interference, hot_threshold, warm_threshold 等）
- `MemoryEdge` 列表（含 base_weight, last_accessed_at, cooccurrence_count, interference_count 等字段）
- Neo4j 异步驱动（用于批量写回权重与 tier）
- 当前时间 `now`（可选，默认 UTC 当前时刻）

### 输出

- **文件路径**：`api/internal/service/memory/hebbian_decay.py`
- **关键类/函数签名**：

```python
class HebbianDecay:
    def __init__(self, config: DecayConfig) -> None: ...

    def compute_weight(self, edge: MemoryEdge, now: Optional[datetime] = None) -> float:
        """
        计算边的当前综合权重。
        公式：weight = base_weight * exp(-lambda * Δt) + alpha * cooccurrence_count - beta * interference_count
        其中 Δt 为自 last_accessed_at 起的天数。
        """

    def determine_tier(self, weight: float) -> StorageTier:
        """
        根据权重判定存储层级。
        规则：weight > 0.7 → HOT；weight > 0.3 → WARM；else → COLD。
        """

    async def batch_update_weights(
        self,
        edges: list[MemoryEdge],
        neo4j_driver: AsyncDriver,
        batch_size: int = 500,
    ) -> dict[StorageTier, int]:
        """
        批量更新 Neo4j 边权重和节点 tier。
        按 batch_size 分组，对每批执行 UNWIND Cypher 批量 SET。
        返回各层级迁移计数 {StorageTier.HOT: n, StorageTier.WARM: m, StorageTier.COLD: k}。
        """
```

### 实现步骤

1. 在 `api/internal/service/memory/hebbian_decay.py` 新建文件，导入 I6 提供的 `MemoryEdge`、`StorageTier`、`DecayConfig` 数据模型
2. 实现 `HebbianDecay.__init__(config)`，保存配置
3. 实现 `compute_weight(edge, now=None)`：
   - 若 `now` 为 None，使用 `datetime.now(timezone.utc)`
   - 计算 `Δt = (now - edge.last_accessed_at).total_seconds() / 86400.0`（天数）
   - 计算时间衰减因子 `exp(-lambda_decay * Δt)`
   - 应用公式 `weight = base_weight * exp(-lambda * Δt) + alpha * cooccurrence_count - beta * interference_count`
   - 将结果裁剪到 `[0.0, 1.0]` 区间
4. 实现 `determine_tier(weight)`：
   - `weight > 0.7` → `StorageTier.HOT`
   - `weight > 0.3` → `StorageTier.WARM`
   - 其他 → `StorageTier.COLD`
   - 阈值从 `config.hot_threshold` / `config.warm_threshold` 读取
5. 实现 `batch_update_weights(edges, neo4j_driver, batch_size=500)`：
   - 按 `batch_size` 分批迭代 `edges`
   - 对每条边调用 `compute_weight` 计算新权重，调用 `determine_tier` 决定层级
   - 累计 tier 计数到返回字典
   - 构造 `updates` 列表，执行 Cypher `UNWIND $updates AS u ... SET r.weight = u.weight, r.storage_tier = u.tier, r.last_accessed_at = ...`
   - 在 `async with neo4j_driver.session() as session:` 中执行批量写入
6. 编写单元测试 `api/test/internal/service/memory/test_hebbian_decay.py`，覆盖公式、tier 判定、批量更新

### 验收标准

- `compute_weight` 公式实现与规格一致：`base_weight * exp(-lambda * Δt) + alpha * cooccurrence_count - beta * interference_count`
- `determine_tier` 在边界值（0.7, 0.3, 0.0）正确切换 HOT/WARM/COLD
- `batch_update_weights` 能处理空列表（返回全 0 计数）、单条、多条（>batch_size 触发分批）
- 单元测试通过：`cd api && python -m pytest test/internal/service/memory/test_hebbian_decay.py -v`
- 类型检查通过：`cd api && python -m py_compile internal/service/memory/hebbian_decay.py`

### 关联架构文档章节

- [02-storage-and-retrieval.md §5.1 四级存储分层](../../02-storage-and-retrieval.md)
- [02-storage-and-retrieval.md §5.2 HebbianDecay 完整 Python 实现](../../02-storage-and-retrieval.md)
- [architecture-design.md §16.2 脑启发架构映射](../../architecture-design.md)

---

## B2：ColdStorageManager（冷存储管理）

- **执行时机**：T2，I6 完成后
- **前置条件**：`ColdStorageEntry` 数据模型在 I6 已定义；MinIO/S3 兼容存储在 I3 基础设施中已部署
- **类型**：新建文件

### 目标

实现冷存储管理器，管理 L3 冷记忆的 S3 归档与 Key 重建。提供三种冷存储激活策略：全量遍历恢复、从值重建 Key、统计挖掘潜在模式，支撑冷记忆的回热与挖掘能力。

### 输入

- S3 桶名 `s3_bucket`、键前缀 `s3_prefix`（默认 `cold-memories/`）
- Neo4j 异步驱动（可选，用于恢复时回写）
- AWS 区域 `aws_region`（默认 `us-east-1`）
- `ColdStorageEntry` 归档条目
- 用户 ID、年份、阈值权重、最小支持度等查询参数

### 输出

- **文件路径**：`api/internal/service/memory/cold_storage_manager.py`
- **关键类/函数签名**：

```python
class ColdStorageManager:
    def __init__(
        self,
        s3_bucket: str,
        s3_prefix: str = "cold-memories/",
        neo4j_driver: Optional[AsyncDriver] = None,
        aws_region: str = "us-east-1",
    ) -> None: ...

    async def archive(self, entry: ColdStorageEntry) -> str:
        """将冷记忆条目写入 S3 归档（gzip 压缩 JSON）。返回 S3 对象键。"""

    async def read_archive(self, s3_key: str) -> Optional[ColdStorageEntry]:
        """从 S3 读取并解压冷记忆条目。对象不存在返回 None。"""

    async def list_user_archives(
        self, user_id: str, year: Optional[int] = None
    ) -> list[str]:
        """列出用户的所有冷归档 S3 键，可按年份限定。"""

    async def global_traverse(
        self, user_id: str, threshold_weight: float = 0.5
    ) -> RebuildResult:
        """策略 1：全量遍历冷存储，将权重回升的条目恢复到 Neo4j 热层。"""

    async def rebuild_key_from_value(self, entry: ColdStorageEntry) -> Optional[str]:
        """策略 2：从值内容重建 Key（主题/关键词提取）。"""

    async def statistical_mining(
        self, user_id: str, min_support: int = 3
    ) -> list[dict]:
        """策略 3：统计挖掘冷存储中的潜在技能模式。"""

    async def _restore_to_neo4j(self, entry: ColdStorageEntry) -> None:
        """将冷条目恢复到 Neo4j 热层（storage_tier=HOT）。"""
```

### 实现步骤

1. 在 `api/internal/service/memory/cold_storage_manager.py` 新建文件，导入 I6 的 `ColdStorageEntry`、`RebuildResult` 模型
2. 使用 `boto3` 或 `minio-py` 客户端（MinIO S3 兼容 API），在 `__init__` 中初始化 S3 client
3. 实现 `archive(entry)`：
   - 构造 S3 键路径 `{prefix}{user_id}/{year}/{month:02d}/{memory_id}.json.gz`
   - 用 `gzip.compress` 压缩 `entry.model_dump_json()` 编码字节
   - `put_object` 写入 S3，返回键
4. 实现 `read_archive(s3_key)`：
   - `get_object` 读取，`gzip.decompress` 解压，`ColdStorageEntry.model_validate_json` 解析
   - 捕获 `ClientError`，`NoSuchKey` 返回 None，其他异常上抛
5. 实现 `list_user_archives(user_id, year=None)`：
   - 构造前缀，用 `get_paginator("list_objects_v2")` 分页收集所有键
6. 实现 `global_traverse(user_id, threshold_weight)`：
   - 调用 `list_user_archives` 获取全部键
   - 逐个 `read_archive`，计算恢复潜力分（`original_weight + metadata.cooccurrence_count * 0.05`）
   - 超过阈值的调用 `_restore_to_neo4j`
   - 累计 `RebuildResult.total_scanned` / `rebuilt_keys` / `errors`
7. 实现 `rebuild_key_from_value(entry)`：
   - 取 `entry.content[:500]`，正则提取英文词，过滤停用词
   - 用 `Counter.most_common(3)` 取 Top-3 关键词，以 `|` 连接返回
8. 实现 `statistical_mining(user_id, min_support)`：
   - 遍历所有冷归档，对每个条目调用 `rebuild_key_from_value` 得到主题 Key
   - 统计每个 Key 的出现次数，按 `min_support` 过滤
   - 返回 `[{"pattern": ..., "count": ..., "keys": [...]}]` 按次数降序
9. 实现 `_restore_to_neo4j(entry)`：
   - 若 `neo4j_driver` 为 None 直接返回
   - 执行 `MERGE (n:MemoryNode {id: $id}) SET n.content=..., n.weight=..., n.storage_tier='HOT', n.restored_at=datetime()`
10. 编写单元测试 `api/test/internal/service/memory/test_cold_storage_manager.py`，mock S3 client 与 Neo4j driver

### 验收标准

- `archive` 写入的 S3 对象能被 `read_archive` 正确读回（gzip 解压 + JSON 反序列化）
- `read_archive` 对不存在的键返回 None（不抛异常）
- `list_user_archives` 支持按年份过滤，分页正确
- `global_traverse` 仅恢复潜力分超过阈值的条目，并调用 `_restore_to_neo4j`
- `rebuild_key_from_value` 对空内容返回 None，对正常内容返回 `|` 连接的关键词串
- `statistical_mining` 按 `min_support` 过滤并按 count 降序排列
- 单元测试通过：`cd api && python -m pytest test/internal/service/memory/test_cold_storage_manager.py -v`

### 关联架构文档章节

- [02-storage-and-retrieval.md §5.3 冷存储与 Key 重建](../../02-storage-and-retrieval.md)
- [02-storage-and-retrieval.md §5.1 四级存储分层（L3 冷记忆）](../../02-storage-and-retrieval.md)
- [architecture-design.md §16.2 脑启发架构映射](../../architecture-design.md)

---

## B3：MemoryRetriever（混合检索器 System 1/2 双路）

- **执行时机**：T2，I6 + A2 + A3 完成后
- **前置条件**：`RetrievalConfig`、`RetrievalOptions`、`RetrievalResult` 模型在 I6 已定义；Neo4j 全文索引 `memoryFullText`（I4）已建；pgvector `user_memory.embedding` 列与 HNSW 索引（I5）已建；SpreadActivation（B4）已实现（用于 `_graph_spread`）
- **类型**：新建文件

### 目标

实现混合检索器，融合语义/关键词/图三通道，实现 System 1（Digest 缓存快速路径）与 System 2（TKG 粗召回 + 向量精召回 + 图扩展 + 混合评分 + 早停）的双路架构。完全替代旧系统的 `recall_relevant_memories`。

### 输入

- Neo4j 异步驱动、SQLAlchemy `AsyncSession`（pgvector 向量检索）
- `RetrievalConfig` 配置（w_cosine, w_bm25, w_graph, time_decay_half_life_hours, early_stop_top_k, early_stop_score_gap, embedding_dim）
- LLM 客户端（可选，用于查询嵌入）
- 查询文本 `query`、用户 ID `user_id`、`RetrievalOptions`（top_k, time_range_days, view_names, require_evidence, budget_tokens）

### 输出

- **文件路径**：`api/internal/service/memory/retriever.py`
- **关键类/函数签名**：

```python
class MemoryRetriever:
    def __init__(
        self,
        neo4j: AsyncDriver,
        db_session: AsyncSession,
        config: RetrievalConfig,
        llm_client: Optional[AsyncOpenAI] = None,
    ) -> None: ...

    async def retrieve(
        self,
        query: str,
        user_id: str,
        options: Optional[RetrievalOptions] = None,
    ) -> list[RetrievalResult]:
        """主检索入口，先尝试 System 1 快速路径，未命中则走 System 2 深度搜索。"""

    async def _system1_fast_path(self, query: str, user_id: str) -> Optional[str]:
        """检查 Digest 缓存是否足够，足够则直接返回。"""

    async def _system2_deep_search(
        self, query: str, user_id: str, options: RetrievalOptions
    ) -> list[RetrievalResult]:
        """TKG 粗召回 + 向量精召回 + 图扩展 + 混合评分 + 早停。"""

    async def _tkg_recall(
        self, query: str, user_id: str, top_k: int
    ) -> list[RetrievalResult]:
        """Neo4j 全文索引 BM25 粗召回。"""

    async def _vector_recall(
        self, query_embedding: list[float], user_id: str, top_k: int
    ) -> list[RetrievalResult]:
        """pgvector 向量检索精召回（HNSW 索引 + `<=>` 余弦距离）。"""

    async def _graph_spread(
        self, start_ids: list[str], top_k: int = 20
    ) -> list[tuple[str, float]]:
        """调用 SpreadActivation 进行图扩展。"""

    def _hybrid_score(
        self, result: RetrievalResult, query_embed: list[float], query_text: str
    ) -> float:
        """混合评分：w_cosine * semantic + w_bm25 * keyword + w_graph * graph。"""

    def _time_decay(self, timestamp: datetime, now: Optional[datetime] = None) -> float:
        """时间衰减：exp(-ln2 * Δt / half_life)，Δt 以小时计。"""

    def _apply_early_stop(
        self, scored: list[RetrievalResult], top_k: int
    ) -> list[RetrievalResult]:
        """top_k + score_gap 判断，触发早停则截断。"""
```

### 实现步骤

1. 在 `api/internal/service/memory/retriever.py` 新建文件，导入 I6 的 `RetrievalConfig`/`RetrievalOptions`/`RetrievalResult` 模型与 B4 的 `SpreadActivation`/`SpreadConfig`
2. 实现 `__init__`，保存 neo4j、db_session、config、llm_client
3. 实现 `retrieve(query, user_id, options=None)`：
   - `options` 为 None 时使用 `RetrievalOptions()` 默认值
   - 调用 `_system1_fast_path`，命中则返回 `[RetrievalResult(memory_id="digest", content=fast_result, score=1.0, source="digest_cache")]`
   - 未命中调用 `_system2_deep_search` 返回
4. 实现 `_system1_fast_path`：
   - 通过 DigestManager 获取 Digest 缓存（生产中注入 `self._digest_manager`）
   - 缓存存在且未过期则返回 Digest 文本，否则返回 None
   - 本任务实现可简化为返回 None，由 B6/B8 完成后注入真实 DigestManager
5. 实现 `_system2_deep_search`：
   - ① 调用 `_tkg_recall(query, user_id, options.top_k * 2)` 收集 BM25 候选到 `all_candidates` dict（key=memory_id）
   - ② `_embed_query(query)` 得到查询向量，调用 `_vector_recall(query_embed, user_id, options.top_k * 2)`，与已有候选合并（同 id 取最大分，标记 source="hybrid"）
   - ③ 取前 5 个候选 id 作为 `start_ids`，调用 `_graph_spread(start_ids, top_k=options.top_k)`，新增节点加入候选（score = activation * 0.8, source="graph_spread"）
   - ④ 对每个候选调用 `_get_node_data` 补全内容/时间戳/元数据，计算 `hybrid = _hybrid_score(result, query_embed, query)`，再乘 `_time_decay(result.timestamp)` 得到最终 score
   - ⑤ 按 score 降序排序，调用 `_apply_early_stop(scored, options.top_k)` 截断，返回前 `top_k` 条
6. 实现 `_tkg_recall`：
   - Cypher `CALL db.index.fulltext.queryNodes("memoryFullText", $query) YIELD node, score WHERE node.user_id = $user_id AND (node.storage_tier IS NULL OR node.storage_tier IN ['HOT','WARM']) ...`
   - 返回 `RetrievalResult(source="bm25")` 列表
7. 实现 `_vector_recall`：
   - 通过 SQLAlchemy `AsyncSession` 执行 pgvector HNSW 查询：`SELECT id, content, metadata, embedding <=> :query_vec AS distance FROM user_memory WHERE user_id = :user_id ORDER BY embedding <=> :query_vec LIMIT :top_k`
   - 取 `1 - distance` 作为 score，构造 `RetrievalResult(source="semantic")` 列表
8. 实现 `_graph_spread`：实例化 `SpreadActivation(self._neo4j, SpreadConfig())`，调用 `activate(start_ids, top_k)`
9. 实现 `_hybrid_score`：
   - 根据 `result.source` 分配通道分数（semantic→cos, bm25→bm25, graph_spread/graph→graph, hybrid→三者同值）
   - 缺失通道权重重分配到其余通道
   - 返回归一化到 `[0,1]` 的混合分数
10. 实现 `_time_decay(timestamp, now=None)`：
    - `Δt` 以小时计，`decay = 0.5 ** (Δt / half_life)`，即 `exp(-ln2 * Δt / half_life)`
    - 保留最低 0.01 防完全消失
11. 实现 `_apply_early_stop(scored, top_k)`：
    - 若 `len(scored) <= top_k` 直接返回
    - 检查 `cutoff` 处与前一处的分数差是否 > `early_stop_score_gap`，是则截断到 cutoff
12. 编写单元测试 `api/test/internal/service/memory/test_retriever.py`，mock Neo4j/pgvector/LLM

### 验收标准

- System 1 命中 Digest 缓存时直接返回，不触发 System 2
- System 2 多路召回：TKG + 向量 + 图扩展结果正确合并（同 id 取最大分，source="hybrid"）
- `_hybrid_score` 缺失通道权重重分配正确
- `_time_decay` 半衰期生效（half_life=168h 时 7 天前记忆衰减约 0.5）
- `_apply_early_stop` 在分差超过阈值时提前截断
- 单元测试通过：`cd api && python -m pytest test/internal/service/memory/test_retriever.py -v`

### 关联架构文档章节

- [02-storage-and-retrieval.md §6.1 总流程图（System 1/2 双系统）](../../02-storage-and-retrieval.md)
- [02-storage-and-retrieval.md §6.2 MemoryRetriever 完整 Python 实现](../../02-storage-and-retrieval.md)
- [architecture-design.md §16.4 System 1 / System 2 双系统架构](../../architecture-design.md)

---

## B4：SpreadActivation（图扩展激活）

- **执行时机**：T2，I6 + A2 完成后
- **前置条件**：`SpreadConfig` 模型在 I6 已定义；Neo4j MemoryNode 与边关系已建（I4）；B3 在 `_graph_spread` 中调用本组件
- **类型**：新建文件

### 目标

实现图扩展激活，从起始节点沿边扩展发现间接关联，每跳衰减激活值。灵感来自认知科学扩散激活理论（Collins & Loftus, 1975）。提供 Cypher 多跳遍历与迭代回退两种实现，保证 APOC 不可用时仍可工作。

### 输入

- Neo4j 异步驱动
- `SpreadConfig` 配置（max_hops=3, activation_decay=0.5, min_activation=0.01, edge_weight_multiplier=1.0, top_k=20）
- 起始节点 ID 列表 `start_nodes`、返回最大数 `top_k`

### 输出

- **文件路径**：`api/internal/service/memory/spread_activation.py`
- **关键类/函数签名**：

```python
class SpreadActivation:
    def __init__(
        self,
        neo4j_driver: AsyncDriver,
        config: Optional[SpreadConfig] = None,
    ) -> None: ...

    async def activate(
        self, start_nodes: list[str], top_k: int = 20
    ) -> list[tuple[str, float]]:
        """
        从起始节点沿边扩展，返回激活值排序的 (node_id, activation) 列表。
        多跳遍历：从 start_nodes 出发，沿边扩展，每跳衰减 activation_decay。
        """

    async def _fallback_iterative(
        self, start_nodes: list[str], top_k: int
    ) -> list[tuple[str, float]]:
        """Neo4j APOC 不可用时，用迭代遍历替代。"""
```

### 实现步骤

1. 在 `api/internal/service/memory/spread_activation.py` 新建文件，导入 I6 的 `SpreadConfig`
2. 实现 `__init__`，保存 driver 与 config（默认 `SpreadConfig()`）
3. 实现 `activate(start_nodes, top_k=20)`：
   - `top_k = min(top_k, cfg.top_k)`
   - 为每跳生成独立 MATCH-WITH 阶段，第 1 跳从 `start_nodes` 出发，第 N 跳从前一跳结果出发
   - 每跳衰减因子 `decay = cfg.activation_decay ** hop`
   - 用 `UNION ALL` 合并各跳结果，外层 `WITH node_id, sum(activation) AS total_activation WHERE total_activation >= $min_activation RETURN ... ORDER BY activation DESC LIMIT $top_k`
   - Cypher 失败时捕获异常，调用 `_fallback_iterative`
4. 实现 `_fallback_iterative(start_nodes, top_k)`：
   - 初始化 `current_frontier = [(nid, 1.0) for nid in start_nodes]`，`visited = set(start_nodes)`
   - 逐跳循环（最多 `max_hops`）：
     - 对 frontier 中每个节点查询出边 `(src)-[r]->(tgt) WHERE NOT tgt.id IN $visited`
     - 计算 `act = base_act * edge_w * decay`，低于 `min_activation` 跳过
     - 多路径激活取最大值，更新 `activations` dict
     - 新节点加入 `next_frontier` 与 `visited`
   - frontier 为空时提前 break
   - 按 activation 降序排序，返回前 `top_k`
5. 编写单元测试 `api/test/internal/service/memory/test_spread_activation.py`，mock Neo4j driver

### 验收标准

- 3 跳扩展：能从起始节点扩展到 3 跳外的关联节点
- 衰减正确：第 N 跳激活值 = 前跳激活 × 边权重 × `activation_decay ** N`
- `min_activation` 过滤：低于阈值的节点不返回
- Cypher 失败时正确回退到 `_fallback_iterative`，结果一致
- 单元测试通过：`cd api && python -m pytest test/internal/service/memory/test_spread_activation.py -v`

### 关联架构文档章节

- [02-storage-and-retrieval.md §6.3 SpreadActivation 完整 Python 实现](../../02-storage-and-retrieval.md)
- [architecture-design.md §16.4 System 1 / System 2 双系统架构（System 2 图扩展）](../../architecture-design.md)

---

## B5：FunnelCompressor（五层漏斗压缩）

- **执行时机**：T2，I6 完成后
- **前置条件**：`FunnelConfig`、`EvidenceItem` 模型在 I6 已定义；`RetrievalResult`（B3）已实现；LLM 客户端可用
- **类型**：新建文件

### 目标

实现五层漏斗压缩，将大量召回结果通过 RAW → DEDUP → SCORED → EVIDENCE → COMPRESSED → FINAL 五层处理，压缩为可注入的结构化摘要。在 Early Stop 条件满足时跳过 LLM 调用以节省成本。

### 输入

- LLM 客户端（OpenAI 异步）
- `FunnelConfig` 配置（dedup_similarity_threshold=0.85, evidence_max_items=30, early_stop_confidence=0.9, early_stop_min_items=3, llm_model, compression_prompt_template 等）
- 候选 `RetrievalResult` 列表
- 输出 token 预算 `budget_tokens`（默认 2000）

### 输出

- **文件路径**：`api/internal/service/memory/funnel_compressor.py`
- **关键类/函数签名**：

```python
class FunnelCompressor:
    def __init__(
        self,
        llm_client: AsyncOpenAI,
        config: Optional[FunnelConfig] = None,
    ) -> None: ...

    async def compress(
        self, candidates: list[RetrievalResult], budget_tokens: int = 2000
    ) -> str:
        """主压缩入口，五层漏斗压缩为结构化摘要。"""

    def _deduplicate(self, candidates: list[RetrievalResult]) -> list[RetrievalResult]:
        """Layer 1：相似度 > 0.85 去重。"""

    def _re_score(self, candidates: list[RetrievalResult]) -> list[RetrievalResult]:
        """Layer 2：综合原始分数与时间新鲜度重排序。"""

    async def _evidence_accumulation(
        self, candidates: list[RetrievalResult]
    ) -> list[EvidenceItem]:
        """Layer 3：候选转证据条目，限制最大数量。"""

    def _check_early_stop(self, evidence: list[EvidenceItem]) -> bool:
        """Layer 3-4：置信度 > 0.9 且条目数 > 3 时触发早停。"""

    async def _llm_compress(
        self, evidence: list[EvidenceItem], budget_tokens: int
    ) -> str:
        """Layer 4：LLM 压缩到 budget_tokens。"""
```

### 实现步骤

1. 在 `api/internal/service/memory/funnel_compressor.py` 新建文件，导入 I6 的 `FunnelConfig`、`EvidenceItem` 与 B3 的 `RetrievalResult`
2. 实现 `__init__`，保存 llm_client 与 config（默认 `FunnelConfig()`）
3. 实现 `compress(candidates, budget_tokens=2000)`：
   - 空列表返回空字符串
   - Layer 0→1：`_deduplicate(candidates)`
   - Layer 1→2：`_re_score(deduped)`
   - Layer 2→3：`await _evidence_accumulation(scored)`，空则返回 ""
   - 检查 `_check_early_stop(evidence)`，触发则返回 `_format_evidence(evidence[:early_stop_min_items])`
   - Layer 3→4：`await _llm_compress(evidence, budget_tokens)` 返回
4. 实现 `_deduplicate(candidates)`：
   - 维护 `kept` 与 `seen_contents`
   - 对每个候选与 seen 计算文本相似度（Jaccard 集合交并比），>= 阈值则跳过
   - 否则加入 kept 与 seen_contents
5. 实现 `_re_score(candidates)`：
   - 对每个候选计算 `hours_age`，`freshness = 0.99 ** hours_age`
   - `c.score = c.score * (0.7 + 0.3 * freshness)`
   - 按 score 降序排序
6. 实现 `_evidence_accumulation(candidates)`：
   - 取前 `evidence_max_items` 个，转为 `EvidenceItem(content, score, source, timestamp, memory_id)` 列表
7. 实现 `_check_early_stop(evidence)`：
   - 条目数 <= `early_stop_min_items` 返回 True
   - Top-1 分数 >= `early_stop_confidence` 且条目数 <= `2 * early_stop_min_items` 返回 True
   - 否则 False
8. 实现 `_llm_compress(evidence, budget_tokens)`：
   - 拼接证据文本 `[source|score] content[:300]`
   - 用 `compression_prompt_template.format(budget=..., evidence=...)` 渲染 prompt
   - 调 LLM `chat.completions.create(model, messages, temperature=0, max_tokens)`
   - 异常时回退 `_format_evidence(evidence[:10])`
9. 编写单元测试 `api/test/internal/service/memory/test_funnel_compressor.py`，mock LLM

### 验收标准

- 去重：相似度 >= 0.85 的候选被合并（保留先出现者）
- 早停：置信度 > 0.9 且条目数 > 3 时跳过 LLM 调用，直接返回格式化证据
- LLM 压缩：正常调用返回 LLM 输出；LLM 异常时回退为格式化证据文本
- 空候选输入返回空字符串
- 单元测试通过：`cd api && python -m pytest test/internal/service/memory/test_funnel_compressor.py -v`

### 关联架构文档章节

- [02-storage-and-retrieval.md §6.4 FunnelCompressor 完整 Python 实现](../../02-storage-and-retrieval.md)
- [02-storage-and-retrieval.md §6.1 总流程图（漏斗压缩环节）](../../02-storage-and-retrieval.md)
- [architecture-design.md §16.4 System 1 / System 2 双系统架构](../../architecture-design.md)

---

## B6：DigestManager（Memory Digest 管理器）

- **执行时机**：T2，I6 + A2 完成后
- **前置条件**：`DigestConfig` 模型在 I6 已定义；Neo4j User/Skill/Episode/Task 节点已建（I4）；Redis 在 I1 已部署；LLM 客户端可用
- **类型**：新建文件

### 目标

实现 Memory Digest 管理器，维护固定大小（≤2K tokens）的用户记忆摘要视图，由 Neo4j 重建 + Redis 缓存。Digest 包含用户画像、已习得技能、近期事件、待办任务四部分，作为 System 1 快速路径与对话 system prompt 注入的数据源。

### 输入

- Redis 异步客户端、Neo4j 异步驱动、LLM 客户端
- `DigestConfig` 配置（cache_ttl_seconds=300, cache_key_prefix="memory:digest:", max_tokens=2000, profile_max_items=5, skills_max_items=10, events_max_items=10, tasks_max_items=5, render_model, render_temperature）
- 用户 ID `user_id`

### 输出

- **文件路径**：`api/internal/service/memory/digest_manager.py`
- **关键类/函数签名**：

```python
class DigestManager:
    def __init__(
        self,
        redis: aioredis.Redis,
        neo4j: AsyncDriver,
        llm_client: AsyncOpenAI,
        config: Optional[DigestConfig] = None,
    ) -> None: ...

    async def get_digest(self, user_id: str) -> str:
        """先查 Redis 缓存，miss 则调用 update_digest 重建。"""

    async def update_digest(self, user_id: str) -> str:
        """从 Neo4j 查 4 部分 → _render_digest → 写 Redis。"""

    async def _fetch_profile(self, user_id: str) -> str:
        """查用户画像实体（User + Trait + Preference）。"""

    async def _fetch_skills(self, user_id: str) -> str:
        """查活跃技能（Skill status='active'）。"""

    async def _fetch_recent_episodes(self, user_id: str) -> str:
        """查近期事件（Episode storage_tier IN ['HOT','WARM']）。"""

    async def _fetch_tasks(self, user_id: str) -> str:
        """查任务状态（Task status='pending'）。"""

    async def _render_digest(
        self, profile: str, skills: str, events: str, tasks: str
    ) -> str:
        """LLM 渲染为 ~2K tokens 结构化文本。"""
```

### 实现步骤

1. 在 `api/internal/service/memory/digest_manager.py` 新建文件，导入 I6 的 `DigestConfig`、`DIGEST_TEMPLATE`，redis.asyncio、neo4j.AsyncDriver、openai.AsyncOpenAI
2. 实现 `__init__`，保存 redis、neo4j、llm、config（默认 `DigestConfig()`）
3. 实现 `get_digest(user_id)`：
   - 构造 cache_key = `f"{cache_key_prefix}{user_id}"`（即 `memory:digest:{user_id}`）
   - `redis.get(cache_key)`，命中则 `json.loads` 取 `text` 返回
   - miss 则调用 `update_digest(user_id)`，异常时返回 ""
4. 实现 `update_digest(user_id)`：
   - 依次调用 `_fetch_profile` / `_fetch_skills` / `_fetch_recent_episodes` / `_fetch_tasks`
   - 调用 `_render_digest(profile, skills, events, tasks)` 渲染
   - 用 tiktoken 计数（无 tiktoken 时按 1.5 中文字符 / 4 英文字符估算）
   - 超过 `max_tokens` 时按段截断（优先保留画像与技能）
   - 写 Redis：`redis.set(cache_key, json.dumps({"text", "tokens", "updated_at"}), ex=cache_ttl_seconds)`
   - TTL=300s
5. 实现 `_fetch_profile(user_id)`：
   - Cypher `MATCH (u:User {id: $user_id}) OPTIONAL MATCH (u)-[:HAS_TRAIT]->(t:Trait) OPTIONAL MATCH (u)-[:HAS_PREFERENCE]->(p:Preference) RETURN ...`
   - 无数据返回 "暂无用户画像数据"
   - 否则格式化为 "姓名: ..., 特质: ..., 偏好: ..."
6. 实现 `_fetch_skills(user_id)`：
   - Cypher `MATCH (s:Skill)-[:BELONGS_TO]->(u:User {id: $user_id}) WHERE s.status='active' RETURN ... ORDER BY s.maturity DESC LIMIT $limit`
   - 格式化为 "- {name} (成熟度: {maturity}, 使用: {use_count}次)" 列表
7. 实现 `_fetch_recent_episodes(user_id)`：
   - Cypher `MATCH (e:Episode)-[:BELONGS_TO]->(u:User {id: $user_id}) WHERE e.storage_tier IN ['HOT','WARM'] OR e.storage_tier IS NULL RETURN ... ORDER BY e.created_at DESC LIMIT $limit`
   - 格式化为 "- [MM-DD HH:MM] content[:100]" 列表
8. 实现 `_fetch_tasks(user_id)`：
   - Cypher `MATCH (t:Task)-[:ASSIGNED_TO]->(u:User {id: $user_id}) WHERE t.status='pending' RETURN ... ORDER BY t.due_date ASC NULLS LAST LIMIT $limit`
   - 格式化为 "- content[:80] (截止: MM-DD)" 列表
9. 实现 `_render_digest(profile, skills, events, tasks)`：
   - 用 `DIGEST_TEMPLATE.format(profile=, skills=, events=, tasks=)` 渲染
   - 可选：调用 LLM 进一步精炼为结构化文本（控制在 2K tokens）
10. 编写单元测试 `api/test/internal/service/memory/test_digest_manager.py`，mock Redis/Neo4j/LLM

### 验收标准

- 缓存命中：Redis 中存在未过期 Digest 时直接返回，不触发 Neo4j 查询
- 缓存 miss：触发 `update_digest`，从 Neo4j 拉取 4 部分数据并渲染
- Redis key 格式正确：`memory:digest:{user_id}`，TTL=300s
- 4 部分 Cypher 查询分别命中 User/Skill/Episode/Task 节点
- 渲染结果超过 `max_tokens` 时按段截断
- 单元测试通过：`cd api && python -m pytest test/internal/service/memory/test_digest_manager.py -v`

### 关联架构文档章节

- [02-storage-and-retrieval.md §6.5 DigestManager 完整 Python 实现](../../02-storage-and-retrieval.md)
- [02-storage-and-retrieval.md §5.1 四级存储分层（L0 Redis 工作缓冲）](../../02-storage-and-retrieval.md)
- [architecture-design.md §16.4 System 1 / System 2 双系统架构（System 1 Digest）](../../architecture-design.md)

---

## B7：检索 API + Digest API

- **执行时机**：T2 末，B3 + B4 + B5 + B6 完成后
- **前置条件**：MemoryRetriever（B3）、FunnelCompressor（B5）、DigestManager（B6）已实现；A4 已创建 `memory_handler.py` 文件
- **类型**：追加到 A4 创建的文件

### 目标

在统一 memory handler 中追加检索与 Digest 两个 API 端点，对外暴露 System 1/2 双路检索能力与 Digest 查询能力。替代旧系统的 `/user/memory` 列表查询。

### 输入

- `MemoryRetrieveRequest`（query, user_id, top_k, time_range_days, budget_tokens, views）
- 用户 ID（path 参数）
- 强制刷新标志 `refresh`（query 参数，可选）

### 输出

- **文件路径**：`api/internal/handler/memory_handler.py`（追加到 A4 创建的文件）
- **关键类/函数签名**：

```python
@router.post("/memory/retrieve", response_model=MemoryRetrieveResponse)
async def retrieve_memory(request: MemoryRetrieveRequest) -> MemoryRetrieveResponse:
    """
    POST /memory/retrieve
    请求：MemoryRetrieveRequest → 响应：MemoryRetrieveResponse
    内部调用 MemoryRetriever.retrieve，并可选调用 FunnelCompressor 压缩。
    """

@router.get("/memory/digest/{user_id}")
async def get_digest(
    user_id: str, refresh: bool = Query(default=False)
) -> dict:
    """
    GET /memory/digest/{user_id}
    refresh=True 时强制调用 DigestManager.update_digest，否则 get_digest。
    返回 {"user_id", "digest", "cached"}。
    """
```

### 实现步骤

1. 在 `api/internal/handler/memory_handler.py`（A4 已创建）追加导入 `MemoryRetrieveRequest`/`MemoryRetrieveResponse` schema（来自 I6 或 A4 schema 文件）
2. 在 handler 模块顶部注入 `MemoryRetriever`、`DigestManager` 单例（通过依赖注入或模块级初始化）
3. 实现 `POST /memory/retrieve`：
   - 记录开始时间 `start = time.monotonic()`
   - 构造 `RetrievalOptions(top_k=request.top_k, time_range_days=request.time_range_days, view_names=request.views, budget_tokens=request.budget_tokens)`
   - 调用 `retriever.retrieve(request.query, request.user_id, options)`
   - 可选：若 `options.budget_tokens` 有效，调用 `FunnelCompressor.compress(results, budget_tokens)` 得到 summary
   - 计算 `latency_ms = (time.monotonic() - start) * 1000`
   - 返回 `MemoryRetrieveResponse(results=[r.dict() for r in results], summary=summary, intent="", retrieval_path="system2", latency_ms=latency_ms)`
4. 实现 `GET /memory/digest/{user_id}`：
   - `refresh=True` 时调用 `digest_manager.update_digest(user_id)`
   - 否则调用 `digest_manager.get_digest(user_id)`
   - 返回 `{"user_id": user_id, "digest": text, "cached": not refresh}`
5. 在 router 注册两个端点（确保 A4 的 `/memory/write` 端点不冲突）
6. 编写 API 测试 `api/test/internal/handler/test_memory_handler.py`（追加 retrieve/digest 用例）

### 验收标准

- `POST /memory/retrieve` 接受合法请求返回 `MemoryRetrieveResponse`，含 results/summary/latency_ms
- `GET /memory/digest/{user_id}` 返回 Digest 文本，`refresh=true` 时强制重建
- 端点在 router 中正确注册，可通过 FastAPI TestClient 调用
- API 测试通过：`cd api && python -m pytest test/internal/handler/test_memory_handler.py -v`

### 关联架构文档章节

- [03-consolidation-skill-policy-api.md §10 API 接口定义（/memory/retrieve, /memory/digest）](../../03-consolidation-skill-policy-api.md)
- [02-storage-and-retrieval.md §6.1 总流程图](../../02-storage-and-retrieval.md)

---

## B8：集成 ResultSynthesizer

- **执行时机**：T2 末，B6 完成后
- **前置条件**：DigestManager（B6）已实现；`token_buffer_memory.py` 与 `result_synthesizer_service.py` 存在且可改
- **类型**：改代码

### 目标

将 DigestManager 集成到对话合成链路：删除 `token_buffer_memory.get_relevant_facts` 的记忆检索逻辑（保留 `recent_messages` 与 `distant_summary`），在 `ResultSynthesizerService` 中注入 DigestManager，合成时调用 `get_digest` 注入记忆上下文到 system prompt。

### 输入

- 现有 `api/internal/core/memory/token_buffer_memory.py`（含 `get_relevant_facts` 方法）
- 现有 `api/internal/service/result_synthesizer_service.py`（含 `ResultSynthesizerService.synthesize`）
- DigestManager 实例（B6）

### 输出

- **文件路径**：
  - `api/internal/core/memory/token_buffer_memory.py`（修改）
  - `api/internal/service/result_synthesizer_service.py`（修改）
- **关键变更签名**：

```python
# token_buffer_memory.py
class TokenBufferMemory:
    def get_relevant_facts(self, account, current_query: str) -> list[str]:
        """
        记忆检索逻辑已迁移到 DigestManager（B6）。
        保留方法签名以兼容调用方，但返回空列表（或标记 deprecated）。
        recent_messages 与 distant_summary 逻辑保持不变。
        """
        return []  # deprecated，记忆注入由 DigestManager 负责

# result_synthesizer_service.py
class ResultSynthesizerService:
    def __init__(self, event_logger=None, digest_manager: Optional[DigestManager] = None):
        self.event_logger = event_logger
        self.digest_manager = digest_manager

    def synthesize(
        self,
        results: list[OrchestratedAgentResult],
        *,
        original_query: str = "",
        user_id: str = "",  # 新增参数，用于查询 Digest
        ...
    ) -> dict:
        """
        合成时若 digest_manager 与 user_id 可用，调用 get_digest(user_id)
        注入记忆上下文到 context_sections（与系统规则/用户偏好区段并列）。
        """
```

### 实现步骤

1. 修改 `api/internal/core/memory/token_buffer_memory.py`：
   - 定位 `get_relevant_facts` 方法（约 L126 起）
   - 删除方法体（原调用 pgvector/`recall_relevant_memories` 的逻辑）
   - 保留方法签名，返回空列表 `[]`，添加注释说明记忆注入已迁移到 DigestManager
   - 添加 `# TODO(deprecated): 此方法将在后续 G10 任务中彻底删除` 标记
   - **保留** `recent_messages`（`extract_recent`）与 `distant_summary`（`get_distant_summary`）逻辑不动
2. 修改 `api/internal/service/result_synthesizer_service.py`：
   - 在 `ResultSynthesizerService.__init__` 增加 `digest_manager: Optional[DigestManager] = None` 参数并保存
   - 在 `synthesize` 方法签名增加 `user_id: str = ""` 关键字参数
   - 在 `synthesize` 内部，构建 `context_sections` 后：
     - 若 `self.digest_manager` 与 `user_id` 均可用，调用 `await self.digest_manager.get_digest(user_id)` 获取 Digest 文本
     - 将 Digest 文本作为新区段加入 `context_sections["memory_digest"] = digest_text`（与系统规则/用户偏好区段并列，互不覆盖）
   - 异常时记录 warning 并跳过（不阻断合成）
3. 在调用 `ResultSynthesizerService` 的上层（如 orchestrator）传入 `user_id` 与 DigestManager 实例
4. 更新或新增单元测试：
   - `test_token_buffer_memory.py`：`get_relevant_facts` 返回空列表，`recent_messages`/`distant_summary` 仍正常
   - `test_result_synthesizer_service.py`：mock DigestManager，验证 `memory_digest` 区段被注入到 context_sections

### 验收标准

- `token_buffer_memory.get_relevant_facts` 返回空列表，不再调用任何 pgvector/`recall_relevant_memories` 逻辑
- `token_buffer_memory.recent_messages` 与 `distant_summary` 逻辑保持原有行为
- `ResultSynthesizerService.synthesize` 在 `digest_manager` 与 `user_id` 提供时，将 Digest 注入 `context_sections["memory_digest"]`
- DigestManager 异常时不阻断合成（仅 warning 日志）
- 对话中 MemoryDigest 正确注入 system prompt（可通过测试验证 context_sections 含 memory_digest 键）
- 单元测试通过：
  - `cd api && python -m pytest test/internal/core/memory/test_token_buffer_memory.py -v`
  - `cd api && python -m pytest test/internal/service/test_result_synthesizer_service.py -v`

### 关联架构文档章节

- [02-storage-and-retrieval.md §6.5 DigestManager（替代说明 v5.1：MemoryDigest 只替代 relevant_facts）](../../02-storage-and-retrieval.md)
- [02-storage-and-retrieval.md §旧系统替代说明（token_buffer_memory 替代矩阵）](../../02-storage-and-retrieval.md)
- [architecture-design.md §14 ResultSynthesizer 设计](../../architecture-design.md)

---

## 附录：Track B 验证命令汇总

每个任务完成后执行以下验证：

```bash
# 后端类型检查（所有 B 任务新建/修改的文件）
cd api && python -m py_compile internal/service/memory/hebbian_decay.py \
  internal/service/memory/cold_storage_manager.py \
  internal/service/memory/retriever.py \
  internal/service/memory/spread_activation.py \
  internal/service/memory/funnel_compressor.py \
  internal/service/memory/digest_manager.py \
  internal/handler/memory_handler.py \
  internal/core/memory/token_buffer_memory.py \
  internal/service/result_synthesizer_service.py

# 后端单元测试（Track B 全部）
cd api && python -m pytest test/internal/service/memory/ -v
cd api && python -m pytest test/internal/handler/test_memory_handler.py -v
cd api && python -m pytest test/internal/core/memory/test_token_buffer_memory.py -v
cd api && python -m pytest test/internal/service/test_result_synthesizer_service.py -v

# 容器健康检查（依赖 Neo4j/PostgreSQL pgvector/Redis/MinIO）
cd docker && docker compose ps
```

---

## 附录：Track B 文件清单

| 任务 | 文件路径 | 类型 |
|---|---|---|
| B1 | `api/internal/service/memory/hebbian_decay.py` | 新建 |
| B1 | `api/test/internal/service/memory/test_hebbian_decay.py` | 新建测试 |
| B2 | `api/internal/service/memory/cold_storage_manager.py` | 新建 |
| B2 | `api/test/internal/service/memory/test_cold_storage_manager.py` | 新建测试 |
| B3 | `api/internal/service/memory/retriever.py` | 新建 |
| B3 | `api/test/internal/service/memory/test_retriever.py` | 新建测试 |
| B4 | `api/internal/service/memory/spread_activation.py` | 新建 |
| B4 | `api/test/internal/service/memory/test_spread_activation.py` | 新建测试 |
| B5 | `api/internal/service/memory/funnel_compressor.py` | 新建 |
| B5 | `api/test/internal/service/memory/test_funnel_compressor.py` | 新建测试 |
| B6 | `api/internal/service/memory/digest_manager.py` | 新建 |
| B6 | `api/test/internal/service/memory/test_digest_manager.py` | 新建测试 |
| B7 | `api/internal/handler/memory_handler.py` | 追加（A4 创建） |
| B7 | `api/test/internal/handler/test_memory_handler.py` | 追加测试 |
| B8 | `api/internal/core/memory/token_buffer_memory.py` | 修改 |
| B8 | `api/internal/service/result_synthesizer_service.py` | 修改 |
| B8 | `api/test/internal/core/memory/test_token_buffer_memory.py` | 修改测试 |
| B8 | `api/test/internal/service/test_result_synthesizer_service.py` | 修改测试 |

---

> Track B 文档结束。共 8 个任务（B1-B8），覆盖存储分级、冷存储管理、混合检索、图扩展、漏斗压缩、Digest 管理、API 端点与 ResultSynthesizer 集成。
