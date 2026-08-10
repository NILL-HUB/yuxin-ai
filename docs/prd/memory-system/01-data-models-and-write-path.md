# 数据模型与写入路径 -- 代码实现

> 本文档为主架构文档的子模块，包含数据模型定义与写入路径的完整代码实现。

---

> **v5.1 设计更新（2026-07-09）**
>
> 本文档已更新为反映以下设计决策：
> - **自动写入替代逐条确认**：SalienceScorer 评分后自动写入，不再需要用户逐条确认。用户通过图可视化界面事后管理记忆（详见 [02-storage-and-retrieval.md](./02-storage-and-retrieval.md) §图可视化）。
> - **完全替代旧系统**：旧记忆系统（MemoryCandidateExtractor、MemoryConfidenceTracker、UserMemoryConfirmationService、MemoryCandidate 表）被完全替代并删除，不做向后兼容。
> - **存储切换**：记忆向量存储于 PostgreSQL pgvector（`user_memory.embedding` 列，HNSW 索引）；记忆关系从 PG 扁平表迁移到 Neo4j TKG。

---

## 1. 数据模型

### 1.1 MemoryEvent -- 输入事件

系统接收的原始记忆输入，包含事件标识、来源、内容、上下文窗口等字段。

```python
"""输入事件模型 -- 系统接收的原始记忆输入"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventSource(str, Enum):
    """事件来源枚举"""
    USER_MESSAGE = "user_message"
    AGENT_ACTION = "agent_action"
    SYSTEM_OBSERVATION = "system_observation"
    EXTERNAL_FEED = "external_feed"


class MemoryEvent(BaseModel):
    """
    系统接收的原始记忆事件。

    Attributes:
        event_id: 全局唯一事件标识
        timestamp: 事件发生时间（客户端提供，默认为当前时间）
        source: 事件来源分类
        content: 事件原始文本内容
        context_messages: 上下文窗口中的前序消息（最近 N 条）
        metadata: 可扩展的元数据字典
        session_id: 会话标识，用于关联同一会话的事件
        user_id: 用户标识，多用户隔离
    """

    event_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source: EventSource = EventSource.USER_MESSAGE
    content: str = Field(..., min_length=1, description="事件原始文本内容")
    context_messages: list[str] = Field(
        default_factory=list,
        description="上下文窗口中的前序消息，用于消歧和评分",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="可扩展元数据（如 channel、topic 等）",
    )
    session_id: Optional[str] = Field(default=None)
    user_id: str = Field(..., description="用户标识，用于多用户隔离")
```

### 1.2 StorageTier -- 存储层级枚举

记忆存储层级，由赫布权重衰减动态决定。

```python
"""存储层级枚举 -- 四级存储分层"""


class StorageTier(str, Enum):
    """
    记忆存储层级，由赫布权重衰减动态决定。

    - HOT:   高速缓存，实时可访问，存储完整原始内容
    - WARM:  摘要缓存，可快速检索，存储 LLM 生成的摘要
    - COLD:  冷存储，延迟访问，仅保留统计计数器
    - FROZEN: 归档存储，离线可用，仅实体级统计
    """

    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    FROZEN = "frozen"
```

### 1.3 MemoryNode -- TKG 节点

时序知识图谱中的节点，支持 Episode（情景记忆）、Entity（实体）、Community（社区）三种类型。

```python
"""时序知识图谱节点模型"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class NodeType(str, Enum):
    """TKG 节点类型"""
    EPISODE = "episode"        # 情景记忆节点 -- 记录一次具体经历
    ENTITY = "entity"         # 实体节点 -- 人、组织、概念等
    COMMUNITY = "community"    # 社区节点 -- 高层主题/概念聚合


class MemoryNode(BaseModel):
    """
    时序知识图谱中的节点。

    Attributes:
        node_id: 节点全局唯一标识
        node_type: 节点类型（Episode / Entity / Community）
        name: 节点名称（Entity 为实体名，Episode 为摘要标题）
        summary: 节点摘要文本
        content: 完整内容（仅 Episode 可能为非空）
        properties: Neo4j 节点属性字典
        embedding: 节点的语义嵌入向量
        tier: 当前存储层级
        created_at: 节点创建时间
        last_accessed: 最后访问时间（用于权重衰减计算）
        access_count: 累计访问次数
        is_active: 节点是否活跃（逻辑删除用）
    """

    node_id: UUID = Field(default_factory=uuid4)
    node_type: NodeType = Field(...)
    name: str = Field(..., min_length=1)
    summary: str = Field(default="")
    content: Optional[str] = Field(default=None)
    properties: dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[list[float]] = Field(default=None)
    tier: StorageTier = StorageTier.HOT
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_accessed: datetime = Field(default_factory=datetime.utcnow)
    access_count: int = Field(default=0)
    is_active: bool = Field(default=True)
```

### 1.4 MemoryEdge -- TKG 边

TKG 中的关系边，采用四时间戳的双时间模型（Bi-Temporal Model），支持事实矛盾追踪与历史可追溯。

```python
"""时序知识图谱边模型 -- 含四时间戳的双时间模型"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MemoryEdge(BaseModel):
    """
    TKG 中的关系边，采用四时间戳的双时间模型（Bi-Temporal Model）。

    四时间戳:
        - t_valid_at:         事实开始有效的时间（"世界状态"时间轴）
        - t_invalidated_at:    事实被推翻/更新的时间（null 表示仍有效）
        - t_transaction_start: 数据摄入事务开始时间（"系统"时间轴）
        - t_transaction_end:   数据摄入事务结束时间

    设计要点:
        事实矛盾时不删除旧边，而是将 t_invalidated_at 标记为新事实的 valid_at，
        保留完整历史可追溯，支持任意时间点的世界状态查询。

    Attributes:
        edge_id: 边全局唯一标识
        source_id: 起始节点 ID
        target_id: 目标节点 ID
        relation_type: 关系类型（如 WORKS_AT、KNOWS、PART_OF）
        properties: 边属性字典
        weight: 边权重（赫布学习累积，动态衰减）
        t_valid_at: 事实开始有效时间
        t_invalidated_at: 事实失效时间（null = 仍有效）
        t_transaction_start: 事务开始时间
        t_transaction_end: 事务结束时间
        invalidated_by: 推翻此边的新边 ID（冲突追踪用）
        is_active: 边是否活跃
    """

    edge_id: UUID = Field(default_factory=uuid4)
    source_id: UUID = Field(...)
    target_id: UUID = Field(...)
    relation_type: str = Field(..., min_length=1)
    properties: dict[str, Any] = Field(default_factory=dict)
    weight: float = Field(default=1.0, ge=0.0, le=2.0)
    t_valid_at: datetime = Field(default_factory=datetime.utcnow)
    t_invalidated_at: Optional[datetime] = Field(default=None)
    t_transaction_start: datetime = Field(default_factory=datetime.utcnow)
    t_transaction_end: Optional[datetime] = Field(default=None)
    invalidated_by: Optional[UUID] = Field(default=None)
    is_active: bool = Field(default=True)
```

### 1.5 SalienceResult -- 评分结果

SalienceScorer 的评分输出，包含综合显著性得分、各因子明细、写入路径建议。

```python
"""杏仁核显著性评分结果模型"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from brain_memory.models.event import MemoryEvent
from brain_memory.policy.write_path import WritePath


@dataclass
class SalienceResult:
    """
    SalienceScorer 的评分输出。

    Attributes:
        event: 被评分的原始事件
        total_score: 综合显著性得分 [0, 1]
        emotion_intensity: 情绪强度因子 [0, 1]
        novelty: 新颖性因子 [0, 1]
        goal_relevance: 目标相关性因子 [0, 1]
        outcome_impact: 结果影响力因子 [0, 1]
        rehearsal_boost: 复述强化因子 [0, 1]（累积 bonus）
        write_path: 由评分决定的写入路径
        reasoning: 评分简要理由（调试/审计用）
    """

    event: MemoryEvent
    total_score: float
    emotion_intensity: float
    novelty: float
    goal_relevance: float
    outcome_impact: float
    rehearsal_boost: float
    write_path: WritePath
    reasoning: str = ""
```

### 1.6 MemoryDigest -- 记忆摘要视图

固定大小（~2K tokens）的结构化记忆摘要视图，是 System 1 路径的核心派生视图。

```python
"""Memory Digest -- 固定大小的记忆摘要视图模型"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    """用户画像摘要"""

    preferences: list[str] = Field(default_factory=list, description="用户偏好")
    constraints: list[str] = Field(default_factory=list, description="用户约束")
    goals: list[str] = Field(default_factory=list, description="活跃目标")


class RecentEventSummary(BaseModel):
    """近期事件摘要条目"""

    date: str = Field(..., description="事件日期 (YYYY-MM-DD)")
    summary: str = Field(..., description="事件一句话摘要")


class TaskStatus(BaseModel):
    """任务状态条目"""

    task_id: str = Field(...)
    status: str = Field(..., description="in_progress | pending | completed")
    description: str = Field(...)


class MemoryDigest(BaseModel):
    """
    固定大小（~2K tokens）的结构化记忆摘要视图。

    这是 System 1 路径的核心派生视图，始终在 system prompt 中注入，
    为 LLM 提供"当前世界认知状态"的压缩概览。

    组成:
        - 用户画像: 偏好、约束、目标
        - 活跃技能: Top N 高置信度技能摘要
        - 近期事件: 最近 N 天的重要事件摘要
        - 当前任务: 进行中 / 待跟进

    Attributes:
        user_id: 所属用户 ID
        profile: 用户画像
        top_skills: 当前最活跃的技能摘要列表
        recent_events: 近期重要事件摘要
        active_tasks: 当前活跃任务
        token_count: 当前 Digest 的 token 计数（用于预算控制）
        updated_at: 最后更新时间
        version: Digest 版本号（递增，用于 diff 检测）
    """

    user_id: str = Field(...)
    profile: UserProfile = Field(default_factory=UserProfile)
    top_skills: list[str] = Field(
        default_factory=list,
        description="Top N 活跃技能的一句话摘要",
    )
    recent_events: list[RecentEventSummary] = Field(default_factory=list)
    active_tasks: list[TaskStatus] = Field(default_factory=list)
    token_count: int = Field(default=0, description="当前 token 总量")
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    version: int = Field(default=0)
```

### 1.7 Skill -- 技能模型

从用户行为数据中涌现的可复用行为模式，不是预先编程的，而是当同一行为模式重复出现超过阈值后自动创建。

```python
"""技能模型 -- 从行为数据中涌现的可复用模式"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SkillMaturity(str, Enum):
    """技能成熟度等级"""
    INITIAL = "initial"      # 初级：刚从频率扫描中涌现
    VERIFIED = "verified"    # 已验证：经过多次成功应用
    MATURE = "mature"        # 成熟：高频率、高泛化度、长期验证


class Skill(BaseModel):
    """
    从用户行为数据中涌现的可复用行为模式。

    技能不是预先编程的，而是当同一行为模式重复出现超过阈值后
    自动创建，并通过后续相关经验增量更新逐渐成熟。

    Attributes:
        skill_id: 技能全局唯一标识
        name: 技能名称（如 "code_review_workflow"）
        trigger: 触发条件描述
        steps: 参数化的行为步骤列表
        parameters: 步骤中的可变参数槽
        confidence: 技能置信度 [0, 1]
        maturity: 成熟度等级
        frequency: 技能被触发的累计次数
        success_rate: 技能执行后获得正面反馈的比例
        generalization: 技能在不同上下文中被成功使用的广度
        source_memories: 涌现此技能的来源记忆 ID 列表
        created_at: 技能创建时间
        last_updated: 最后更新时间
    """

    skill_id: UUID = Field(default_factory=uuid4)
    name: str = Field(..., min_length=1)
    trigger: str = Field(default="")
    steps: list[str] = Field(default_factory=list)
    parameters: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    maturity: SkillMaturity = SkillMaturity.INITIAL
    frequency: int = Field(default=0, ge=0)
    success_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    generalization: float = Field(default=0.0, ge=0.0, le=1.0)
    source_memories: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated: datetime = Field(default_factory=datetime.utcnow)
```

### 1.8 RetrievalResult -- 检索结果

检索结果模型，包含语义、关键词、图遍历三通道评分明细。

```python
"""检索结果模型"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional

from brain_memory.models.graph import MemoryNode, MemoryEdge


@dataclass
class RetrievalScore:
    """
    检索评分的各通道明细。

    Attributes:
        semantic: 语义通道得分（向量余弦相似度）
        keyword: 关键词通道得分（BM25）
        graph: 图通道得分（图遍历路径相关性）
        time_decay: 时间衰减因子
        total: 加权总分
    """

    semantic: float = 0.0
    keyword: float = 0.0
    graph: float = 0.0
    time_decay: float = 1.0
    total: float = 0.0


@dataclass
class RetrievalResult:
    """
    单条检索结果。

    Attributes:
        node: 命中的记忆节点
        edges: 关联边列表
        score: 评分明细
        snippet: 检索命中的文本片段（用于上下文注入）
        source: 命中来源通道（用于调试）
    """

    node: MemoryNode
    edges: list[MemoryEdge] = field(default_factory=list)
    score: RetrievalScore = field(default_factory=RetrievalScore)
    snippet: str = ""
    source: str = ""
```

### 1.9 ConsolidationReport -- 巩固报告

巩固引擎单次执行的完整报告，包含冲突解决、冗余合并、层级变更等记录。

```python
"""巩固引擎执行报告模型"""

from __future__ import annotations
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ConflictResolution(BaseModel):
    """单条冲突检测结果"""

    old_edge_id: str
    new_edge_id: str
    resolution: str = Field(..., description="CONTRADICTION | UPDATE | COMPLEMENT")
    invalidated: bool = False


class DedupMerge(BaseModel):
    """单条冗余合并记录"""

    merged_edge_ids: list[str] = Field(default_factory=list)
    new_summary: str = ""
    salience_after_merge: float = 0.0


class TierTransition(BaseModel):
    """存储层级变更记录"""

    node_id: str
    old_tier: str
    new_tier: str
    reason: str


class ConsolidationReport(BaseModel):
    """
    巩固引擎单次执行的完整报告。

    Attributes:
        run_id: 本次运行的唯一标识
        started_at: 开始时间
        finished_at: 结束时间
        duration_seconds: 执行耗时
        conflicts_resolved: 冲突解决记录列表
        edges_invalidated: 被失效的边数量
        dedup_merges: 冗余合并记录列表
        tier_transitions: 层级变更记录列表
        weight_recalculated: 重新计算权重的边数量
        digest_updated: Digest 是否被更新
        skills_updated: 更新的技能数量
        errors: 执行过程中的错误列表
    """

    run_id: str = Field(...)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = Field(default=None)
    duration_seconds: float = Field(default=0.0)
    conflicts_resolved: list[ConflictResolution] = Field(default_factory=list)
    edges_invalidated: int = Field(default=0)
    dedup_merges: list[DedupMerge] = Field(default_factory=list)
    tier_transitions: list[TierTransition] = Field(default_factory=list)
    weight_recalculated: int = Field(default=0)
    digest_updated: bool = Field(default=False)
    skills_updated: int = Field(default=0)
    errors: list[str] = Field(default_factory=list)
```

---

## 2. 写入路径

写入路径描述事件从 SalienceScorer 评分到 LedgerWriter 持久化的完整流程。**SalienceScorer 评分后根据分数自动决定写入路径，无需用户逐条确认**。写入完成后，用户可通过图可视化界面事后管理自己的记忆（查看、编辑、删除），详见 [02-storage-and-retrieval.md](./02-storage-and-retrieval.md) §图可视化。

写入路径由显著性评分阈值决定：

| 评分区间 | 写入路径 | 自动写入内容 |
|---|---|---|
| score > 0.7 | FULL | 完整内容 + 向量 + TKG 图节点（Episode + Entity + 关系边） |
| 0.3 < score ≤ 0.7 | SUMMARY | 摘要 + 向量 + TKG 图节点（精简实体 + 主要关系） |
| score ≤ 0.3 | STATS | 不写入向量与图节点，仅更新实体访问计数器和共现统计 |

核心组件：
- **SalienceScorer**：计算五因子加权显著性得分，路由到写入路径
- **LedgerWriter**：根据写入路径将事件以不同粒度写入 Neo4j TKG + PostgreSQL pgvector 向量列
- **entity_resolution**：TKG 实体消解，融合向量 + BM25 + LLM 三信号判断新实体是创建还是合并

所有写入遵循 append-only 原则，事实矛盾通过双时间戳模型保留历史可追溯，不删除旧数据。

### 2.1 WritePath 枚举与 ScoreFactors

写入路径枚举，由显著性评分决定存储策略；ScoreFactors 用于记录评分因子明细。

```python
"""杏仁核显著性评分器 -- 写入路径的入口过滤器

灵感来源:
    - 生物杏仁核在记忆编码的同时注入情感标签（而非事后标注）
    - Generative Agents (Park et al., 2023) 的三因子检索评分

关键区别:
    Generative Agents 的评分是检索时计算的；本模块在写入时计算，
    作为前置过滤器决定存储策略，而非用于检索排序。
"""

from __future__ import annotations

import math
import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from brain_memory.models.event import MemoryEvent
from brain_memory.models.graph import StorageTier
from brain_memory.config import Settings

logger = logging.getLogger(__name__)


# ============================================================
# 写入路径枚举
# ============================================================

class WritePath(str, Enum):
    """由显著性评分决定的写入路径"""
    FULL = "full"          # 完整路径：全量存储
    SUMMARY = "summary"    # 摘要路径：摘要存储
    STATS = "stats"        # 统计路径：仅更新计数器


# ============================================================
# 评分因子明细
# ============================================================

@dataclass
class ScoreFactors:
    """评分因子明细，用于调试和审计"""
    emotion_intensity: float = 0.0
    novelty: float = 0.0
    goal_relevance: float = 0.0
    outcome_impact: float = 0.0
    rehearsal_boost: float = 0.0


# ============================================================
# LLM 响应模型
# ============================================================

class _EmotionAnalysis(BaseModel):
    """LLM 情感分析的结构化输出"""
    intensity: float = Field(
        ..., ge=0.0, le=1.0,
        description="情绪强度，0=平静，1=极端情绪（狂喜/暴怒/崩溃）",
    )
    valence: str = Field(
        default="neutral",
        description="情绪极性：positive / negative / neutral",
    )
    reasoning: str = Field(default="")


class _NoveltyAnalysis(BaseModel):
    """LLM 新颖性分析的结构化输出"""
    score: float = Field(
        ..., ge=0.0, le=1.0,
        description="新颖性得分，0=完全预期中，1=完全出乎意料",
    )
    reasoning: str = Field(default="")


class _GoalRelevanceAnalysis(BaseModel):
    """LLM 目标相关性分析的结构化输出"""
    score: float = Field(
        ..., ge=0.0, le=1.0,
        description="目标相关性得分，0=无关，1=直接推进当前核心目标",
    )
    reasoning: str = Field(default="")


class _OutcomeImpactAnalysis(BaseModel):
    """LLM 结果影响力分析的结构化输出"""
    score: float = Field(
        ..., ge=0.0, le=1.0,
        description="结果影响力得分，0=无后果，1=不可逆的重大影响",
    )
    reasoning: str = Field(default="")
```

### 2.2 SalienceScorer

杏仁核显著性评分器。在事件写入 Ledger 之前，评估该事件的记忆价值，输出综合显著性得分和写入路径建议。评分基于五个因子的加权求和：情绪强度、新颖性、目标相关性、结果影响力、复述强化。

```python
# ============================================================
# SalienceScorer 主类
# ============================================================

class SalienceScorer:
    """
    杏仁核显著性评分器。

    在事件写入 Ledger 之前，评估该事件的记忆价值，输出综合显著性
    得分和写入路径建议。评分基于五个因子的加权求和。

    Args:
        settings: 全局配置对象
        llm_client: AsyncOpenAI 客户端实例

    Usage:
        scorer = SalienceScorer(settings, llm_client)
        result = await scorer.score(event)
        # result.total_score in [0, 1]
        # result.write_path in [WritePath.FULL, SUMMARY, STATS]
    """

    def __init__(
        self,
        settings: Settings,
        llm_client: AsyncOpenAI,
    ) -> None:
        self._settings = settings
        self._llm = llm_client
        self._weights = settings.salience.weights

    # --------------------------------------------------------
    # 公开接口
    # --------------------------------------------------------

    async def score(self, event: MemoryEvent) -> "SalienceResult":
        """
        对输入事件计算显著性评分。

        Args:
            event: 待评分的 MemoryEvent

        Returns:
            SalienceResult 包含综合得分和写入路径建议

        Raises:
            LLMError: LLM 调用失败时降级为默认中等等分
        """
        # 并行计算四个独立因子（减少延迟）
        import asyncio

        emotion_task = self._emotion_intensity(event)
        novelty_task = self._novelty(event)
        goal_task = self._goal_relevance(event)
        outcome_task = self._outcome_impact(event)

        results = await asyncio.gather(
            emotion_task, novelty_task, goal_task, outcome_task,
            return_exceptions=True,
        )

        # 异常处理：单个因子失败时用 0.5 降级
        factors = ScoreFactors()
        reasonings: list[str] = []

        for idx, (field_name, value) in enumerate(
            zip(
                ["emotion", "novelty", "goal", "outcome"],
                results,
            )
        ):
            if isinstance(value, Exception):
                logger.warning(
                    "评分因子 %s 计算失败，降级为 0.5: %s",
                    field_name, value,
                )
                setattr(factors, [
                    "emotion_intensity", "novelty",
                    "goal_relevance", "outcome_impact",
                ][idx], 0.5)
            else:
                score_val, reasoning = value
                setattr(factors, [
                    "emotion_intensity", "novelty",
                    "goal_relevance", "outcome_impact",
                ][idx], score_val)
                reasonings.append(reasoning)

        # 复述强化（累积因子，从 Redis 读取访问计数）
        rehearsal = await self._rehearsal_boost(event)
        factors.rehearsal_boost = rehearsal

        # 加权求和
        total_score = self._compute_total(factors)

        # 路由到写入路径
        write_path = self.route(total_score)

        from brain_memory.models.event import SalienceResult
        return SalienceResult(
            event=event,
            total_score=total_score,
            emotion_intensity=factors.emotion_intensity,
            novelty=factors.novelty,
            goal_relevance=factors.goal_relevance,
            outcome_impact=factors.outcome_impact,
            rehearsal_boost=factors.rehearsal_boost,
            write_path=write_path,
            reasoning="; ".join(reasonings),
        )

    def route(self, total_score: float) -> WritePath:
        """
        根据综合评分路由到写入路径。

        Args:
            total_score: 综合显著性得分 [0, 1]

        Returns:
            WritePath 枚举值
        """
        thresholds = self._settings.salience.thresholds
        if total_score > thresholds.full_path:
            return WritePath.FULL
        elif total_score > thresholds.summary_path:
            return WritePath.SUMMARY
        else:
            return WritePath.STATS

    # --------------------------------------------------------
    # 内部因子计算方法
    # --------------------------------------------------------

    async def _emotion_intensity(
        self, event: MemoryEvent,
    ) -> tuple[float, str]:
        """
        计算情绪强度因子。

        使用 LLM 分析文本中的情绪极性和强度，
        映射到 [0, 1] 区间。正面或负面极端情绪得更高分。

        Returns:
            (score, reasoning) 元组
        """
        prompt = (
            f"分析以下文本的情绪强度。\n\n"
            f"文本: {event.content}\n"
            f"上下文: {'; '.join(event.context_messages[-3:])}\n\n"
            f"请评估情绪强度（0=完全平静/例行公事，1=极端情绪如狂喜、暴怒、崩溃）。"
            f"注意：即使是正面情绪（如重大成功），高强度也应获得高分。"
        )
        response = await self._call_llm_structured(
            prompt=prompt,
            response_model=_EmotionAnalysis,
        )
        return response.intensity, f"情绪强度={response.intensity:.2f}({response.valence})"

    async def _novelty(
        self, event: MemoryEvent,
    ) -> tuple[float, str]:
        """
        计算新颖性/意外性因子。

        评估当前事件与已有记忆/预期的偏离程度。
        完全重复或例行性事件得低分，意外发现或首次经历得高分。

        新颖性 = 1 - sim(event, expected_scenario)

        Returns:
            (score, reasoning) 元组
        """
        prompt = (
            f"评估以下事件的新颖性/意外程度。\n\n"
            f"当前事件: {event.content}\n"
            f"近期上下文: {'; '.join(event.context_messages[-3:])}\n\n"
            f"请评估：这个事件是否出乎意料、是首次出现还是反复发生？"
            f"（0=完全例行/预期之中，1=完全出乎意料/首次经历）"
        )
        response = await self._call_llm_structured(
            prompt=prompt,
            response_model=_NoveltyAnalysis,
        )
        return response.score, f"新颖性={response.score:.2f}({response.reasoning})"

    async def _goal_relevance(
        self, event: MemoryEvent,
    ) -> tuple[float, str]:
        """
        计算目标相关性因子。

        评估事件与当前活跃目标的语义距离。
        如果事件直接推进或阻碍当前目标，得分更高。

        goal_relevance = max(cos(e_m, e_g)) over active goals

        Returns:
            (score, reasoning) 元组
        """
        prompt = (
            f"评估以下事件与用户当前目标的相关性。\n\n"
            f"事件: {event.content}\n"
            f"上下文: {'; '.join(event.context_messages[-3:])}\n\n"
            f"请评估：这个事件是否与用户的当前任务/目标直接相关？"
            f"（0=完全无关的闲聊，1=直接推进或影响当前核心目标）"
        )
        response = await self._call_llm_structured(
            prompt=prompt,
            response_model=_GoalRelevanceAnalysis,
        )
        return response.score, f"目标相关={response.score:.2f}({response.reasoning})"

    async def _outcome_impact(
        self, event: MemoryEvent,
    ) -> tuple[float, str]:
        """
        计算结果影响力因子。

        评估事件后果的严重性和因果权重。
        不可逆的重大决策或严重错误得高分，无实质影响的事件得低分。

        Returns:
            (score, reasoning) 元组
        """
        prompt = (
            f"评估以下事件的后果严重性/影响力。\n\n"
            f"事件: {event.content}\n"
            f"上下文: {'; '.join(event.context_messages[-3:])}\n\n"
            f"请评估：这个事件带来的后果有多重要？"
            f"（0=无任何实质后果，1=不可逆的重大影响如关键决策、严重错误）"
        )
        response = await self._call_llm_structured(
            prompt=prompt,
            response_model=_OutcomeImpactAnalysis,
        )
        return response.score, f"影响={response.score:.2f}({response.reasoning})"

    async def _rehearsal_boost(self, event: MemoryEvent) -> float:
        """
        计算复述强化因子（累积 bonus）。

        rehearsal_boost = min(1, log(1 + access_count) / log(100))

        基于实体被访问的历史频率，从 Redis 读取计数器。

        Returns:
            复述强化因子 [0, 1]
        """
        try:
            redis = await self._get_redis()
            key = f"bms:access_count:{event.user_id}"
            raw = await redis.get(key)
            if raw is None:
                return 0.0
            access_count = int(raw)
            # min(1, log(1 + count) / log(100))
            # 当 count >= 99 时，boost 达到 1.0
            boost = min(1.0, math.log(1 + access_count) / math.log(100))
            return boost
        except Exception:
            logger.warning("复述强化因子计算失败，降级为 0.0")
            return 0.0

    # --------------------------------------------------------
    # 加权求和
    # --------------------------------------------------------

    def _compute_total(self, factors: ScoreFactors) -> float:
        """
        综合显著性评分加权求和。

        total = w1 * E + w2 * S + w3 * G + w4 * O + w5 * F

        其中前四个因子在写入时一次性计算，F(m) 是累积 bonus。
        使用 min(1.0, ...) 确保总分不超过 1.0。

        Args:
            factors: 各因子得分

        Returns:
            综合得分 [0, 1]
        """
        w = self._weights
        total = (
            w.emotion_intensity * factors.emotion_intensity
            + w.novelty * factors.novelty
            + w.goal_relevance * factors.goal_relevance
            + w.outcome_impact * factors.outcome_impact
            + w.rehearsal_boost * factors.rehearsal_boost
        )
        return min(1.0, total)

    # --------------------------------------------------------
    # LLM 调用封装
    # --------------------------------------------------------

    async def _call_llm_structured(
        self,
        prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel:
        """
        带结构化输出的 LLM 调用封装。

        使用 OpenAI 的 structured output / JSON mode，
        确保返回结果可反序列化为指定的 Pydantic 模型。

        Args:
            prompt: 输入 prompt
            response_model: 期望的响应 Pydantic 模型类型

        Returns:
            反序列化后的 Pydantic 模型实例

        Raises:
            LLMError: 调用失败或解析失败
        """
        try:
            from openai import NOT_GIVEN

            response = await self._llm.chat.completions.create(
                model=self._settings.llm.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个精准的分析器。请严格按照要求的 JSON 格式输出，"
                            "不要添加任何额外文本。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format=(
                    {"type": "json_object"}
                ),
                max_tokens=256,
                temperature=self._settings.llm.temperature,
                timeout=self._settings.llm.request_timeout_s,
            )
            content = response.choices[0].message.content
            if content is None:
                raise ValueError("LLM 返回空内容")
            return response_model.model_validate_json(content)
        except Exception as e:
            logger.error("LLM 结构化调用失败: %s", e)
            raise

    async def _get_redis(self):
        """获取 Redis 连接（延迟导入避免循环依赖）"""
        from brain_memory.infra.redis_client import get_redis
        return await get_redis()
```

### 2.3 LedgerWriter

权威账本层写入总控。根据写入路径（FULL / SUMMARY / STATS），将事件以不同粒度写入 Neo4j TKG 和 PostgreSQL pgvector 向量列。所有写入遵循 append-only 原则。

```python
"""LedgerWriter -- 写入总控，负责将事件写入权威账本层

Ledger 层 = Neo4j (TKG 结构化键) + PostgreSQL pgvector (向量内容值)
所有写入遵循 append-only 原则。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from neo4j import AsyncDriver, AsyncSession
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from brain_memory.models.event import MemoryEvent
from brain_memory.models.graph import MemoryNode, MemoryEdge, NodeType
from brain_memory.config import Settings

logger = logging.getLogger(__name__)


class LedgerWriter:
    """
    权威账本层写入总控。

    根据写入路径（FULL / SUMMARY / STATS），将事件以不同粒度
    写入 Neo4j TKG 和 PostgreSQL pgvector 向量列（user_memory.embedding）。

    Args:
        neo4j_driver: Neo4j 异步驱动
        db_session: SQLAlchemy 异步会话（用于 pgvector 向量读写）
        settings: 全局配置对象

    Usage:
        writer = LedgerWriter(neo4j_driver, db_session, settings)
        result = await writer.write_full_path(event)
    """

    def __init__(
        self,
        neo4j_driver: AsyncDriver,
        db_session: AsyncSession,
        settings: Settings,
    ) -> None:
        self._neo4j = neo4j_driver
        self._db_session = db_session
        self._settings = settings
        # pgvector: 向量存储在 user_memory.embedding 列（Vector(1536)）

    # --------------------------------------------------------
    # 路径 A: 完整路径 (salience > 0.7)
    # --------------------------------------------------------

    async def write_full_path(
        self,
        event: MemoryEvent,
        entities: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        embedding: list[float],
    ) -> dict[str, Any]:
        """
        完整路径写入：全量实体提取 + 完整关系三元组 + 完整内容嵌入。

        存储内容:
            - Neo4j: Episode 节点 + 全量 Entity 节点 + 全量关系边
            - PostgreSQL pgvector: 完整原始内容的嵌入向量（user_memory.embedding）

        Args:
            event: 原始事件
            entities: LLM 提取的实体列表 [{name, type, summary}, ...]
            relations: LLM 提取的关系列表 [{subject, relation, object}, ...]
            embedding: 事件内容的语义嵌入向量

        Returns:
            写入结果摘要 {episode_node_id, entity_count, edge_count, vector_id}
        """
        now = datetime.utcnow()

        # 1. 创建 Episode 节点
        episode_id = await self._create_episode_node(event, now)

        # 2. 创建/合并 Entity 节点 + 关系边
        edge_count = 0
        for entity in entities:
            entity_node_id = await self._merge_entity_node(entity, now)
            # 创建 Episode -> Entity 的 CONTAINS 边
            await self._create_edge(
                source_id=episode_id,
                target_id=entity_node_id,
                relation_type="CONTAINS",
                t_valid_at=now,
            )
            edge_count += 1

        for rel in relations:
            src_node_id = await self._merge_entity_node(
                {"name": rel["subject"], "type": "unknown", "summary": ""},
                now,
            )
            tgt_node_id = await self._merge_entity_node(
                {"name": rel["object"], "type": "unknown", "summary": ""},
                now,
            )
            await self._create_edge(
                source_id=src_node_id,
                target_id=tgt_node_id,
                relation_type=rel["relation"],
                t_valid_at=now,
                properties={"source_episode": str(episode_id)},
            )
            edge_count += 1

        # 3. pgvector 写入完整内容嵌入到 user_memory.embedding 列
        await self._upsert_vector(
            point_id=str(episode_id),
            vector=embedding,
            payload={
                "content": event.content,
                "event_type": "episode",
                "tier": "hot",
                "timestamp": now.isoformat(),
                "user_id": event.user_id,
                "node_id": str(episode_id),
            },
        )

        return {
            "episode_node_id": str(episode_id),
            "entity_count": len(entities),
            "edge_count": edge_count,
            "vector_id": str(episode_id),
        }

    # --------------------------------------------------------
    # 路径 B: 摘要路径 (0.3 < salience <= 0.7)
    # --------------------------------------------------------

    async def write_summary_path(
        self,
        event: MemoryEvent,
        summary: str,
        entities: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        embedding: list[float],
    ) -> dict[str, Any]:
        """
        摘要路径写入：精简实体 + 主要关系 + LLM 摘要嵌入。

        存储内容:
            - Neo4j: Episode 节点（内容为摘要）+ 精简 Entity + 主要关系边
            - PostgreSQL pgvector: LLM 生成摘要的嵌入向量（非原文，user_memory.embedding）

        Args:
            event: 原始事件
            summary: LLM 生成的摘要文本
            entities: 精简实体列表
            relations: 主要关系列表
            embedding: 摘要文本的语义嵌入向量

        Returns:
            写入结果摘要
        """
        now = datetime.utcnow()

        # 创建 Episode 节点，内容为摘要而非原文
        episode_id = await self._create_episode_node(
            event, now, content_override=summary,
        )

        # 创建精简实体和关系
        edge_count = 0
        for entity in entities[:5]:  # 摘要路径限制实体数量
            entity_node_id = await self._merge_entity_node(entity, now)
            await self._create_edge(
                source_id=episode_id,
                target_id=entity_node_id,
                relation_type="CONTAINS",
                t_valid_at=now,
            )
            edge_count += 1

        for rel in relations[:5]:
            src_node_id = await self._merge_entity_node(
                {"name": rel["subject"], "type": "unknown", "summary": ""},
                now,
            )
            tgt_node_id = await self._merge_entity_node(
                {"name": rel["object"], "type": "unknown", "summary": ""},
                now,
            )
            await self._create_edge(
                source_id=src_node_id,
                target_id=tgt_node_id,
                relation_type=rel["relation"],
                t_valid_at=now,
                properties={"source_episode": str(episode_id)},
            )
            edge_count += 1

        # pgvector 写入摘要嵌入（非原文）到 user_memory.embedding 列
        await self._upsert_vector(
            point_id=str(episode_id),
            vector=embedding,
            payload={
                "content": summary,  # 摘要而非原文
                "event_type": "episode_summary",
                "tier": "warm",
                "timestamp": now.isoformat(),
                "user_id": event.user_id,
                "node_id": str(episode_id),
            },
        )

        return {
            "episode_node_id": str(episode_id),
            "entity_count": len(entities[:5]),
            "edge_count": edge_count,
            "vector_id": str(episode_id),
        }

    # --------------------------------------------------------
    # 路径 C: 统计路径 (salience <= 0.3)
    # --------------------------------------------------------

    async def write_stats_path(
        self,
        event: MemoryEvent,
        entities: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        统计路径写入：仅更新实体访问计数器和共现统计。

        存储内容:
            - Neo4j: 仅更新已有 Entity 节点的属性（access_count +1）
            - PostgreSQL pgvector: 不写入

        设计意图:
            低价值事件不占用向量存储空间，但仍维护实体级统计，
            为后续技能涌现和统计挖掘保留信号。

        Args:
            event: 原始事件
            entities: 提到的实体列表（仅更新计数）

        Returns:
            写入结果摘要
        """
        now = datetime.utcnow()
        updated_count = 0

        for entity in entities:
            await self._increment_entity_access(entity["name"], now)
            updated_count += 1

        # 更新共现矩阵（实体对的共现计数 +1）
        for i in range(len(entities)):
            for j in range(i + 1, len(entities)):
                await self._increment_cooccurrence(
                    entities[i]["name"],
                    entities[j]["name"],
                    now,
                )

        # pgvector: 统计路径不写入向量

        return {
            "updated_entities": updated_count,
            "vector_id": None,  # 统计路径不写入向量
        }

    # --------------------------------------------------------
    # Neo4j 内部方法
    # --------------------------------------------------------

    async def _create_episode_node(
        self,
        event: MemoryEvent,
        now: datetime,
        content_override: Optional[str] = None,
    ) -> UUID:
        """
        在 Neo4j 中创建 Episode 节点。

        Args:
            event: 原始事件
            now: 当前时间
            content_override: 如果非空，用此值替代原始内容（摘要路径用）

        Returns:
            创建的节点 ID
        """
        from uuid import uuid4
        node_id = uuid4()
        content = content_override or event.content

        cypher = """
        CREATE (e:Episode {
            node_id: $node_id,
            content: $content,
            summary: $summary,
            source: $source,
            tier: $tier,
            created_at: $created_at,
            last_accessed: $last_accessed,
            access_count: 0,
            is_active: true,
            user_id: $user_id,
            session_id: $session_id
        })
        RETURN e.node_id AS node_id
        """
        async with self._neo4j.session() as session:
            result = await session.run(
                cypher,
                node_id=str(node_id),
                content=content,
                summary=content[:200],  # 前 200 字符作为摘要
                source=event.source.value,
                tier="hot",
                created_at=now.isoformat(),
                last_accessed=now.isoformat(),
                user_id=event.user_id,
                session_id=event.session_id or "",
            )
            record = await result.single()
            logger.info("创建 Episode 节点: %s (tier=hot)", node_id)
            return node_id

    async def _merge_entity_node(
        self,
        entity: dict[str, Any],
        now: datetime,
    ) -> UUID:
        """
        在 Neo4j 中 MERGE Entity 节点（存在则更新，不存在则创建）。

        Args:
            entity: 实体信息 {name, type, summary}
            now: 当前时间

        Returns:
            实体节点 ID
        """
        from uuid import uuid4

        cypher = """
        MERGE (e:Entity {name: $name, user_id: $user_id})
        ON CREATE SET
            e.node_id = $node_id,
            e.type = $type,
            e.summary = $summary,
            e.tier = 'hot',
            e.created_at = $now,
            e.last_accessed = $now,
            e.access_count = 0,
            e.is_active = true
        ON MATCH SET
            e.last_accessed = $now,
            e.access_count = e.access_count + 1
        RETURN e.node_id AS node_id
        """
        node_id = uuid4()
        async with self._neo4j.session() as session:
            result = await session.run(
                cypher,
                name=entity["name"],
                node_id=str(node_id),
                type=entity.get("type", "unknown"),
                summary=entity.get("summary", ""),
                now=now.isoformat(),
                user_id="",  # 需要从上层传入
            )
            record = await result.single()
            return node_id

    async def _create_edge(
        self,
        source_id: UUID,
        target_id: UUID,
        relation_type: str,
        t_valid_at: datetime,
        properties: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        在 Neo4j 中创建关系边（四时间戳）。

        Cypher 查询创建一条带有四时间戳的关系边:
            - t_valid_at: 事实开始有效时间
            - t_invalidated_at: null (当前有效)
            - t_transaction_start / t_transaction_end: 事务时间

        Args:
            source_id: 起始节点 ID
            target_id: 目标节点 ID
            relation_type: 关系类型
            t_valid_at: 有效时间
            properties: 附加属性
        """
        props = properties or {}
        now = datetime.utcnow()
        from uuid import uuid4
        edge_id = uuid4()

        cypher = f"""
        MATCH (s {{node_id: $source_id}})
        MATCH (t {{node_id: $target_id}})
        CREATE (s)-[r:{relation_type} {{
            edge_id: $edge_id,
            t_valid_at: $t_valid_at,
            t_invalidated_at: null,
            t_transaction_start: $tx_start,
            t_transaction_end: $tx_end,
            weight: 1.0,
            is_active: true
        }}]->(t)
        SET r += $properties
        RETURN r.edge_id AS edge_id
        """
        async with self._neo4j.session() as session:
            await session.run(
                cypher,
                source_id=str(source_id),
                target_id=str(target_id),
                edge_id=str(edge_id),
                t_valid_at=t_valid_at.isoformat(),
                tx_start=now.isoformat(),
                tx_end=now.isoformat(),
                properties=props,
            )

    async def _increment_entity_access(
        self, entity_name: str, now: datetime,
    ) -> None:
        """增加指定实体的访问计数（统计路径用）"""
        cypher = """
        MATCH (e:Entity {name: $name})
        SET e.access_count = e.access_count + 1,
            e.last_accessed = $now
        """
        async with self._neo4j.session() as session:
            await session.run(cypher, name=entity_name, now=now.isoformat())

    async def _increment_cooccurrence(
        self, entity_a: str, entity_b: str, now: datetime,
    ) -> None:
        """增加两个实体的共现计数（统计路径用）"""
        cypher = """
        MERGE (a:Entity {name: $name_a})
        MERGE (b:Entity {name: $name_b})
        MERGE (a)-[r:CO_OCCUR_WITH]->(b)
        ON MATCH SET r.count = r.count + 1, r.last_seen = $now
        ON CREATE SET r.count = 1, r.last_seen = $now, r.weight = 0.1
        """
        async with self._neo4j.session() as session:
            await session.run(
                cypher,
                name_a=entity_a,
                name_b=entity_b,
                now=now.isoformat(),
            )

    # --------------------------------------------------------
    # pgvector 内部方法
    # --------------------------------------------------------

    async def _upsert_vector(
        self,
        point_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> None:
        """
        向 user_memory 表 upsert 一条向量记录（pgvector）。

        通过 SQLAlchemy 将 embedding 向量及 payload 字段写入 user_memory 表。
        point_id 与 Neo4j 节点 ID 一致，实现双向关联。

        Args:
            point_id: 向量点 ID（与 Neo4j 节点 ID 一致，实现双向关联）
            vector: 嵌入向量
            payload: 附加载荷（content, tier, timestamp 等）
        """
        # pgvector: 向量存储在 user_memory.embedding 列（Vector(1536)）
        # 使用 SQLAlchemy UPDATE/INSERT 写入 embedding 及 payload 字段
        stmt = text("""
            INSERT INTO user_memory (memory_id, owner_account_id, content,
                                     memory_type, storage_tier, embedding,
                                     created_at, node_id)
            VALUES (:memory_id, :user_id, :content,
                    :event_type, :tier, CAST(:vector AS vector),
                    CAST(:timestamp AS timestamp), :node_id)
            ON CONFLICT (memory_id) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                content = EXCLUDED.content,
                storage_tier = EXCLUDED.storage_tier
        """)
        await self._db_session.execute(stmt, {
            "memory_id": point_id,
            "user_id": payload.get("user_id", ""),
            "content": payload.get("content", ""),
            "event_type": payload.get("event_type", "episode"),
            "tier": payload.get("tier", "hot"),
            "vector": str(vector),
            "timestamp": payload.get("timestamp"),
            "node_id": payload.get("node_id", point_id),
        })
        await self._db_session.commit()
        logger.debug("pgvector upsert: point_id=%s, tier=%s", point_id, payload.get("tier"))
```

### 2.4 TKG 实体消解

实体消解模块，使用向量 + BM25 + LLM 三信号融合判断新实体是创建还是合并到已有实体。

```python
"""TKG 实体消解 -- 向量 + BM25 + LLM 三信号融合

实体消解的目标：给定一个新提取的实体名，判断它是
    (A) 已有实体的别名/变体 -> 合并到已有实体
    (B) 全新的实体 -> 创建新节点

消解策略融合三种信号:
    1. 向量余弦相似度：实体的语义嵌入是否接近
    2. BM25 文本匹配：实体名称的字符串相似度
    3. LLM 判定：在上下文中是否指同一实体
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Optional

from neo4j import AsyncDriver
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from openai import AsyncOpenAI

from brain_memory.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class EntityCandidate:
    """
    实体消解候选。

    Attributes:
        node_id: Neo4j 中已有实体的节点 ID
        name: 已有实体名称
        vector_score: 向量余弦相似度 [0, 1]
        bm25_score: BM25 文本匹配分数 [0, 1]
        llm_score: LLM 判定分数 [0, 1] (0=不同实体, 1=同一实体)
        fused_score: 三信号融合总分 [0, 1]
    """

    node_id: str
    name: str
    vector_score: float = 0.0
    bm25_score: float = 0.0
    llm_score: float = 0.0
    fused_score: float = 0.0


@dataclass
class EntityResolutionResult:
    """
    实体消解结果。

    Attributes:
        is_new: 是否为全新实体（True = 创建新节点）
        matched_node_id: 匹配到的已有实体 ID（is_new=False 时）
        confidence: 消解置信度
        candidates: 所有候选列表（调试/审计用）
    """

    is_new: bool
    matched_node_id: Optional[str] = None
    confidence: float = 0.0
    candidates: list[EntityCandidate] = None

    def __post_init__(self):
        if self.candidates is None:
            self.candidates = []


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
) -> EntityResolutionResult:
    """
    对新提取的实体执行消解。

    流程:
        1. 在 Neo4j 中查找所有同类型实体作为候选集
        2. 对候选集计算向量余弦相似度（pgvector HNSW 检索）
        3. 对候选集计算 BM25 文本匹配分数
        4. 对高分候选调用 LLM 做最终判定
        5. 三信号加权融合，判断是否为同一实体

    融合公式:
        fused = w1 * vector_score + w2 * bm25_score + w3 * llm_score

    Args:
        entity_name: 新实体名称
        entity_type: 新实体类型
        entity_summary: 新实体摘要描述
        embedding: 新实体的语义嵌入向量
        user_id: 用户 ID（多用户隔离）
        neo4j_driver: Neo4j 异步驱动
        db_session: SQLAlchemy 异步会话（用于 pgvector 向量检索）
        llm_client: AsyncOpenAI 客户端
        settings: 全局配置

    Returns:
        EntityResolutionResult 消解结果
    """
    weights = settings.write.entity_resolution

    # Step 1: 从 Neo4j 获取同类型实体候选集
    cypher = """
    MATCH (e:Entity {type: $type, is_active: true})
    RETURN e.node_id AS node_id, e.name AS name, e.summary AS summary
    """
    candidates: list[EntityCandidate] = []
    async with neo4j_driver.session() as session:
        result = await session.run(cypher, type=entity_type)
        records = await result.data()

    for record in records:
        candidates.append(EntityCandidate(
            node_id=record["node_id"],
            name=record["name"],
        ))

    if not candidates:
        return EntityResolutionResult(is_new=True, confidence=1.0)

    # Step 2: 计算向量余弦相似度（通过 pgvector HNSW 检索）
    candidates = await _compute_vector_scores(
        candidates, embedding, db_session, settings,
    )

    # Step 3: 计算 BM25 文本匹配分数
    candidates = _compute_bm25_scores(
        candidates, entity_name, weights.edit_distance_threshold,
    )

    # Step 4: 对高分候选调用 LLM 判定
    candidates = await _compute_llm_scores(
        candidates, entity_name, entity_summary,
        llm_client, settings,
    )

    # Step 5: 三信号融合
    for c in candidates:
        c.fused_score = (
            weights.vector_weight * c.vector_score
            + weights.bm25_weight * c.bm25_score
            + weights.llm_judge_weight * c.llm_score
        )

    # 找到最高分候选
    best = max(candidates, key=lambda c: c.fused_score)

    # 判定阈值：融合得分超过向量合并阈值，认为是同一实体
    if best.fused_score >= weights.merge_threshold:
        return EntityResolutionResult(
            is_new=False,
            matched_node_id=best.node_id,
            confidence=best.fused_score,
            candidates=candidates,
        )
    else:
        return EntityResolutionResult(
            is_new=True,
            confidence=1.0 - best.fused_score,
            candidates=candidates,
        )


async def _compute_vector_scores(
    candidates: list[EntityCandidate],
    query_embedding: list[float],
    db_session: AsyncSession,
    settings: Settings,
) -> list[EntityCandidate]:
    """
    通过 pgvector HNSW 检索计算每个候选的语义相似度。

    将候选实体 node_id 作为过滤条件，在 user_memory.embedding 列上
    执行余弦距离查询（<=> 操作符），用 1 - distance 作为向量通道得分。
    """
    # pgvector: 向量存储在 user_memory.embedding 列，使用 <=> 余弦距离
    for candidate in candidates:
        try:
            stmt = text("""
                SELECT 1 - (embedding <=> CAST(:query_vec AS vector)) AS similarity
                FROM user_memory
                WHERE node_id = :node_id
                LIMIT 1
            """)
            result = await db_session.execute(stmt, {
                "query_vec": str(query_embedding),
                "node_id": candidate.node_id,
            })
            row = result.fetchone()
            if row and row[0] is not None:
                candidate.vector_score = float(row[0])
            else:
                candidate.vector_score = 0.0
        except Exception:
            logger.warning(
                "pgvector 向量检索失败: node_id=%s", candidate.node_id,
            )
            candidate.vector_score = 0.0

    return candidates


def _compute_bm25_scores(
    candidates: list[EntityCandidate],
    query_name: str,
    edit_distance_threshold: int,
) -> list[EntityCandidate]:
    """
    计算 BM25 风格的文本匹配分数。

    使用编辑距离（Levenshtein distance）作为快速相似度指标:
        bm25_score = 1 - min(1, edit_distance / max_len)

    当编辑距离小于阈值时额外加分。
    """
    for candidate in candidates:
        dist = _levenshtein_distance(query_name, candidate.name)
        max_len = max(len(query_name), len(candidate.name))
        if max_len == 0:
            candidate.bm25_score = 1.0
            continue

        raw_score = 1.0 - min(1.0, dist / max_len)

        # 编辑距离小于阈值时加分
        if dist < edit_distance_threshold:
            candidate.bm25_score = min(1.0, raw_score + 0.2)
        else:
            candidate.bm25_score = raw_score

    return candidates


async def _compute_llm_scores(
    candidates: list[EntityCandidate],
    new_name: str,
    new_summary: str,
    llm_client: AsyncOpenAI,
    settings: Settings,
) -> list[EntityCandidate]:
    """
    对向量或 BM25 通道高分候选调用 LLM 做最终判定。

    只对 fused(vector, bm25) >= 0.6 的候选调用 LLM，
    避免对明显不匹配的候选浪费 LLM 调用。
    """
    for candidate in candidates:
        # 跳过低分候选
        preliminary = 0.5 * candidate.vector_score + 0.5 * candidate.bm25_score
        if preliminary < 0.6:
            candidate.llm_score = 0.0
            continue

        prompt = (
            f"判断以下两个实体名称是否指同一个实体。\n\n"
            f"实体 A: \"{new_name}\" -- {new_summary}\n"
            f"实体 B: \"{candidate.name}\"\n\n"
            f"请评估它们是同一实体的概率（0=完全不同，1=确定同一实体）。"
            f"只输出 JSON: {{\"score\": <float>, \"reasoning\": \"<str>\"}}"
        )
        try:
            response = await llm_client.chat.completions.create(
                model=settings.llm.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=128,
                temperature=0.1,
                timeout=settings.llm.request_timeout_s,
            )
            import json
            data = json.loads(response.choices[0].message.content)
            candidate.llm_score = min(1.0, max(0.0, float(data.get("score", 0.0))))
        except Exception:
            logger.warning("LLM 实体判定失败: %s vs %s", new_name, candidate.name)
            candidate.llm_score = 0.0

    return candidates


def _levenshtein_distance(s1: str, s2: str) -> int:
    """
    计算两个字符串的 Levenshtein 编辑距离。

    标准 DP 实现，时间复杂度 O(m*n)。

    Args:
        s1: 字符串 1
        s2: 字符串 2

    Returns:
        编辑距离（整数）
    """
    m, n = len(s1), len(s2)
    # 优化：使用单行 DP
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            if s1[i - 1] == s2[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(prev, dp[j], dp[j - 1])
            prev = temp
    return dp[n]
```

---

### 2.5 Agent-Curated 写入通道（v5.2 新增）

> **对应主文档**：[00-overview.md](./00-overview.md) §16.19.2 基因 4
> **灵感来源**：Hermes Agent — "Agent-curated memory with periodic nudges"
> **实施优先级**：P2

#### 设计思路

当前记忆写入是**系统自动记录**（`AssistantAgentService._write_memory_from_conversation` 每次对话后后台线程触发 `MemoryWriteService`），Agent 本身没有"什么值得记"的自主权。吸纳 Hermes 的 Agent-Curated 机制，形成"系统自动记录（兜底快路径）+ Agent 自主记忆（精准路径）"双通道。

**修正说明**：钰心AI 已有 `user_memory_retriever` 检索工具（让 Agent 检索用户记忆），以下新增的是**写入工具**，与检索工具配套形成完整的 memory tool 家族。

#### 双通道写入

```
现有路径（保持不变）:
  对话结束 → 后台线程 → MemoryWriteService.write_from_event()
  → SalienceScorer 评分 → LedgerWriter 写入（系统自动记录）

新增路径（Agent-Curated）:
  Agent 执行过程中 → 调用 memory tool（新增写入工具）
  │
  ├─ memory_add(content, category?)
  │   → 跳过 SalienceScorer（Agent 已判定有价值）
  │   → 直接走 FULL 写入路径
  │   → metadata 标记 source='agent_curated'
  │
  ├─ memory_replace(old_id, new_content)
  │   → 触发 SUPERSEDE 流程（复用 WriteTimeConflictResolver）
  │
  └─ memory_remove(memory_id)
      → 软删除（status='deprecated'）
      → 记录 Agent 主动遗忘原因
```

#### memory tool 定义

```python
# 新增 LangChain tool，注入 Conductor 的工具集
# 与已有的 user_memory_retriever（检索）配套

@tool
def memory_add(content: str, category: str = "general") -> str:
    """将你认为值得永久记住的信息写入长期记忆。
    
    适用场景: 用户明确表达偏好/习惯/目标、发现可复用问题解决模式、重要决策及原因
    不适用场景: 临时性信息、已有记忆的重复内容
    """
    # 直接走 FULL 路径，跳过 SalienceScorer
    # metadata.source = 'agent_curated', metadata.explicitness = 1.0
    ...

@tool
def memory_replace(memory_id: str, new_content: str, reason: str) -> str:
    """更新已有记忆（旧记忆被标记为 superseded）。"""
    # 复用 WriteTimeConflictResolver 的 SUPERSEDE 流程
    ...
```

#### 与现有架构的融合点

| 现有组件 | 改造方式 |
|---|---|
| `MemoryWriteService.write_from_event()` | **保持不变**（系统自动记录路径） |
| `LedgerWriter` | 新增 `write_agent_curated()` 方法（跳过 SalienceScorer） |
| `WriteTimeConflictResolver` | **复用现有代码**（memory_replace 走 SUPERSEDE） |
| `user_memory_retriever`（检索工具） | **保持不变**，新增 3 个写入工具配套 |
| `UserMemory.metadata_` | 新增 `source` 字段（`system_auto` / `agent_curated`） |

#### 设计约束

> **避免 Agent 滥用 memory tool**：设置每会话 memory_add 上限（默认 5 次），超出时 tool 返回提示"已达本会话记忆上限，请优先更新已有记忆"。

---

### 2.6 周期性 Nudge 触发器（v5.2 新增）

> **对应主文档**：[00-overview.md](./00-overview.md) §16.19.2 基因 5
> **灵感来源**：Hermes Agent — "Agent-curated memory with periodic nudges"
> **实施优先级**：P2
> **依赖**：基因 4（Agent-Curated Memory）— Nudge 是 Agent-Curated 的触发器

#### 设计思路

当前记忆写入是**每次对话都触发**，可能写入大量低价值信息。吸纳 Hermes 的**只在满足条件时 nudge Agent 思考记忆**机制，更精准。Nudge 让 Agent 主动调用 memory tool（基因 4），比"每次对话都触发系统自动记录"更精准。

#### 触发条件（满足任一）

| 条件 | 判定方式 | 说明 |
|---|---|---|
| 复杂任务完成 | tool_call ≥ 5 且任务成功 | 任务中产生了值得总结的经验 |
| 出错后恢复 | error → retry → success | 自我纠错经验值得记忆 |
| 用户纠正 | 检测"否定→重新指令"模式 | 用户纠正意味着 Agent 的认知需要更新 |
| 会话轮次 ≥ 10 | 对话消息数统计 | 长对话可能有遗漏的记忆点 |

#### Nudge Prompt

```
[内部提醒] 本次对话中是否有什么值得永久记住的信息？

请检查以下类型：
1. 用户偏好/习惯（用户明确表达或从行为推断）
2. 重要决策及其原因
3. 可复用的问题解决模式
4. 用户纠正了你之前的错误认知

如果有，请调用 memory_add 写入。
如果没有，忽略此提醒。

注意：不要重复已有记忆，调用 memory_replace 更新而非新增。
```

#### 执行流程

```
对话结束 / 触发条件命中
    │
    ▼
NudgeEvaluator.should_nudge(conversation) → bool
    │
    ▼ [True]
在 PostExecutionHook 中注入 Nudge Prompt
    │
    ▼
Agent（Conductor）收到 Nudge → 自主判断
    │
    ├─ 有价值 → 调用 memory_add / memory_replace（基因 4）
    └─ 无价值 → 忽略（不产生任何写入）
```

#### 配置项（MemoryWriteConfig 新增）

```python
nudge_enabled: bool = True
nudge_min_tool_calls: int = 5
nudge_min_conversation_turns: int = 10
nudge_max_per_session: int = 3  # 每会话最多 nudge 3 次
nudge_model: str = "gpt-4o-mini"  # nudge 条件判定用轻量模型
```

---

## 旧系统替代说明

本写入路径完全替代以下旧系统组件，旧代码已删除：

| 旧组件 | 替代物 | 说明 |
|---|---|---|
| MemoryCandidateExtractor | SalienceScorer | 从 LLM 二元判断升级为五因子量化评分 |
| MemoryConfidenceTracker | SalienceScorer + ConsolidationEngine | 计数累计被评分阈值替代；冲突解决由巩固引擎处理 |
| UserMemoryConfirmationService | 已删除 | 不再需要逐条确认流程 |
| MemoryCandidate 表 (PG) | 已删除 | 不再需要候选累计表 |
| 旧 user_memory.embedding | PostgreSQL pgvector 向量存储 | 记忆向量迁移到 user_memory.embedding 列 |
| token_buffer_memory.get_relevant_facts | MemoryDigest | 详见 [02-storage-and-retrieval.md](./02-storage-and-retrieval.md) |

### 与知识库系统的边界

记忆系统和知识库系统是两个独立系统，职责清晰分离：

| 维度 | 记忆系统 | 知识库系统 |
|---|---|---|
| 解决的问题 | Agent 认知记忆——记住用户画像、偏好、关系、事件 | 知识资产管理——文档上传、RAG 检索、外部数据源同步 |
| 数据来源 | 对话中自动提取 | 用户主动上传 / 管理员配置 / 外部同步 |
| 存储介质 | Neo4j TKG + PostgreSQL pgvector | PostgreSQL（仅关系层） |
| 写入方式 | SalienceScorer 评分后自动写入 | 用户上传 / 管理员手动创建 |
| 检索方式 | MemoryRetriever（图遍历 + 向量混合） | layered_search（分层作用域检索） |
| 用户管理 | 图可视化界面事后 CRUD | 知识库管理页面 CRUD |
| 生命周期 | HebbianDecay 自动衰减 + 巩固引擎整理 | 手动删除 / 禁用 |

两个系统在 ResultSynthesizer 处汇合：记忆片段和知识库片段统一合成，但数据流完全独立。
