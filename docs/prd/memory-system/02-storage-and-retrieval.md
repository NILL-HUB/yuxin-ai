# 存储层与读取路径 -- 代码实现

> 本文档为主架构文档的子模块，包含存储分级、读取路径、漏斗压缩、Memory Digest 的完整代码实现。
>
> **注意**：源文档存在换行符合并问题（所有换行符被替换为空格），导致代码块的缩进和分行可能不完美。代码逻辑和内容完整，但建议配合原始源文档阅读以获取最佳格式。

> **v5.1 设计更新（2026-07-09）**
>
> - **MemoryDigest 替代 token_buffer_memory 的记忆注入部分**：recent_messages 和 distant_summary 仍由对话管理负责，MemoryDigest 只负责记忆摘要部分。
> - **MemoryRetriever 替代 recall_relevant_memories**：旧函数和 user_memory_retrieval_tool 内部调用切换到 MemoryRetriever。
> - **新增图可视化**：用户通过图数据库可视化界面事后管理记忆（CRUD），无需逐条确认。
> - **新增降级策略**：每个依赖（Neo4j/PostgreSQL pgvector/Celery/Redis）挂掉时的降级行为明确定义。
> - **完全替代旧系统**：不做向后兼容，旧代码删除。

---

## 5. 存储层 — 分级与持久化

### 5.1 四级存储分层

灵感来源：人脑记忆的多存储模型（Atkinson-Shiffrin）与赫布突触可塑性理论。

| 层级 | 名称 | 存储介质 | 典型容量 | 访问延迟 | 示例内容 |
|------|------|----------|----------|----------|----------|
| L0 | 工作缓冲 | Redis | 64 KB / 会话 | <1 ms | 当前会话上下文窗口 |
| L1 | 热记忆 | Neo4j + PostgreSQL pgvector | ~10 K 条 / 用户 | <10 ms | 近 7 天高权重记忆 |
| L2 | 温记忆 | Neo4j + PostgreSQL pgvector（压缩索引） | ~100 K 条 / 用户 | <50 ms | 7-90 天中等权重 |
| L3 | 冷记忆 | S3 / 对象存储 | 无上限 | 100-500 ms | 90 天以上、低权重归档 |

**权重 → 层级映射规则**（由 `HebbianDecay.determine_tier` 实现）：

- `weight >= 0.7` → L1（热）
- `0.3 <= weight < 0.7` → L2（温）
- `weight < 0.3` → L3（冷）

### 5.2 HebbianDecay 完整 Python 实现

```python
from __future__ import annotations
import math
import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field
from neo4j import AsyncDriver, AsyncSession


# ── 枚举与配置 ──────────────────────────────────────────────
class StorageTier(enum.IntEnum):
    """
    存储层级枚举
    """

    HOT = 1
    # L1 热记忆
    WARM = 2  # L2 温记忆
    COLD = 3  # L3 冷记忆

    class DecayConfig(BaseModel):
        """
        赫布衰减配置
        """

        # 时间衰减速率（越大衰减越快）
        lambda_decay: float = Field(
            default=0.05, ge=0.0, le=1.0, description="时间衰减系数，控制遗忘曲线斜率"
        )
        # 共现增强系数
        alpha_cooccurrence: float = Field(
            default=0.2, ge=0.0, le=1.0, description="近期共现增强系数"
        )
        # 干扰惩罚系数
        beta_interference: float = Field(
            default=0.15, ge=0.0, le=1.0, description="语义竞争干扰惩罚系数"
        )
        # 共现时间窗口（小时）
        cooccurrence_window_hours: int = Field(
            default=168, ge=1, description="共现统计的时间窗口，默认 7 天"
        )
        # 层级阈值
        hot_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
        warm_threshold: float = Field(default=0.3, ge=0.0, le=1.0)

        class MemoryEdge(BaseModel):
            """
            记忆边的运行时表示
            """

            edge_id: str
            source_id: str
            target_id: str
            relation_type: str
            weight: float = Field(default=1.0)
            created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
            last_accessed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
            access_count: int = Field(default=1)
            cooccurrence_count: int = Field(default=0)

            # ── 核心类 ──────────────────────────────────────────────────
            class HebbianDecay:
                """
                赫布权重衰减器 — 根据时间/共现/干扰动态计算边权重并决定存储层级。      设计灵感：赫布学习规则 "一起激活的神经元连接更强"，     结合 Ebbinghaus 遗忘曲线实现自然衰减。
                """

                def __init__(self, config: DecayConfig) -> None:
                    """
                    初始化衰减器。          Args:
                    config: 衰减参数配置。"""
                    self._config = config

                    def compute_weight(
                        self, edge: MemoryEdge, now: Optional[datetime] = None
                    ) -> float:
                        """
                        计算边的当前综合权重。
                        综合权重 = 基础权重 × 时间衰减 × 共现增强 × 干扰惩罚
                        时间衰减: exp(-lambda * days_since_access)
                        共现增强: (1 + alpha * recent_cooccurrence_count)
                        干扰惩罚: 1 / (1 + beta * competitor_count)
                        Args:
                        edge: 待计算的边。
                        now: 当前时间，默认 UTC 当前时刻。
                        Returns:
                        归一化到 [0, 1] 的综合权重。
                        """
                        if now is None:
                            now = datetime.now(timezone.utc)
                            cfg = self._config
                            # ---- 1. 时间衰减 ----
                            days_elapsed = max(
                                0.0, (now - edge.last_accessed_at).total_seconds() / 86400.0
                            )
                            time_factor = math.exp(-cfg.lambda_decay * days_elapsed)
                            # ---- 2. 共现增强 ----
                            cooccurrence_factor = (
                                1.0 + cfg.alpha_cooccurrence * edge.cooccurrence_count
                            )
                            # ---- 3. 干扰惩罚（假设 competitor_count 保留在 edge 上）----
                            competitor_count = getattr(edge, "competitor_count", 0)
                            interference_factor = 1.0 / (
                                1.0 + cfg.beta_interference * competitor_count
                            )
                            # ---- 综合计算 ----
                            raw = (
                                edge.weight
                                * time_factor
                                * cooccurrence_factor
                                * interference_factor
                            )
                            # Sigmoid 归一化到 [0, 1]
                            normalized = 1.0 / (1.0 + math.exp(-5.0 * (raw - 0.5)))
                            return max(0.0, min(1.0, normalized))

                        def determine_tier(self, weight: float) -> StorageTier:
                            """
                            根据权重判定存储层级。          Args:
                            weight: 由 compute_weight 计算出的综合权重 [0, 1]。          Returns:
                            对应的存储层级枚举。"""
                            if weight >= self._config.hot_threshold:
                                return StorageTier.HOT
                            elif weight >= self._config.warm_threshold:
                                return StorageTier.WARM
                            else:
                                return StorageTier.COLD

                            async def batch_update_weights(
                                self,
                                edges: list[MemoryEdge],
                                neo4j_driver: AsyncDriver,
                                batch_size: int = 500,
                            ) -> dict[StorageTier, int]:
                                """
                                批量扫描并更新边权重及存储层级。
                                从 Neo4j 读取所有边，计算新权重，批量写回边权重和层级标签。
                                Args:
                                edges: 待处理的边列表。
                                neo4j_driver: Neo4j 异步驱动。
                                batch_size: 每批写入数量，控制事务大小。
                                Returns:
                                各层级迁移计数 {层级: 数量}。
                                """
                                now = datetime.now(timezone.utc)
                                tier_counts: dict[StorageTier, int] = {t: 0 for t in StorageTier}
                                # 按 batch_size 分组处理
                                for i in range(0, len(edges), batch_size):
                                    batch = edges[i : i + batch_size]
                                    updates: list[dict] = []
                                    for edge in batch:
                                        new_weight = self.compute_weight(edge, now)
                                        tier = self.determine_tier(new_weight)
                                        tier_counts[tier] += 1
                                        updates.append(
                                            {
                                                "edge_id": edge.edge_id,
                                                "source_id": edge.source_id,
                                                "target_id": edge.target_id,
                                                "weight": new_weight,
                                                "tier": tier.name,
                                                "last_accessed_at": edge.last_accessed_at.isoformat(),
                                            }
                                        )
                                        # Neo4j 批量 Cypher 写入
                                        cypher = """
                                        UNWIND $updates AS u
                                        MATCH (a:MemoryNode {id: u.source_id})-[r]->(b:MemoryNode {id: u.target_id})
                                        SET r.weight = u.weight,                 r.storage_tier = u.tier,                 r.last_accessed_at = datetime(u.last_accessed_at)
                                        RETURN count(r) AS updated             """
                                        async with neo4j_driver.session() as session:
                                            await session.run(cypher, updates=updates)
                                            return tier_counts
```

#### 5.2.1 节点删除与编辑策略（配合图可视化）

HebbianDecay 仅负责权重计算与层级迁移，节点删除/编辑由图可视化界面触发，分以下三种策略：

- **软删除**（用户在图可视化界面点"删除"）：Neo4j `is_active=false` + 清空 `user_memory.embedding` 列 + Redis 清缓存。节点保留在图中但变灰，不参与检索，可恢复。
- **彻底删除**（用户点"彻底删除"）：Neo4j `DETACH DELETE` + 删除 `user_memory` 行。不可恢复。
- **编辑**：创建新节点 + 旧节点 `t_invalidated_at=now` + 虚线关联。

软删除的记忆 30 天后自动彻底清理（由 Celery 周期任务执行）。

### 5.3 冷存储与 Key 重建

```python
from __future__ import annotations
import json
import gzip
import logging
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass, field
import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field
from neo4j import AsyncDriver

logger = logging.getLogger(__name__)


# ── 冷存储条目模型 ──────────────────────────────────────────
class ColdStorageEntry(BaseModel):
    """
    冷存储归档条目
    """

    memory_id: str
    user_id: str
    content: str
    embedding: list[float] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    archived_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    original_weight: float = 0.0
    storage_tier: str = "COLD"

    @dataclass
    class RebuildResult:
        """
        Key 重建结果
        """

        total_scanned: int = 0
        rebuilt_keys: int = 0
        statistical_skills: int = 0
        errors: list[str] = field(default_factory=list)

        class ColdStorageManager:
            """
            冷存储管理器 — 管理 L3 冷记忆的 S3 归档与 Key 重建。
            三种冷存储激活策略：
            1. global_traverse: 全量遍历冷存储，按需拉回热层
            2. rebuild_key_from_value: 从值内容重建 Key（主题提取）
            3. statistical_mining: 统计挖掘冷存储中的潜在模式
            """

            def __init__(
                self,
                s3_bucket: str,
                s3_prefix: str = "cold-memories/",
                neo4j_driver: Optional[AsyncDriver] = None,
                aws_region: str = "us-east-1",
            ) -> None:
                """
                初始化冷存储管理器。
                Args:
                s3_bucket: S3 桶名。
                s3_prefix: S3 对象键前缀。
                neo4j_driver: Neo4j 异步驱动（可选，用于重建时回写）。
                aws_region: AWS 区域。
                """
                self._bucket = s3_bucket
                self._prefix = s3_prefix
                self._neo4j = neo4j_driver
                self._s3_client = boto3.client("s3", region_name=aws_region)

                # ── S3 归档读写 ──────────────────────────────────────
                async def archive(self, entry: ColdStorageEntry) -> str:
                    """
                    将冷记忆条目写入 S3 归档。
                    以 gzip 压缩 JSON 格式存储，键路径为:
                    {prefix}{user_id}/{year}/{month}/{memory_id}.json.gz
                    Args:
                    entry: 待归档的冷存储条目。
                    Returns:
                    S3 对象键。
                    """
                    key = (
                        f"{self._prefix}{entry.user_id}/"
                        f"{entry.archived_at.year}/{entry.archived_at.month:02d}/"
                        f"{entry.memory_id}.json.gz"
                    )
                    payload = gzip.compress(entry.model_dump_json().encode("utf-8"))
                    self._s3_client.put_object(Bucket=self._bucket, Key=key, Body=payload)
                    logger.info("Cold memory archived: %s", key)
                    return key

                    async def read_archive(self, s3_key: str) -> Optional[ColdStorageEntry]:
                        """
                        从 S3 读取并解压冷记忆条目。
                        Args:
                        s3_key: S3 对象键。
                        Returns:
                        解析后的条目，或 None（对象不存在）。
                        """
                        try:
                            response = self._s3_client.get_object(Bucket=self._bucket, Key=s3_key)
                            raw = gzip.decompress(response["Body"].read())
                            return ColdStorageEntry.model_validate_json(raw)
                        except ClientError as e:
                            if e.response["Error"]["Code"] == "NoSuchKey":
                                logger.warning("Cold archive not found: %s", s3_key)
                                return None
                                raise

                        async def list_user_archives(
                            self,
                            user_id: str,
                            year: Optional[int] = None,
                        ) -> list[str]:
                            """
                            列出用户的所有冷归档 S3 键。
                            Args:
                            user_id: 用户 ID。
                            year: 可选，限定年份。
                            Returns:
                            S3 对象键列表。
                            """
                            prefix = f"{self._prefix}{user_id}/"
                            if year is not None:
                                prefix += f"{year}/"
                                paginator = self._s3_client.get_paginator("list_objects_v2")
                                keys: list[str] = []
                                for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                                    for obj in page.get("Contents", []):
                                        keys.append(obj["Key"])
                                        return keys
                                        # ── Key 重建策略 ─────────────────────────────────────

                            async def global_traverse(
                                self,
                                user_id: str,
                                threshold_weight: float = 0.5,
                            ) -> RebuildResult:
                                """
                                策略 1: 全量遍历冷存储，将权重可能回升的条目标记为待恢复。
                                遍历用户所有冷归档，基于访问统计和共现信息计算"恢复潜力分"，
                                超过阈值的标记回 Neo4j 热层。
                                Args:
                                user_id: 用户 ID。
                                threshold_weight: 恢复权重阈值。
                                Returns:
                                重建结果统计。
                                """
                                result = RebuildResult()
                                s3_keys = await self.list_user_archives(user_id)
                                result.total_scanned = len(s3_keys)
                                for key in s3_keys:
                                    try:
                                        entry = await self.read_archive(key)
                                        if entry is None:
                                            continue
                                            # 简易恢复判定：原始权重 + 共现加分
                                            recovery_score = entry.original_weight
                                            metadata_boost = (
                                                entry.metadata.get("cooccurrence_count", 0) * 0.05
                                            )
                                            if recovery_score + metadata_boost >= threshold_weight:
                                                if self._neo4j:
                                                    await self._restore_to_neo4j(entry)
                                                    result.rebuilt_keys += 1
                                    except Exception as e:
                                        result.errors.append(f"{key}: {e}")
                                        return result

                                async def rebuild_key_from_value(
                                    self, entry: ColdStorageEntry
                                ) -> Optional[str]:
                                    """
                                    策略 2: 从值内容重建 Key — 对归档内容做主题提取，重建语义索引。
                                    Args:
                                    entry: 冷存储条目。
                                    Returns:
                                    提取的主题 Key，或 None。
                                    """
                                    # 在生产中会调用 LLM 或关键词提取，此处为简化实现
                                    content = entry.content[:500]
                                    # 使用 TF 简易提取 Top-3 关键词作为重建 Key
                                    from collections import Counter
                                    import re

                                    words = re.findall(r"\b[a-zA-Z]{3,}\b", content.lower())
                                    stop_words = {
                                        "the",
                                        "and",
                                        "for",
                                        "are",
                                        "but",
                                        "not",
                                        "you",
                                        "all",
                                    }
                                    filtered = [w for w in words if w not in stop_words]
                                    top_words = [w for w, _ in Counter(filtered).most_common(3)]
                                    return "|".join(top_words) if top_words else None

                                    async def statistical_mining(
                                        self,
                                        user_id: str,
                                        min_support: int = 3,
                                    ) -> list[dict]:
                                        """
                                        策略 3: 统计挖掘冷存储中的潜在技能模式。
                                        扫描冷归档，统计高频行为序列，返回候选模式列表。
                                        Args:
                                        user_id: 用户 ID。
                                        min_support: 最小支持度（出现次数）。
                                        Returns:
                                        候选模式列表 [{"pattern": ..., "count": ..., "keys": [...]}, ...]
                                        """
                                        s3_keys = await self.list_user_archives(user_id)
                                        from collections import Counter

                                        pattern_counter: Counter = Counter()
                                        entries_by_key: dict[str, list[str]] = {}
                                        for key in s3_keys:
                                            entry = await self.read_archive(key)
                                            if entry is None:
                                                continue
                                                rebuilt_key = await self.rebuild_key_from_value(
                                                    entry
                                                )
                                                if rebuilt_key:
                                                    pattern_counter[rebuilt_key] += 1
                                                    entries_by_key.setdefault(
                                                        rebuilt_key, []
                                                    ).append(entry.memory_id)
                                                    candidates = [
                                                        {
                                                            "pattern": p,
                                                            "count": c,
                                                            "keys": entries_by_key.get(p, []),
                                                        }
                                                        for p, c in pattern_counter.items()
                                                        if c >= min_support
                                                    ]
                                                    return sorted(
                                                        candidates,
                                                        key=lambda x: x["count"],
                                                        reverse=True,
                                                    )

                                        async def _restore_to_neo4j(
                                            self, entry: ColdStorageEntry
                                        ) -> None:
                                            """
                                            将冷条目恢复到 Neo4j 热层。
                                            """
                                            if self._neo4j is None:
                                                return
                                                cypher = """
                                                MERGE (n:MemoryNode {id: $id})
                                                SET n.content = $content,
                                                n.weight = $weight,
                                                n.storage_tier = 'HOT',
                                                n.restored_at = datetime(),
                                                n += $metadata
                                                """
                                                async with self._neo4j.session() as session:
                                                    await session.run(
                                                        cypher,
                                                        id=entry.memory_id,
                                                        content=entry.content,
                                                        weight=entry.original_weight,
                                                        metadata=entry.metadata,
                                                    )
```

---

## 6. 读取路径 — 召回与压缩

### 6.1 总流程图
灵感来源：Kahneman 双系统理论 — System 1 快速直觉，System 2 深度推理。

```
用户查询 (query)     │     ▼ ┌──────────────┐     命中 Digest 缓存? │ PolicyRouter │──Yes──▶ _system1_fast_path ──▶ 直接返回 └──────┬───────┘        │ No        ▼ ┌──────────────────────────────────────────────────┐ │              _system2_deep_search                │ │                                                  │ │  ① TKG 粗召回（Cypher 图遍历 + BM25）           │ │       │                                          │ │       ▼                                          │ │  ② 向量精召回（pgvector HNSW 相似度搜索）        │ │       │                                          │ │       ▼                                          │ │  ③ SpreadActivation 图扩展（发现间接关联）       │ │       │                                          │ │       ▼                                          │ │  ④ _hybrid_score 混合评分（cos+bm25+graph）      │ │       │                                          │ │       ▼                                          │ │  ⑤ _evidence_accumulation（去重+排序+Early Stop）│ │       │                                          │ │       ▼                                          │ │  ⑥ FunnelCompressor（LLM 压缩为 ≤ budget tokens）│ └──────────────────┬───────────────────────────────┘                    │                    ▼            结构化摘要注入 Prompt
```

### 6.2 MemoryRetriever 完整 Python 实现

> **替代说明（v5.1）**：MemoryRetriever **完全替代** 旧系统的 `recall_relevant_memories`。
> - 旧函数 `recall_relevant_memories`（UserMemoryService）已删除，调用方统一切换到 `MemoryRetriever.retrieve`。
> - LangChain 工具 `user_memory_retrieval_tool` 的**接口签名保持不变**，仅内部实现替换为调用 MemoryRetriever，对上层 Agent 透明。
> - 旧的 Weaviate `UserMemory` collection 检索路径已删除，向量检索统一走 PostgreSQL pgvector（`user_memory.embedding` 列）。
> - 从 Weaviate 单路向量检索，升级为 TKG 图遍历（Neo4j BM25）+ pgvector 向量相似度的混合检索 + SpreadActivation 图扩展。

```python
from __future__ import annotations
import math
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from neo4j import AsyncDriver, AsyncSession
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


# ── 枚举与配置 ──────────────────────────────────────────────
class QueryIntent(str, Enum):
    """
    查询意图分类
    """

    FACTUAL = "factual"
    # 事实查询
    TEMPORAL = "temporal"
    # 时间相关
    RELATIONAL = "relational"
    # 关系查询
    ACTION = "action"
    # 行动指令
    REFLECTION = "reflection"

    # 自省/总结
    class RetrievalOptions(BaseModel):
        """
        检索选项
        """

        top_k: int = Field(default=20, ge=1, le=200, description="最大返回数量")
        time_range_days: Optional[int] = Field(default=None, description="时间范围限制")
        view_names: list[str] = Field(default_factory=list, description="限定查询的视图列表")
        require_evidence: bool = Field(default=False, description="是否要求证据链")
        budget_tokens: int = Field(default=2000, ge=100, le=8000, description="输出 token 预算")

        class RetrievalConfig(BaseModel):
            """
            检索配置
            """

            # 混合评分权重
            w_cosine: float = Field(default=0.4, ge=0.0, le=1.0)
            w_bm25: float = Field(default=0.3, ge=0.0, le=1.0)
            w_graph: float = Field(default=0.3, ge=0.0, le=1.0)
            # 时间衰减半衰期（小时）
            time_decay_half_life_hours: float = Field(default=168.0, ge=1.0)
            # Early Stop 参数
            early_stop_top_k: int = Field(default=10, ge=1)
            early_stop_score_gap: float = Field(default=0.15, ge=0.0, le=1.0)
            # pgvector: 向量存储在 user_memory.embedding 列，无需 collection_name
            # 向量维度
            embedding_dim: int = Field(default=1536)

            class RetrievalResult(BaseModel):
                """
                单条检索结果
                """

                memory_id: str
                content: str
                score: float
                source: str = Field(
                    default="hybrid", description="来源: semantic/bm25/graph/hybrid"
                )
                timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
                metadata: dict = Field(default_factory=dict)
                evidence_chain: list[str] = Field(default_factory=list, description="证据链路径")

                # ── 核心类 ──────────────────────────────────────────────────
                class MemoryRetriever:
                    """
                    混合检索器 — 融合语义/关键词/图三通道。      实现 System 1（快速缓存路径）和 System 2（深度搜索路径）的双路架构。"""

                    def __init__(
                        self,
                        neo4j: AsyncDriver,
                        db_session: AsyncSession,
                        config: RetrievalConfig,
                        llm_client: Optional[AsyncOpenAI] = None,
                    ) -> None:
                        """
                        初始化检索器。
                        Args:
                        neo4j: Neo4j 异步驱动。
                        db_session: SQLAlchemy 异步会话（用于 pgvector 向量检索）。
                        config: 检索配置。
                        llm_client: LLM 客户端（用于意图分类，可选）。
                        """
                        self._neo4j = neo4j
                        self._db_session = db_session
                        self._config = config
                        self._llm = llm_client

                        async def retrieve(
                            self,
                            query: str,
                            user_id: str,
                            options: Optional[RetrievalOptions] = None,
                        ) -> list[RetrievalResult]:
                            """
                            主检索入口，实现 System 1/System 2 路由。
                            先尝试 System 1 快速路径（Digest 缓存），未命中则走
                            System 2 深度搜索。
                            Args:
                            query: 用户查询文本。
                            user_id: 用户 ID。
                            options: 检索选项，默认使用配置中的默认值。
                            Returns:
                            按分数降序排列的检索结果列表。
                            """
                            if options is None:
                                options = RetrievalOptions()
                                # 尝试 System 1
                                fast_result = await self._system1_fast_path(query, user_id)
                                if fast_result is not None:
                                    return [
                                        RetrievalResult(
                                            memory_id="digest",
                                            content=fast_result,
                                            score=1.0,
                                            source="digest_cache",
                                        )
                                    ]
                                    # System 2 深度搜索
                                    results = await self._system2_deep_search(
                                        query, user_id, options
                                    )
                                    return results

                            async def _system1_fast_path(
                                self,
                                query: str,
                                user_id: str,
                            ) -> Optional[str]:
                                """
                                快速路径：从 Digest 缓存返回。
                                通过 Redis 获取预计算的 Digest 摘要。
                                如果 Digest 缓存存在且未过期，直接返回摘要文本。
                                Args:
                                query: 用户查询。
                                user_id: 用户 ID。
                                Returns:
                                Digest 文本，或 None（缓存未命中）。
                                """
                                # 此处简化为直接返回 None；实际由 DigestManager 提供
                                # 生产中: return await self._digest_manager.get_digest(user_id)
                                return None

                                async def _system2_deep_search(
                                    self,
                                    query: str,
                                    user_id: str,
                                    options: RetrievalOptions,
                                ) -> list[RetrievalResult]:
                                    """
                                    慢速路径：TKG 粗召回 → 向量精召回 → 图扩展 → 混合评分 → Early Stop。
                                    Args:
                                    query: 用户查询。
                                    user_id: 用户 ID。
                                    options: 检索选项。
                                    Returns:
                                    深度检索结果列表。
                                    """
                                    all_candidates: dict[str, RetrievalResult] = {}
                                    # ① TKG 粗召回（Neo4j Cypher + BM25 索引）
                                    tkg_results = await self._tkg_recall(
                                        query, user_id, options.top_k * 2
                                    )
                                    for r in tkg_results:
                                        all_candidates[r.memory_id] = r
                                        # ② 向量精召回（pgvector）
                                        query_embed = await self._embed_query(query)
                                        vector_results = await self._vector_recall(
                                            query_embed, user_id, options.top_k * 2
                                        )
                                        for r in vector_results:
                                            if r.memory_id in all_candidates:
                                                # 合并分数
                                                existing = all_candidates[r.memory_id]
                                                r.score = max(existing.score, r.score)
                                                r.source = "hybrid"
                                                all_candidates[r.memory_id] = r
                                                # ③ 图扩展激活
                                                start_ids = [
                                                    r.memory_id
                                                    for r in list(all_candidates.values())[:5]
                                                ]
                                                spread_results = await self._graph_spread(
                                                    start_ids, top_k=options.top_k
                                                )
                                                for node_id, activation in spread_results:
                                                    if node_id not in all_candidates:
                                                        all_candidates[node_id] = RetrievalResult(
                                                            memory_id=node_id,
                                                            content="",
                                                            score=activation * 0.8,
                                                            # 图扩展分数打折
                                                            source="graph_spread",
                                                        )
                                                        # ④ 混合评分
                                                        scored = []
                                                        for mid, result in all_candidates.items():
                                                            # 获取完整内容用于评分
                                                            node_data = await self._get_node_data(
                                                                mid
                                                            )
                                                            if node_data:
                                                                result.content = node_data.get(
                                                                    "content", ""
                                                                )
                                                                result.timestamp = node_data.get(
                                                                    "timestamp", result.timestamp
                                                                )
                                                                result.metadata = node_data.get(
                                                                    "metadata", {}
                                                                )
                                                                hybrid = self._hybrid_score(
                                                                    result, query_embed, query
                                                                )
                                                                time_decayed = (
                                                                    hybrid
                                                                    * self._time_decay(
                                                                        result.timestamp
                                                                    )
                                                                )
                                                                result.score = time_decayed
                                                                scored.append(result)
                                                                # ⑤ 排序 + Early Stop
                                                                scored.sort(
                                                                    key=lambda x: x.score,
                                                                    reverse=True,
                                                                )
                                                                final = self._apply_early_stop(
                                                                    scored, options.top_k
                                                                )
                                                                return final[: options.top_k]

                                    async def _tkg_recall(
                                        self,
                                        query: str,
                                        user_id: str,
                                        top_k: int,
                                    ) -> list[RetrievalResult]:
                                        """
                                        TKG 粗召回 — Neo4j 全文索引 + BM25。
                                        """
                                        cypher = """
                                        CALL db.index.fulltext.queryNodes("memoryFullText", $query)
                                        YIELD node, score
                                        WHERE node.user_id = $user_id           AND (node.storage_tier IS NULL OR node.storage_tier IN ['HOT', 'WARM'])
                                        RETURN node.id AS memory_id,                node.content AS content,                node.created_at AS timestamp,                node,                score AS bm25_score
                                        ORDER BY score DESC
                                        LIMIT $limit
                                        """
                                        async with self._neo4j.session() as session:
                                            result = await session.run(
                                                cypher, query=query, user_id=user_id, limit=top_k
                                            )
                                            records = await result.data()
                                            return [
                                                RetrievalResult(
                                                    memory_id=r["memory_id"],
                                                    content=r["content"] or "",
                                                    score=r["bm25_score"],
                                                    source="bm25",
                                                    timestamp=r["timestamp"],
                                                )
                                                for r in records
                                            ]

                                        async def _vector_recall(
                                            self,
                                            query_embedding: list[float],
                                            user_id: str,
                                            top_k: int,
                                        ) -> list[RetrievalResult]:
                                            """
                                            向量精召回 — pgvector HNSW 相似度搜索。
                                            """
                                            # pgvector: 在 user_memory.embedding 列上执行余弦距离查询
                                            stmt = text("""
                                                SELECT memory_id, content,
                                                       1 - (embedding <=> CAST(:query_embedding AS vector)) AS score,
                                                       metadata
                                                FROM user_memory
                                                WHERE owner_account_id = :user_id
                                                ORDER BY embedding <=> CAST(:query_embedding AS vector)
                                                LIMIT :top_k
                                            """)
                                            result = await self._db_session.execute(stmt, {
                                                "query_embedding": str(query_embedding),
                                                "user_id": user_id,
                                                "top_k": top_k,
                                            })
                                            rows = result.fetchall()
                                            return [
                                                RetrievalResult(
                                                    memory_id=str(row[0]),
                                                    content=row[1] or "",
                                                    score=float(row[2]),
                                                    source="semantic",
                                                    metadata=row[3] or {},
                                                )
                                                for row in rows
                                            ]

                                            async def _graph_spread(
                                                self,
                                                start_ids: list[str],
                                                top_k: int = 20,
                                            ) -> list[tuple[str, float]]:
                                                """
                                                图扩展 — 委托 SpreadActivation。
                                                """
                                                spread = SpreadActivation(
                                                    self._neo4j, SpreadConfig()
                                                )
                                                return await spread.activate(start_ids, top_k)

                                                async def _embed_query(
                                                    self, text: str
                                                ) -> list[float]:
                                                    """
                                                    将查询文本转为嵌入向量。
                                                    """
                                                    # 生产中调用 embedding 模型
                                                    # response = await self._llm.embeddings.create(model="...", input=text)
                                                    # return response.data[0].embedding
                                                    return [0.0] * self._config.embedding_dim

                                                    async def _get_node_data(
                                                        self, node_id: str
                                                    ) -> Optional[dict]:
                                                        """
                                                        从 Neo4j 获取节点完整数据。
                                                        """
                                                        cypher = """
                                                        MATCH (n:MemoryNode {id: $id})
                                                        RETURN n.content AS content,
                                                        n.created_at AS timestamp,
                                                        properties(n) AS metadata
                                                        """
                                                        async with self._neo4j.session() as session:
                                                            result = await session.run(
                                                                cypher, id=node_id
                                                            )
                                                            records = await result.data()
                                                            return records[0] if records else None

                                                        def _hybrid_score(
                                                            self,
                                                            result: RetrievalResult,
                                                            query_embed: list[float],
                                                            query_text: str,
                                                        ) -> float:
                                                            """
                                                            混合检索评分: w_cosine * cos_sim + w_bm25 * bm25 + w_graph * graph。
                                                            根据来源类型分配权重，缺失通道权重重分配到其余通道。
                                                            Args:
                                                            result: 检索结果（已含来源和原始分数）。
                                                            query_embed: 查询嵌入向量。
                                                            query_text: 查询文本。
                                                            Returns:
                                                            归一化混合分数 [0, 1]。
                                                            """
                                                            cfg = self._config
                                                            # 确定各通道分数
                                                            cos_score = 0.0
                                                            bm25_score = 0.0
                                                            graph_score = 0.0
                                                            if result.source == "semantic":
                                                                cos_score = result.score
                                                            elif result.source == "bm25":
                                                                bm25_score = result.score
                                                            elif result.source in (
                                                                "graph_spread",
                                                                "graph",
                                                            ):
                                                                graph_score = result.score
                                                            elif result.source == "hybrid":
                                                                cos_score = bm25_score = (
                                                                    graph_score
                                                                ) = result.score
                                                                # 缺失通道权重重分配
                                                                weights = {}
                                                                total_w = 0.0
                                                                for name, score, w in [
                                                                    (
                                                                        "cos",
                                                                        cos_score,
                                                                        cfg.w_cosine,
                                                                    ),
                                                                    (
                                                                        "bm25",
                                                                        bm25_score,
                                                                        cfg.w_bm25,
                                                                    ),
                                                                    (
                                                                        "graph",
                                                                        graph_score,
                                                                        cfg.w_graph,
                                                                    ),
                                                                ]:
                                                                    if score > 0:
                                                                        weights[name] = w
                                                                        total_w += w
                                                                        if total_w == 0:
                                                                            return 0.0
                                                                            # 归一化权重
                                                                            final = 0.0
                                                                            for name, score, w in [
                                                                                (
                                                                                    "cos",
                                                                                    cos_score,
                                                                                    cfg.w_cosine,
                                                                                ),
                                                                                (
                                                                                    "bm25",
                                                                                    bm25_score,
                                                                                    cfg.w_bm25,
                                                                                ),
                                                                                (
                                                                                    "graph",
                                                                                    graph_score,
                                                                                    cfg.w_graph,
                                                                                ),
                                                                            ]:
                                                                                if name in weights:
                                                                                    final += score * (
                                                                                        w / total_w
                                                                                    )
                                                                                    return max(
                                                                                        0.0,
                                                                                        min(
                                                                                            1.0,
                                                                                            final,
                                                                                        ),
                                                                                    )

                                                            def _time_decay(
                                                                self,
                                                                timestamp: datetime,
                                                                now: Optional[datetime] = None,
                                                            ) -> float:
                                                                """
                                                                时间衰减: 0.995^hours_elapsed。
                                                                使用指数衰减模型，半衰期由配置决定。
                                                                decay = 0.995^(hours / half_life_hours * ln(0.5) / ln(0.995))
                                                                Args:
                                                                timestamp: 记忆时间戳。
                                                                now: 当前时间，默认 UTC 当前。
                                                                Returns:
                                                                衰减系数 [0, 1]。
                                                                """
                                                                if now is None:
                                                                    now = datetime.now(timezone.utc)
                                                                    hours_elapsed = max(
                                                                        0.0,
                                                                        (
                                                                            now - timestamp
                                                                        ).total_seconds()
                                                                        / 3600.0,
                                                                    )
                                                                    # 使用配置的半衰期计算
                                                                    half_life = (
                                                                        self._config.time_decay_half_life_hours
                                                                    )
                                                                    decay = 0.5 ** (
                                                                        hours_elapsed / half_life
                                                                    )
                                                                    return max(
                                                                        0.01, decay
                                                                    )  # 保留最低 1% 以防完全消失

                                                                def _apply_early_stop(
                                                                    self,
                                                                    scored: list[RetrievalResult],
                                                                    top_k: int,
                                                                ) -> list[RetrievalResult]:
                                                                    """
                                                                    Early Stop: 当 top_k+1 的分数与 top_k 差距超过阈值时提前截断。
                                                                    Args:
                                                                    scored: 已排序的检索结果。
                                                                    top_k: 最大返回数。
                                                                    Returns:
                                                                    截断后的结果列表。
                                                                    """
                                                                    if len(scored) <= top_k:
                                                                        return scored
                                                                        gap = (
                                                                            self._config.early_stop_score_gap
                                                                        )
                                                                        cutoff = min(
                                                                            top_k, len(scored) - 1
                                                                        )
                                                                        # 检查 cutoff 之后的分数是否显著下降
                                                                        if cutoff < len(scored) - 1:
                                                                            top_score = scored[
                                                                                cutoff - 1
                                                                            ].score
                                                                            next_score = scored[
                                                                                cutoff
                                                                            ].score
                                                                            if (
                                                                                top_score
                                                                                - next_score
                                                                                > gap
                                                                            ):
                                                                                return scored[
                                                                                    :cutoff
                                                                                ]
                                                                                return scored[
                                                                                    :top_k
                                                                                ]
```

### 6.3 SpreadActivation 完整 Python 实现

```python
from __future__ import annotations
import math
import logging
from dataclasses import dataclass
from typing import Optional
from pydantic import BaseModel, Field
from neo4j import AsyncDriver

logger = logging.getLogger(__name__)


class SpreadConfig(BaseModel):
    """
    图扩展激活配置
    """

    max_hops: int = Field(default=3, ge=1, le=6, description="最大跳数")
    activation_decay: float = Field(default=0.5, ge=0.0, le=1.0, description="每跳衰减系数")
    min_activation: float = Field(default=0.01, ge=0.0, le=1.0, description="最低激活阈值")
    edge_weight_multiplier: float = Field(default=1.0, ge=0.0, le=5.0)
    top_k: int = Field(default=20, ge=1, le=100)

    class SpreadActivation:
        """
        图扩展激活 — 从起始节点沿边扩展发现间接关联。      灵感来源：认知科学中的扩散激活理论（Collins & Loftus, 1975）—     概念网络中激活信号沿语义关联路径扩散，距离越远激活越弱。
        """

        def __init__(
            self,
            neo4j_driver: AsyncDriver,
            config: Optional[SpreadConfig] = None,
        ) -> None:
            """
            初始化图扩展器。
            Args:
            neo4j_driver: Neo4j 异步驱动。
            config: 扩展配置，默认使用 SpreadConfig 默认值。
            """
            self._neo4j = neo4j_driver
            self._config = config or SpreadConfig()

            async def activate(
                self,
                start_nodes: list[str],
                top_k: int = 20,
            ) -> list[tuple[str, float]]:
                """
                从起始节点沿边扩展，返回激活值排序的 (node_id, activation) 列表。
                使用 Neo4j Cypher 实现多跳遍历，每跳衰减激活值。
                Args:
                start_nodes: 起始节点 ID 列表。
                top_k: 返回的最大节点数。
                Returns:
                按激活值降序排列的 (node_id, activation) 元组列表。
                """
                cfg = self._config
                top_k = min(top_k, cfg.top_k)
                # 使用纯 Cypher 实现多跳扩散激活
                # 为每跳生成独立的 MATCH-WITH 阶段
                hop_queries = []
                params: dict = {"start_nodes": start_nodes, "top_k": top_k}
                for hop in range(1, cfg.max_hops + 1):
                    hop_alias = f"h{hop}"
                    decay_factor = cfg.activation_decay**hop
                    params[f"decay_{hop}"] = decay_factor
                    if hop == 1:
                        hop_queries.append(
                            f"""
                        MATCH (start:MemoryNode) WHERE start.id IN $start_nodes
                        CALL {{
                        WITH start
                        MATCH (start)-[r]->(next:MemoryNode)
                        RETURN next, r.weight AS edge_weight                 }} IN TRANSACTIONS OF 100 ROWS
                        RETURN next.id AS node_id,                        r.weight * $decay_{hop} AS activation                 """
                        )
                    else:
                        prev_alias = f"h{hop - 1}"
                        hop_queries.append(
                            f"""
                        WITH {prev_alias}
                        CALL {{
                        WITH {prev_alias}
                        MATCH (prev_node:MemoryNode {{id: {prev_alias}.node_id}})-[r]->(next:MemoryNode)
                        WHERE next.id <> {prev_alias}.node_id
                        RETURN next, r.weight AS edge_weight                 }} IN TRANSACTIONS OF 100 ROWS
                        RETURN next.id AS node_id,                        {prev_alias}.activation * r.weight * $decay_{hop} AS activation                 """
                        )
                        # 合并为带 UNION 的完整查询，收集所有 hop 结果
                        union_parts = []
                        for i, hq in enumerate(hop_queries):
                            clean = hq.strip()
                            union_parts.append(clean)
                            full_query = "\n\nUNION ALL\n\n".join(union_parts) + "\n\n"
                            # 外层聚合
                            full_query += """
                            WITH node_id, sum(activation) AS total_activation
                            WHERE total_activation >= $min_activation
                            RETURN node_id, total_activation AS activation
                            ORDER BY activation DESC
                            LIMIT $top_k         """
                            params["min_activation"] = cfg.min_activation
                            try:
                                async with self._neo4j.session() as session:
                                    result = await session.run(full_query, **params)
                                    records = await result.data()
                                    return [(r["node_id"], r["activation"]) for r in records]
                            except Exception as e:
                                logger.warning(
                                    "SpreadActivation Cypher failed, falling back to iterative: %s",
                                    e,
                                )
                                return await self._fallback_iterative(start_nodes, top_k)

                async def _fallback_iterative(
                    self,
                    start_nodes: list[str],
                    top_k: int,
                ) -> list[tuple[str, float]]:
                    """
                    迭代式回退实现 — 逐跳查询并合并结果。
                    当复杂 Cypher 执行失败时使用。
                    Args:
                    start_nodes: 起始节点 ID。
                    top_k: 最大返回数。
                    Returns:
                    (node_id, activation) 列表。
                    """
                    cfg = self._config
                    activations: dict[str, float] = {}
                    # 初始化
                    current_frontier: list[tuple[str, float]] = [(nid, 1.0) for nid in start_nodes]
                    visited: set[str] = set(start_nodes)
                    for hop in range(1, cfg.max_hops + 1):
                        decay = cfg.activation_decay**hop
                        next_frontier: list[tuple[str, float]] = []
                        for node_id, base_act in current_frontier:
                            cypher = """
                            MATCH (src:MemoryNode {id: $src_id})-[r]->(tgt:MemoryNode)
                            WHERE NOT tgt.id IN $visited
                            RETURN tgt.id AS tgt_id, r.weight AS edge_w
                            """
                            async with self._neo4j.session() as session:
                                result = await session.run(
                                    cypher, src_id=node_id, visited=list(visited)
                                )
                                records = await result.data()
                                for rec in records:
                                    tgt_id = rec["tgt_id"]
                                    edge_w = rec["edge_w"] or 1.0
                                    act = base_act * edge_w * decay
                                    if act < cfg.min_activation:
                                        continue
                                        # 多路径激活取最大值
                                        if tgt_id not in activations or act > activations[tgt_id]:
                                            activations[tgt_id] = act
                                            if tgt_id not in visited:
                                                next_frontier.append((tgt_id, act))
                                                visited.add(tgt_id)
                                                current_frontier = next_frontier
                                                if not current_frontier:
                                                    break
                                                    sorted_results = sorted(
                                                        activations.items(),
                                                        key=lambda x: x[1],
                                                        reverse=True,
                                                    )
                                                    return sorted_results[:top_k]
```

### 6.4 FunnelCompressor 完整 Python 实现

```python
from __future__ import annotations
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class FunnelLayer(str, Enum):
    """
    漏斗层级
    """

    RAW = "raw"
    # Layer 0: 原始召回
    DEDUP = "dedup"
    # Layer 1: 去重
    SCORED = "scored"
    # Layer 2: 评分排序
    EVIDENCE = "evidence"
    # Layer 3: 证据累积
    COMPRESSED = "compressed"  # Layer 4: LLM 压缩
    FINAL = "final"

    # Layer 5: 最终输出
    class FunnelConfig(BaseModel):
        """
        漏斗压缩配置
        """

        # 证据累积
        dedup_similarity_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
        evidence_max_items: int = Field(default=30, ge=1)
        # Early Stop
        early_stop_confidence: float = Field(default=0.9, ge=0.0, le=1.0)
        early_stop_min_items: int = Field(default=3, ge=1)
        # LLM 压缩
        llm_model: str = Field(default="gpt-4o-mini")
        llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
        llm_max_tokens: int = Field(default=2000, ge=100)
        compression_prompt_template: str = Field(
            default=""" 请将以下记忆证据压缩为结构化摘要。要求： 1. 保留关键事实、时间、人物、数量 2. 按主题分组，使用有序列表 3. 丢弃冗余和低相关内容 4. 输出控制在 {budget} tokens 以内
        ## 证据列表 {evidence} """
        )

        class EvidenceItem(BaseModel):
            """
            证据条目
            """

            content: str
            score: float
            source: str
            timestamp: Optional[datetime] = None
            memory_id: str = ""

            class FunnelCompressor:
                """
                五层漏斗压缩 — 将大量召回结果压缩为可注入的结构化摘要。
                漏斗层级:
                Layer 0 (RAW): 原始召回结果
                Layer 1 (DEDUP): 语义去重
                Layer 2 (SCORED): 加权评分排序
                Layer 3 (EVIDENCE): 证据累积 + Early Stop
                Layer 4 (COMPRESSED): LLM 压缩
                Layer 5 (FINAL): 最终输出
                """

                def __init__(
                    self,
                    llm_client: AsyncOpenAI,
                    config: Optional[FunnelConfig] = None,
                ) -> None:
                    """
                    初始化漏斗压缩器。
                    Args:
                    llm_client: OpenAI 异步客户端。
                    config: 压缩配置，默认使用默认值。
                    """
                    self._llm = llm_client
                    self._config = config or FunnelConfig()

                    async def compress(
                        self,
                        candidates: list["RetrievalResult"],
                        budget_tokens: int = 2000,
                    ) -> str:
                        """
                        主压缩入口 — 将召回结果通过五层漏斗压缩为结构化摘要。
                        Args:
                        candidates: 检索结果列表。
                        budget_tokens: 输出 token 预算。
                        Returns:
                        压缩后的结构化摘要文本。
                        """
                        if not candidates:
                            return ""
                            # Layer 0 → Layer 1: 去重
                            deduped = self._deduplicate(candidates)
                            # Layer 1 → Layer 2: 评分排序
                            scored = self._re_score(deduped)
                            # Layer 2 → Layer 3: 证据累积 + Early Stop
                            evidence = await self._evidence_accumulation(scored)
                            if not evidence:
                                return ""
                                # Early Stop 检查
                                if self._check_early_stop(evidence):
                                    logger.info(
                                        "Early Stop triggered, evidence count=%d", len(evidence)
                                    )
                                    return self._format_evidence(
                                        evidence[: self._config.early_stop_min_items]
                                    )
                                    # Layer 3 → Layer 4: LLM 压缩
                                    compressed = await self._llm_compress(evidence, budget_tokens)
                                    # Layer 5: 最终输出
                                    return compressed

                        def _deduplicate(
                            self,
                            candidates: list["RetrievalResult"],
                        ) -> list["RetrievalResult"]:
                            """
                            Layer 1: 语义去重 — 基于内容的简易文本去重。
                            使用编辑距离比率作为去重依据。在生产中可替换为
                            向量余弦相似度去重。
                            Args:
                            candidates: 原始候选列表。
                            Returns:
                            去重后的列表。
                            """
                            threshold = self._config.dedup_similarity_threshold
                            kept: list["RetrievalResult"] = []
                            seen_contents: list[str] = []
                            for c in candidates:
                                is_dup = False
                                for seen in seen_contents:
                                    sim = self._text_similarity(c.content, seen)
                                    if sim >= threshold:
                                        is_dup = True
                                        break
                                        if not is_dup:
                                            kept.append(c)
                                            seen_contents.append(c.content)
                                            return kept

                                            @staticmethod
                                            def _text_similarity(a: str, b: str) -> float:
                                                """
                                                计算两个文本的简易相似度（最长公共子序列比率）。
                                                """
                                                if not a or not b:
                                                    return 0.0
                                                    # 使用集合交集比率（快速近似）
                                                    set_a = set(a.lower().split())
                                                    set_b = set(b.lower().split())
                                                    if not set_a or not set_b:
                                                        return 0.0
                                                        intersection = set_a & set_b
                                                        union = set_a | set_b
                                                        return len(intersection) / len(union)

                                                def _re_score(
                                                    self,
                                                    candidates: list["RetrievalResult"],
                                                ) -> list["RetrievalResult"]:
                                                    """
                                                    Layer 2: 重新评分排序。
                                                    综合原始分数和时间新鲜度进行二次排序。
                                                    Args:
                                                    candidates: 去重后的候选列表。
                                                    Returns:
                                                    排序后的列表。
                                                    """
                                                    now = datetime.now(timezone.utc)
                                                    for c in candidates:
                                                        hours_age = max(
                                                            0.0,
                                                            (now - c.timestamp).total_seconds()
                                                            / 3600.0,
                                                        )
                                                        freshness = 0.99**hours_age
                                                        # 新鲜度衰减
                                                        c.score = c.score * (0.7 + 0.3 * freshness)
                                                        return sorted(
                                                            candidates,
                                                            key=lambda x: x.score,
                                                            reverse=True,
                                                        )

                                                    async def _evidence_accumulation(
                                                        self,
                                                        candidates: list["RetrievalResult"],
                                                    ) -> list[EvidenceItem]:
                                                        """
                                                        Layer 2-3: 证据累积 — 将候选转为证据条目，限制最大数量。
                                                        Args:
                                                        candidates: 排序后的候选列表。
                                                        Returns:
                                                        证据条目列表。
                                                        """
                                                        max_items = self._config.evidence_max_items
                                                        evidence = []
                                                        for c in candidates[:max_items]:
                                                            evidence.append(
                                                                EvidenceItem(
                                                                    content=c.content,
                                                                    score=c.score,
                                                                    source=c.source,
                                                                    timestamp=c.timestamp,
                                                                    memory_id=c.memory_id,
                                                                )
                                                            )
                                                            return evidence

                                                        def _check_early_stop(
                                                            self, evidence: list[EvidenceItem]
                                                        ) -> bool:
                                                            """
                                                            Early Stop 判定逻辑。
                                                            当满足以下条件之一时触发 Early Stop:
                                                            1. 证据条目数 < early_stop_min_items
                                                            2. Top-1 证据分数 > confidence 阈值 且 条目数 <= 2x min_items
                                                            Args:
                                                            evidence: 证据列表。
                                                            Returns:
                                                            是否触发 Early Stop。
                                                            """
                                                            cfg = self._config
                                                            if (
                                                                len(evidence)
                                                                <= cfg.early_stop_min_items
                                                            ):
                                                                return True
                                                                if (
                                                                    evidence[0].score
                                                                    >= cfg.early_stop_confidence
                                                                ):
                                                                    if (
                                                                        len(evidence)
                                                                        <= cfg.early_stop_min_items
                                                                        * 2
                                                                    ):
                                                                        return True
                                                                        return False

                                                                        @staticmethod
                                                                        def _format_evidence(
                                                                            evidence: list[
                                                                                EvidenceItem
                                                                            ],
                                                                        ) -> str:
                                                                            """
                                                                            将证据格式化为简洁文本（Early Stop 时使用）。
                                                                            """
                                                                            lines = []
                                                                            for i, e in enumerate(
                                                                                evidence, 1
                                                                            ):
                                                                                lines.append(
                                                                                    f"{i}. [score={e.score:.3f}] {e.content[:200]}"
                                                                                )
                                                                                return "\n".join(
                                                                                    lines
                                                                                )

                                                                            async def _llm_compress(
                                                                                self,
                                                                                evidence: list[
                                                                                    EvidenceItem
                                                                                ],
                                                                                budget_tokens: int,
                                                                            ) -> str:
                                                                                """
                                                                                Layer 4: LLM 压缩为结构化摘要。
                                                                                将证据列表送入 LLM，要求压缩到指定 token 预算内。
                                                                                Args:
                                                                                evidence: 证据列表。
                                                                                budget_tokens: token 预算。
                                                                                Returns:
                                                                                LLM 压缩后的摘要文本。
                                                                                """
                                                                                evidence_text = "\n".join(
                                                                                    f"- [{e.source}|{e.score:.2f}] {e.content[:300]}"
                                                                                    for e in evidence
                                                                                )
                                                                                prompt = self._config.compression_prompt_template.format(
                                                                                    budget=budget_tokens,
                                                                                    evidence=evidence_text,
                                                                                )
                                                                                try:
                                                                                    response = await self._llm.chat.completions.create(
                                                                                        model=self._config.llm_model,
                                                                                        messages=[
                                                                                            {
                                                                                                "role": "user",
                                                                                                "content": prompt,
                                                                                            }
                                                                                        ],
                                                                                        temperature=self._config.llm_temperature,
                                                                                        max_tokens=self._config.llm_max_tokens,
                                                                                    )
                                                                                    return (
                                                                                        response.choices[
                                                                                            0
                                                                                        ].message.content
                                                                                        or ""
                                                                                    )
                                                                                except (
                                                                                    Exception
                                                                                ) as e:
                                                                                    logger.error(
                                                                                        "LLM compress failed: %s, fallback to raw",
                                                                                        e,
                                                                                    )
                                                                                    return self._format_evidence(
                                                                                        evidence[
                                                                                            :10
                                                                                        ]
                                                                                    )
```

### 6.5 DigestManager 完整 Python 实现

> **替代说明（v5.1）**：MemoryDigest（DigestManager）**只替代** `token_buffer_memory` 中的 `relevant_facts`（原 relevant_facts 500 tokens 部分），不接管整个对话缓冲。
>
> - **属于记忆系统（DigestManager 负责）**：用户画像 / 已习得技能 / 近期事件 / 待办任务的结构化摘要（≤ 2K tokens），由 Neo4j 重建 + Redis 缓存。
> - **不属于记忆系统（仍由对话管理负责）**：
>   - `recent_messages`（最近 20 条消息原文）— 由对话管理维护的滑动窗口。
>   - `distant_summary`（远期摘要 1000 tokens）— 由对话管理维护的会话级长程摘要。
> - **注入位置**：Digest 通过 `ResultSynthesizer` 注入 system prompt 的"记忆区段"，与 `recent_messages`、`distant_summary` 区段并列，互不覆盖。
> - **旧链路删除**：旧系统的 `token_buffer_memory.get_relevant_facts` → `recall_relevant_memories` → Weaviate `UserMemory` 检索链路**已删除**，替换为 `MemoryDigest` → Redis 缓存 → Neo4j 重建。

```python
from __future__ import annotations
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional
import redis.asyncio as aioredis
from pydantic import BaseModel, Field
from neo4j import AsyncDriver
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


# ── 配置 ──────────────────────────────────────────────────
class DigestConfig(BaseModel):
    """
    Digest 配置
    """

    # Redis 缓存
    cache_ttl_seconds: int = Field(default=300, ge=60, description="Digest 缓存过期时间")
    cache_key_prefix: str = Field(default="memory:digest:", description="Redis 键前缀")
    # 渲染控制
    max_tokens: int = Field(default=2000, ge=500, le=8000, description="Digest 最大 token 数")
    profile_max_items: int = Field(default=5, ge=1)
    skills_max_items: int = Field(default=10, ge=1)
    events_max_items: int = Field(default=10, ge=1)
    tasks_max_items: int = Field(default=5, ge=1)
    # LLM
    render_model: str = Field(default="gpt-4o-mini")
    render_temperature: float = Field(default=0.0)
    # ── Digest 模板 ────────────────────────────────────────────
    DIGEST_TEMPLATE = """
      ## 用户画像 {profile}  ## 已习得技能 {skills}  ## 近期事件 {events}  ## 待办任务 {tasks} """

    # ── 核心类 ──────────────────────────────────────────────────
    class DigestManager:
        """
        Memory Digest 管理器 — 维护固定大小的记忆摘要视图。
        Digest 是用户记忆系统的"快照摘要"，用于 System 1 快速路径。
        定期从 TKG、Skill Pool 和近期 Episode 重建。
        缓存策略:
        - Redis Key: {prefix}{user_id}
        - Value: JSON {"text": "...", "tokens": N, "updated_at": "..."}
        - TTL: 由配置决定（默认 5 分钟）
        """

        def __init__(
            self,
            redis: aioredis.Redis,
            neo4j: AsyncDriver,
            llm_client: AsyncOpenAI,
            config: Optional[DigestConfig] = None,
        ) -> None:
            """
            初始化 Digest 管理器。
            Args:
            redis: Redis 异步客户端。
            neo4j: Neo4j 异步驱动。
            llm_client: OpenAI 异步客户端。
            config: Digest 配置。
            """
            self._redis = redis
            self._neo4j = neo4j
            self._llm = llm_client
            self._config = config or DigestConfig()

            async def get_digest(self, user_id: str) -> str:
                """
                获取当前 Digest，缓存未过期则直接返回。
                Args:
                user_id: 用户 ID。
                Returns:
                Digest 文本。缓存未命中时返回空字符串。
                """
                cache_key = f"{self._config.cache_key_prefix}{user_id}"
                cached = await self._redis.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    logger.debug("Digest cache hit for user %s", user_id)
                    return data.get("text", "")
                    # 缓存未命中，触发异步重建
                    logger.debug("Digest cache miss for user %s, rebuilding", user_id)
                    try:
                        digest = await self.update_digest(user_id)
                        return digest
                    except Exception as e:
                        logger.error("Digest rebuild failed for user %s: %s", user_id, e)
                        return ""

                async def update_digest(self, user_id: str) -> str:
                    """
                    重建 Digest：从 TKG + Skill Pool + 近期 Episode 生成。
                    步骤:
                    1. 从 Neo4j 获取用户画像节点
                    2. 从 Neo4j 获取 Skill Pool（已涌现技能）
                    3. 从 Neo4j 获取近期 Episode（按时间排序）
                    4. 从 Neo4j 获取待办任务
                    5. 渲染 Digest 模板
                    6. 计算并检查 token 数
                    7. 写入 Redis 缓存
                    Args:
                    user_id: 用户 ID。
                    Returns:
                    渲染后的 Digest 文本。
                    """
                    # 1. 用户画像
                    profile = await self._fetch_profile(user_id)
                    # 2. 技能
                    skills = await self._fetch_skills(user_id)
                    # 3. 近期事件
                    events = await self._fetch_recent_episodes(user_id)
                    # 4. 待办
                    tasks = await self._fetch_tasks(user_id)
                    # 5. 渲染
                    digest_text = await self._render_digest(profile, skills, events, tasks)
                    # 6. Token 计数
                    token_count = await self._count_tokens(digest_text)
                    if token_count > self._config.max_tokens:
                        digest_text = await self._truncate_digest(
                            digest_text, self._config.max_tokens
                        )
                        # 7. 缓存
                        cache_key = f"{self._config.cache_key_prefix}{user_id}"
                        cache_value = json.dumps(
                            {
                                "text": digest_text,
                                "tokens": token_count,
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                        await self._redis.set(
                            cache_key, cache_value, ex=self._config.cache_ttl_seconds
                        )
                        logger.info("Digest updated for user %s: %d tokens", user_id, token_count)
                        return digest_text

                    async def _fetch_profile(self, user_id: str) -> str:
                        """
                        从 Neo4j 获取用户画像摘要。
                        """
                        cypher = """
                        MATCH (u:User {id: $user_id})
                        OPTIONAL MATCH (u)-[:HAS_TRAIT]->(t:Trait)
                        OPTIONAL MATCH (u)-[:HAS_PREFERENCE]->(p:Preference)
                        RETURN u.name AS name,                collect(DISTINCT t.name) AS traits,                collect(DISTINCT p.name) AS preferences
                        LIMIT 1         """
                        async with self._neo4j.session() as session:
                            result = await session.run(cypher, user_id=user_id)
                            records = await result.data()
                            if not records:
                                return "暂无用户画像数据"
                                r = records[0]
                                traits_str = ", ".join(
                                    r["traits"][: self._config.profile_max_items]
                                )
                                prefs_str = ", ".join(
                                    r["preferences"][: self._config.profile_max_items]
                                )
                                return f"姓名: {r['name']}, 特质: {traits_str}, 偏好: {prefs_str}"

                        async def _fetch_skills(self, user_id: str) -> str:
                            """
                            从 Neo4j 获取用户的 Skill Pool。
                            """
                            cypher = """
                            MATCH (s:Skill)-[:BELONGS_TO]->(u:User {id: $user_id})
                            WHERE s.status = 'active'
                            RETURN s.name AS name, s.maturity AS maturity,                s.use_count AS use_count
                            ORDER BY s.maturity DESC
                            LIMIT $limit
                            """
                            async with self._neo4j.session() as session:
                                result = await session.run(
                                    cypher, user_id=user_id, limit=self._config.skills_max_items
                                )
                                records = await result.data()
                                if not records:
                                    return "暂无已习得技能"
                                    lines = []
                                    for r in records:
                                        lines.append(
                                            f"- {r['name']} (成熟度: {r['maturity']:.1f}, "
                                            f"使用: {r['use_count']}次)"
                                        )
                                        return "\n".join(lines)

                            async def _fetch_recent_episodes(self, user_id: str) -> str:
                                """
                                从 Neo4j 获取近期 Episode。
                                """
                                cypher = """
                                MATCH (e:Episode)-[:BELONGS_TO]->(u:User {id: $user_id})
                                WHERE e.storage_tier IN ['HOT', 'WARM'] OR e.storage_tier IS NULL
                                RETURN e.content AS content, e.created_at AS ts
                                ORDER BY e.created_at DESC
                                LIMIT $limit
                                """
                                async with self._neo4j.session() as session:
                                    result = await session.run(
                                        cypher, user_id=user_id, limit=self._config.events_max_items
                                    )
                                    records = await result.data()
                                    if not records:
                                        return "暂无近期事件"
                                        lines = []
                                        for r in records:
                                            ts_str = (
                                                r["ts"].strftime("%m-%d %H:%M") if r["ts"] else ""
                                            )
                                            lines.append(f"- [{ts_str}] {r['content'][:100]}")
                                            return "\n".join(lines)

                                async def _fetch_tasks(self, user_id: str) -> str:
                                    """
                                    从 Neo4j 获取待办任务。
                                    """
                                    cypher = """
                                    MATCH (t:Task)-[:ASSIGNED_TO]->(u:User {id: $user_id})
                                    WHERE t.status = 'pending'
                                    RETURN t.content AS content, t.due_date AS due
                                    ORDER BY t.due_date ASC NULLS LAST
                                    LIMIT $limit
                                    """
                                    async with self._neo4j.session() as session:
                                        result = await session.run(
                                            cypher,
                                            user_id=user_id,
                                            limit=self._config.tasks_max_items,
                                        )
                                        records = await result.data()
                                        if not records:
                                            return "暂无待办任务"
                                            lines = []
                                            for r in records:
                                                due_str = (
                                                    r["due"].strftime("%m-%d")
                                                    if r["due"]
                                                    else "无截止"
                                                )
                                                lines.append(
                                                    f"- {r['content'][:80]} (截止: {due_str})"
                                                )
                                                return "\n".join(lines)

                                    async def _render_digest(
                                        self,
                                        profile: str,
                                        skills: str,
                                        events: str,
                                        tasks: str,
                                    ) -> str:
                                        """
                                        渲染 Digest 文本，控制在 2K tokens 内。
                                        Args:
                                        profile: 用户画像文本。
                                        skills: 技能列表文本。
                                        events: 近期事件文本。
                                        tasks: 待办任务文本。
                                        Returns:
                                        渲染后的 Digest 文本。
                                        """
                                        text = DIGEST_TEMPLATE.format(
                                            profile=profile,
                                            skills=skills,
                                            events=events,
                                            tasks=tasks,
                                        )
                                        return text

                                        async def _count_tokens(self, text: str) -> int:
                                            """
                                            计算文本的 token 数量。
                                            使用简易估算: 1 token ≈ 1.5 个中文字符 / 4 个英文字符。
                                            生产中应使用 tiktoken。
                                            Args:
                                            text: 待计数的文本。
                                            Returns:
                                            估算的 token 数。
                                            """
                                            try:
                                                import tiktoken

                                                enc = tiktoken.encoding_for_model(
                                                    self._config.render_model
                                                )
                                                return len(enc.encode(text))
                                            except ImportError:
                                                # 回退: 简易估算
                                                cn_chars = sum(
                                                    1 for c in text if "\u4e00" <= c <= "\u9fff"
                                                )
                                                en_chars = len(text) - cn_chars
                                                return int(cn_chars / 1.5 + en_chars / 4.0)

                                            async def _truncate_digest(
                                                self, text: str, max_tokens: int
                                            ) -> str:
                                                """
                                                截断 Digest 以满足 token 预算。
                                                逐段截断，优先保留画像和技能。
                                                Args:
                                                text: 原始 Digest 文本。
                                                max_tokens: 最大 token 数。
                                                Returns:
                                                截断后的文本。
                                                """
                                                sections = text.split("\n## ")
                                                result_parts = []
                                                current_tokens = 0
                                                for section in sections:
                                                    section_tokens = await self._count_tokens(
                                                        section
                                                    )
                                                    if (
                                                        current_tokens + section_tokens
                                                        <= max_tokens
                                                    ):
                                                        result_parts.append(section)
                                                        current_tokens += section_tokens
                                                    else:
                                                        break
                                                        return "\n## ".join(result_parts)
```

---

## 图可视化与用户记忆管理

用户通过图数据库可视化界面管理自己的记忆，无需逐条确认。这是新系统利用图数据库天然优势提供的能力，旧系统的扁平列表无法实现。

### 三层交互设计

```
第一层：聚类视图（默认入口）
  - 按 memory_type 聚类显示 6 个大区块：画像 / 偏好 / 关系 / 事件 / 项目 / 密钥
  - 每个区块显示节点数量 + 最近更新时间
  - 用户点击某个区块进入第二层

第二层：子图视图
  - 展开某个聚类内的记忆节点和关联边
  - 节点按 HebbianDecay 权重排列——高权重大，低权重小
  - 节点颜色按 Tier 分层：HOT(红) / WARM(橙) / COLD(灰)
  - 用户可以拖拽、缩放、点击节点查看详情

第三层：节点详情
  - 点击节点弹出详情面板：
    记忆内容 / 类型 / 置信度 / 来源对话 / 创建时间 / 最后访问时间
    关联节点列表 / 关联强度
    操作按钮：编辑 / 删除 / 降低权重 / 标记为"不再重要"
```

### 节点操作策略

| 操作 | 行为 | 图上效果 |
|---|---|---|
| 删除（软删除） | Neo4j `is_active=false` + 清空 `user_memory.embedding` 列 + Redis 清缓存 | 节点变灰，不参与检索，保留在图中可恢复 |
| 彻底删除 | Neo4j `DETACH DELETE` + 删除 `user_memory` 行 | 节点和关联边从图中消失，不可恢复 |
| 降低权重 | 手动触发 HebbianDecay 强制降级 | 节点缩小，颜色变灰 |
| 编辑内容 | 创建新节点 + 旧节点 `t_invalidated_at=now` | 旧节点变灰，新节点出现，有"更新自"虚线 |

软删除的记忆 30 天后自动彻底清理。

### 性能保障

- 聚类视图最多渲染 6 个区块，无性能问题
- 子图视图限制单次渲染 ≤ 200 节点，超出时按权重截断并提示"显示前 200 条记忆"
- 搜索栏支持按类型、时间范围、关键词筛选
- 图渲染使用前端力导向布局（d3-force 或 vis-network），节点数 > 200 时启用 LOD（Level of Detail）降级

---

## 降级策略

新系统引入 Neo4j、PostgreSQL pgvector、Celery、Redis 四个依赖。每个依赖挂掉时的降级行为：

| 依赖故障 | 写入影响 | 检索影响 | 可视化影响 | 其他影响 |
|---|---|---|---|---|
| Neo4j 挂了 | 记忆事件暂存 Redis 队列，恢复后回放 | 跳过 TKG 图遍历，仅走 pgvector 向量检索 | 显示"记忆图谱暂时不可用"，回退扁平列表 | 巩固任务跳过 |
| PostgreSQL 向量检索不可用（pgvector） | 只写 Neo4j TKG，不写向量 | 跳过向量检索，仅走 TKG 图遍历（Graph-only 模式） | 可用（基于 Neo4j） | Digest 从 Neo4j 直接构建 |
| Celery 没跑 | 读写正常 | 读写正常 | 可用 | 巩固不触发（记忆不整理）；Digest 从 Neo4j 重建（不靠定时刷新） |
| Redis 挂了 | 读写正常（设置回退默认值） | Digest 每次从 Neo4j 重建（延迟增加） | 可用 | Celery broker 失效，巩固暂停 |

### 极端情况：全部新依赖不可用

当 Neo4j + PostgreSQL pgvector + Celery 全部不可用时（如冷启动未配置），记忆功能完全不可用，但**对话功能正常**——对话只是没有记忆注入，不会崩溃。系统启动时检查 Neo4j 连接，不可用则标记 `memory_engine_enabled=False`，跳过所有记忆相关逻辑。

---

## 旧系统替代说明

本存储与检索路径完全替代以下旧系统组件：

| 旧组件 | 替代物 | 说明 |
|---|---|---|
| recall_relevant_memories (UserMemoryService) | MemoryRetriever | 从 pgvector 单路向量检索升级为 TKG 图遍历 + pgvector 向量混合检索 |
| token_buffer_memory.get_relevant_facts | MemoryDigest | 从实时检索 500 tokens 升级为预计算 ~2K tokens 结构化摘要 |
| token_buffer_memory (recent_messages) | 保留（对话管理职责） | 不属于记忆系统，仍由对话管理负责 |
| token_buffer_memory (distant_summary) | 保留（对话管理职责） | 不属于记忆系统，仍由对话管理负责 |
| MemoryVectorService (旧 pgvector) | PostgreSQL pgvector 向量存储 | 记忆向量迁移到 user_memory.embedding 列 |
| user_memory_retrieval_tool | 内部切换到 MemoryRetriever | LangChain 工具接口不变，内部实现替换 |
| MemoryConfirmationCard.vue | 图可视化界面 | 从逐条确认卡片升级为全局图管理 |

