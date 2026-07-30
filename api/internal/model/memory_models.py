"""记忆系统统一数据模型层。

模块说明:
    本模块定义记忆系统全部数据模型，统一使用 Pydantic v2 BaseModel 实现。
    合并来自三份设计文档的模型定义，并解决文档间类型冲突：
      - StorageTier 统一为 str Enum（"hot"/"warm"/"cold"/"frozen"），不使用 IntEnum；
      - MemoryEdge 合并文档1四时间戳与文档2访问统计 + 共现计数字段；
      - RetrievalResult 合并两版定义，内含 RetrievalScore 子结构与 evidence_chain。

模型来源映射表:
    ┌──────────────────────────┬─────────────────────────────────────────┐
    │ 模型名称                  │ 来源文档章节                             │
    ├──────────────────────────┼─────────────────────────────────────────┤
    │ EventSource              │ doc1 §1.1                               │
    │ StorageTier              │ doc1 §1.2（统一为 str Enum）             │
    │ NodeType                 │ doc1 §1.3                               │
    │ WritePath                │ doc1 §2.1                               │
    │ SkillStatus              │ doc3                                    │
    │ SkillMaturity            │ doc1 §1.7                               │
    │ ConflictType             │ doc3                                    │
    │ ConsolidationPhase       │ doc3                                    │
    │ QueryIntent              │ doc2                                    │
    │ FunnelLayer              │ doc2                                    │
    │ ViewProfile              │ doc2                                    │
    │ MemoryEvent              │ doc1 §1.1                               │
    │ MemoryNode               │ doc1 §1.3                               │
    │ MemoryEdge               │ doc1 §1.4 + doc2 §5.2（合并字段）       │
    │ ScoreFactors             │ doc1 §2.1                               │
    │ SalienceResult           │ doc1 §1.5（重构为 BaseModel）            │
    │ UserProfile              │ doc1 §1.6                               │
    │ RecentEventSummary       │ doc1 §1.6                               │
    │ TaskStatus               │ doc1 §1.6                               │
    │ MemoryDigest             │ doc1 §1.6                               │
    │ RetrievalScore           │ doc1 §1.8 + doc2（合并）                │
    │ RetrievalResult          │ doc1 §1.8 + doc2（合并）                │
    │ EvidenceItem             │ doc2                                    │
    │ RetrievalOptions         │ doc2                                    │
    │ RetrievalConfig          │ doc2                                    │
    │ SpreadConfig             │ doc2                                    │
    │ FunnelConfig             │ doc2                                    │
    │ DigestConfig             │ doc2                                    │
    │ DecayConfig              │ doc2 §5.2                               │
    │ ColdStorageEntry         │ doc2 §5.3                               │
    │ RebuildResult            │ doc2 §5.3                               │
    │ ConsolidationConfig      │ doc3                                    │
    │ ConsolidationReport      │ doc1 §1.9 + doc3（合并，加 property）    │
    │ ConflictResolution       │ doc1 §1.9 + doc3（合并）                │
    │ ConflictResult           │ doc3                                    │
    │ DedupMerge               │ doc1 §1.9 + doc3（合并）                │
    │ TierTransition           │ doc1 §1.9 + doc3（合并）                │
    │ Skill                    │ doc1 §1.7 + doc3（合并）                │
    │ AuditEntry               │ doc3                                    │
    │ PIIField                 │ doc3                                    │
    │ EntityCandidate          │ doc1 §2.4（重构为 BaseModel）            │
    │ EntityResolutionResult   │ doc1 §2.4（重构为 BaseModel）            │
    └──────────────────────────┴─────────────────────────────────────────┘

文档索引:
    doc1 = docs/prd/memory-system/01-data-models-and-write-path.md
    doc2 = docs/prd/memory-system/02-storage-and-retrieval.md
    doc3 = docs/prd/memory-system/03-consolidation-skill-policy-api.md
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ============================================================
# 枚举定义（全部 str, Enum）
# ============================================================


class EventSource(str, Enum):
    """事件来源枚举。"""

    USER_MESSAGE = "user_message"
    AGENT_ACTION = "agent_action"
    SYSTEM_OBSERVATION = "system_observation"
    EXTERNAL_FEED = "external_feed"


class StorageTier(str, Enum):
    """记忆存储层级，统一为 str Enum（由赫布权重衰减动态决定）。

    - HOT:    高速缓存，实时可访问，存储完整原始内容
    - WARM:   摘要缓存，可快速检索，存储 LLM 生成的摘要
    - COLD:   冷存储，延迟访问，仅保留统计计数器
    - FROZEN: 归档存储，离线可用，仅实体级统计
    """

    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    FROZEN = "frozen"


class NodeType(str, Enum):
    """TKG 节点类型。"""

    EPISODE = "episode"       # 情景记忆节点 -- 记录一次具体经历
    ENTITY = "entity"         # 实体节点 -- 人、组织、概念等
    COMMUNITY = "community"   # 社区节点 -- 高层主题/概念聚合


class WritePath(str, Enum):
    """由显著性评分决定的写入路径。"""

    FULL = "full"        # 完整路径：全量存储
    SUMMARY = "summary"  # 摘要路径：摘要存储
    SKETCH = "sketch"    # 草稿路径：仅写入草稿
    REJECT = "reject"    # 拒绝写入：不持久化


class SkillStatus(str, Enum):
    """技能生命周期状态。"""

    EMERGING = "emerging"   # 涌现中
    ACTIVE = "active"       # 活跃
    STALE = "stale"         # 过时
    ARCHIVED = "archived"   # 已归档


class SkillMaturity(str, Enum):
    """技能成熟度等级。"""

    EMERGING = "emerging"   # 初级：刚从频率扫描中涌现
    ACTIVE = "active"       # 活跃：经过多次成功应用
    STALE = "stale"         # 过时：长期未触发


class ConflictType(str, Enum):
    """冲突类型枚举。"""

    CONTRADICTION = "contradiction"  # 矛盾：新旧事实对立
    REFINEMENT = "refinement"        # 细化：新事实补充旧事实
    DUPLICATE = "duplicate"          # 重复：新旧事实等价
    SUPERSEDE = "supersede"          # 取代：新事实替代旧事实


class ExplicitCategory(str, Enum):
    """显式陈述分类，对应 7 类正则模式库。

    用于 ExplicitStatementDetector 输出与 HebbianDecay 衰减豁免判定：
    - preference/identity/aversion：强豁免（×0.1）
    - habit/goal/capability：中等豁免（×0.5）
    - meta_instruction：不豁免（按原衰减速率）
    """

    PREFERENCE = "preference"            # 偏好：我喜欢/不喜欢...
    HABIT = "habit"                       # 习惯：我习惯/通常...
    IDENTITY = "identity"                 # 身份：我是/我叫...
    AVERSION = "aversion"                 # 厌恶：我讨厌/害怕...
    GOAL = "goal"                         # 目标：我想/我打算...
    META_INSTRUCTION = "meta_instruction"  # 元指令：以后请/记住...
    CAPABILITY = "capability"             # 能力：我擅长/我会...


class ExplicitPolarity(str, Enum):
    """显式陈述极性，用于 DigestManager 分组渲染。"""

    POSITIVE = "positive"  # 正向：喜欢/想要/擅长
    NEGATIVE = "negative"  # 负向：讨厌/害怕/不擅长
    NEUTRAL = "neutral"    # 中性：是/习惯/打算


class ConsolidationPhase(str, Enum):
    """巩固引擎执行阶段。"""

    EXTRACT = "extract"    # 提取：情景→语义
    RESOLVE = "resolve"    # 冲突解决
    MERGE = "merge"        # 冗余合并
    TIER = "tier"          # 层级迁移
    REPORT = "report"      # 报告生成


class QueryIntent(str, Enum):
    """查询意图分类。"""

    FACTUAL = "factual"        # 事实查询
    PROCEDURAL = "procedural"  # 过程查询
    EPISODIC = "episodic"      # 情景查询
    PREFERENCE = "preference"  # 偏好查询
    UNKNOWN = "unknown"        # 未知意图


class FunnelLayer(str, Enum):
    """检索漏斗各层。"""

    RECALL = "recall"      # 召回层
    DEDUP = "dedup"        # 去重层
    RANK = "rank"          # 排序层
    EVIDENCE = "evidence"  # 证据层
    RENDER = "render"      # 渲染层


class ViewProfile(str, Enum):
    """记忆视图配置。"""

    FULL = "full"      # 完整视图
    DIGEST = "digest"  # 摘要视图
    GRAPH = "graph"    # 图视图


# ============================================================
# 核心模型（来自文档1）
# ============================================================


class MemoryEvent(BaseModel):
    """系统接收的原始记忆事件。

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

    event_id: UUID = Field(default_factory=uuid4, description="全局唯一事件标识")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="事件发生时间")
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
    session_id: Optional[str] = Field(default=None, description="会话标识")
    user_id: str = Field(..., description="用户标识，用于多用户隔离")


class MemoryNode(BaseModel):
    """时序知识图谱中的节点，支持 Episode / Entity / Community 三种类型。

    Attributes:
        node_id: 节点全局唯一标识
        node_type: 节点类型
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
        user_id: 用户标识
    """

    node_id: UUID = Field(default_factory=uuid4, description="节点全局唯一标识")
    node_type: NodeType = Field(..., description="节点类型")
    name: str = Field(..., min_length=1, description="节点名称")
    summary: str = Field(default="", description="节点摘要文本")
    content: Optional[str] = Field(default=None, description="完整内容")
    properties: dict[str, Any] = Field(default_factory=dict, description="节点属性字典")
    embedding: Optional[list[float]] = Field(default=None, description="语义嵌入向量")
    tier: StorageTier = StorageTier.HOT
    created_at: datetime = Field(default_factory=datetime.utcnow, description="创建时间")
    last_accessed: datetime = Field(default_factory=datetime.utcnow, description="最后访问时间")
    access_count: int = Field(default=0, description="累计访问次数")
    is_active: bool = Field(default=True, description="节点是否活跃")
    user_id: str = Field(..., description="用户标识")


class MemoryEdge(BaseModel):
    """TKG 中的关系边，合并文档1四时间戳与文档2访问统计 + 共现计数字段。

    四时间戳（双时间模型 Bi-Temporal Model）:
        - t_valid_at:         事实开始有效的时间（"世界状态"时间轴）
        - t_invalidated_at:    事实被推翻/更新的时间（None 表示仍有效）
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
        t_invalidated_at: 事实失效时间（None = 仍有效）
        t_transaction_start: 事务开始时间
        t_transaction_end: 事务结束时间
        created_at: 边创建时间
        last_accessed_at: 最后访问时间
        access_count: 累计访问次数
        cooccurrence_count: 共现计数
        is_active: 边是否活跃
        invalidated_by: 推翻此边的新边 ID（冲突追踪用）
    """

    edge_id: UUID = Field(default_factory=uuid4, description="边全局唯一标识")
    source_id: UUID = Field(..., description="起始节点 ID")
    target_id: UUID = Field(..., description="目标节点 ID")
    relation_type: str = Field(..., min_length=1, description="关系类型")
    properties: dict[str, Any] = Field(default_factory=dict, description="边属性字典")
    weight: float = Field(default=1.0, ge=0.0, le=2.0, description="边权重（赫布学习累积）")
    t_valid_at: datetime = Field(default_factory=datetime.utcnow, description="事实开始有效时间")
    t_invalidated_at: Optional[datetime] = Field(default=None, description="事实失效时间")
    t_transaction_start: datetime = Field(default_factory=datetime.utcnow, description="事务开始时间")
    t_transaction_end: Optional[datetime] = Field(default=None, description="事务结束时间")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="边创建时间")
    last_accessed_at: datetime = Field(default_factory=datetime.utcnow, description="最后访问时间")
    access_count: int = Field(default=0, description="累计访问次数")
    cooccurrence_count: int = Field(default=0, description="共现计数")
    is_active: bool = Field(default=True, description="边是否活跃")
    invalidated_by: Optional[UUID] = Field(default=None, description="推翻此边的新边 ID")


class ScoreFactors(BaseModel):
    """评分因子明细，用于调试和审计。

    六因子模型：在原 5 因子（emotion/novelty/goal_relevance/outcome_impact/rehearsal）
    基础上新增 explicitness，由 ExplicitStatementDetector 前置层传入。
    - 当事件为显式陈述且 0.5 ≤ confidence < 0.85（拉高路径）：explicitness = 0.8
    - 当事件为显式陈述且 confidence ≥ 0.85（快路径）：跳过 SalienceScorer，不进入本结构
    - 其他情况：explicitness = 0.0
    """

    emotion_intensity: float = Field(default=0.0, description="情绪强度因子 [0, 1]")
    novelty: float = Field(default=0.0, description="新颖性因子 [0, 1]")
    goal_relevance: float = Field(default=0.0, description="目标相关性因子 [0, 1]")
    outcome_impact: float = Field(default=0.0, description="结果影响力因子 [0, 1]")
    rehearsal_boost: float = Field(default=0.0, description="复述强化因子 [0, 1]")
    explicitness: float = Field(default=0.0, description="显式陈述因子 [0, 1]，由 ExplicitStatementDetector 传入")


class SalienceResult(BaseModel):
    """SalienceScorer 的评分输出，包含综合显著性得分、各因子明细、写入路径建议。

    Attributes:
        event: 被评分的原始事件
        total_score: 综合显著性得分 [0, 1]
        factors: 各因子明细
        write_path: 由评分决定的写入路径
        reasoning: 评分简要理由（调试/审计用）
    """

    event: Optional[MemoryEvent] = Field(default=None, description="被评分的原始事件")
    total_score: float = Field(..., description="综合显著性得分 [0, 1]")
    factors: ScoreFactors = Field(default_factory=ScoreFactors, description="各因子明细")
    write_path: WritePath = Field(..., description="由评分决定的写入路径")
    reasoning: str = Field(default="", description="评分简要理由")


class ExplicitDetectionResult(BaseModel):
    """ExplicitStatementDetector 的输出，三层决策架构的第一层。

    决策路径：
    - confidence >= fast_path_threshold (0.85)：快路径，直接 FULL 写入，跳过 SalienceScorer
    - boost_threshold (0.5) <= confidence < fast_path_threshold：拉高路径，
      传入 explicitness=0.8 走 6 因子评分
    - confidence < boost_threshold：非显式，走原 5 因子评分（explicitness=0.0）

    Attributes:
        is_explicit: 是否为显式陈述
        category: 显式陈述分类（preference/habit/identity/aversion/goal/meta_instruction/capability）
        polarity: 极性（positive/negative/neutral），用于 DigestManager 分组渲染
        confidence: 置信度 [0, 1]
        subject: 显式陈述的主体（如"苹果"），作为实体种子传入 LedgerWriter
        predicate: 谓词（如"喜欢"），用于关系边构建
        object: 客体（如有），用于三元组关系
        reasoning: 检测理由（调试/审计用）
        fallback_used: 是否使用了降级策略（LLM 不可用时纯正则）
    """

    is_explicit: bool = Field(default=False, description="是否为显式陈述")
    category: Optional[ExplicitCategory] = Field(default=None, description="显式陈述分类")
    polarity: ExplicitPolarity = Field(default=ExplicitPolarity.NEUTRAL, description="极性")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="置信度 [0, 1]")
    subject: Optional[str] = Field(default=None, description="主体（实体种子）")
    predicate: Optional[str] = Field(default=None, description="谓词")
    object: Optional[str] = Field(default=None, description="客体")
    reasoning: str = Field(default="", description="检测理由")
    fallback_used: bool = Field(default=False, description="是否使用了降级策略")


class UserProfile(BaseModel):
    """用户画像摘要。"""

    summary: str = Field(default="", description="用户画像摘要文本")
    traits: list[str] = Field(default_factory=list, description="用户特质列表")
    preferences: list[str] = Field(default_factory=list, description="用户偏好列表")


class RecentEventSummary(BaseModel):
    """近期事件摘要条目。"""

    content: str = Field(..., description="事件内容摘要")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="事件时间")
    importance: float = Field(default=0.0, description="事件重要性 [0, 1]")


class TaskStatus(BaseModel):
    """任务状态条目。"""

    description: str = Field(..., description="任务描述")
    status: str = Field(..., description="任务状态")
    priority: str = Field(..., description="任务优先级")


class MemoryDigest(BaseModel):
    """固定大小（~2K tokens）的结构化记忆摘要视图。

    System 1 路径的核心派生视图，始终在 system prompt 中注入，
    为 LLM 提供"当前世界认知状态"的压缩概览。

    Attributes:
        user_id: 所属用户 ID
        profile: 用户画像摘要文本
        active_skills: 当前最活跃的技能摘要列表
        recent_events: 近期重要事件摘要
        task_status: 当前活跃任务
        total_tokens: 当前 Digest 的 token 计数（用于预算控制）
        updated_at: 最后更新时间
    """

    user_id: str = Field(..., description="所属用户 ID")
    profile: str = Field(default="", description="用户画像摘要文本")
    active_skills: list[str] = Field(
        default_factory=list,
        description="Top N 活跃技能的一句话摘要",
    )
    recent_events: list[RecentEventSummary] = Field(
        default_factory=list, description="近期重要事件摘要"
    )
    task_status: list[TaskStatus] = Field(
        default_factory=list, description="当前活跃任务"
    )
    total_tokens: int = Field(default=0, description="当前 token 总量")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="最后更新时间")


# ============================================================
# 检索模型（来自文档2）
# ============================================================


class RetrievalScore(BaseModel):
    """检索评分的各通道明细。

    Attributes:
        semantic: 语义通道得分（向量余弦相似度）
        keyword: 关键词通道得分（BM25）
        graph: 图通道得分（图遍历路径相关性）
        time_decay: 时间衰减因子
        total: 加权总分
    """

    semantic: float = Field(default=0.0, description="语义通道得分")
    keyword: float = Field(default=0.0, description="关键词通道得分")
    graph: float = Field(default=0.0, description="图通道得分")
    time_decay: float = Field(default=1.0, description="时间衰减因子")
    total: float = Field(default=0.0, description="加权总分")


class EvidenceItem(BaseModel):
    """检索证据条目。"""

    content: str = Field(..., description="证据内容")
    source: str = Field(..., description="证据来源")
    score: float = Field(default=0.0, description="证据得分")
    relevance: str = Field(default="", description="证据相关性说明")


class RetrievalResult(BaseModel):
    """单条检索结果，合并文档1与文档2两版定义。

    内含 RetrievalScore 子结构与 evidence_chain 证据链。

    Attributes:
        memory_id: 记忆 ID
        content: 命中记忆的内容
        score: 综合评分
        source: 命中来源通道（用于调试）
        timestamp: 记忆时间戳
        metadata: 附加元数据
        evidence_chain: 证据链
        score_breakdown: 评分明细
    """

    memory_id: str = Field(..., description="记忆 ID")
    content: str = Field(..., description="命中记忆的内容")
    score: float = Field(..., description="综合评分")
    source: str = Field(default="", description="命中来源通道")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="记忆时间戳")
    metadata: dict[str, Any] = Field(default_factory=dict, description="附加元数据")
    evidence_chain: list[EvidenceItem] = Field(
        default_factory=list, description="证据链"
    )
    score_breakdown: RetrievalScore = Field(
        default_factory=RetrievalScore, description="评分明细"
    )


class RetrievalOptions(BaseModel):
    """检索请求选项。"""

    top_k: int = Field(default=20, description="返回结果数量上限")
    time_range_days: Optional[int] = Field(default=None, description="时间范围（天数）")
    view_names: list[str] = Field(default_factory=list, description="视图名称列表")
    require_evidence: bool = Field(default=False, description="是否要求返回证据链")
    budget_tokens: int = Field(default=2000, description="token 预算上限")


class RetrievalConfig(BaseModel):
    """检索权重与早停配置。"""

    w_cosine: float = Field(default=0.4, description="语义余弦相似度权重")
    w_bm25: float = Field(default=0.3, description="BM25 关键词权重")
    w_graph: float = Field(default=0.3, description="图遍历权重")
    time_decay_half_life_hours: float = Field(
        default=168.0, description="时间衰减半衰期（小时），默认 7 天"
    )
    early_stop_top_k: int = Field(default=10, description="早停 Top K 阈值")
    early_stop_score_gap: float = Field(default=0.15, description="早停分数间隔阈值")


class SpreadConfig(BaseModel):
    """图扩散激活配置。"""

    max_hops: int = Field(default=3, description="最大跳数")
    activation_decay: float = Field(default=0.5, description="激活衰减系数")
    min_activation: float = Field(default=0.01, description="最小激活阈值")
    top_k: int = Field(default=20, description="扩散保留 Top K")


class FunnelConfig(BaseModel):
    """检索漏斗配置。"""

    dedup_similarity_threshold: float = Field(
        default=0.85, description="去重相似度阈值"
    )
    evidence_max_items: int = Field(default=30, description="证据最大条数")
    early_stop_confidence: float = Field(default=0.9, description="早停置信度阈值")
    early_stop_min_items: int = Field(default=3, description="早停最少条数")
    llm_model: str = Field(default="gpt-4o-mini", description="漏斗 LLM 模型")
    llm_temperature: float = Field(default=0.0, description="漏斗 LLM 温度")
    llm_max_tokens: int = Field(default=2000, description="漏斗 LLM 最大 token 数")


class DigestConfig(BaseModel):
    """Memory Digest 配置。"""

    cache_ttl_seconds: int = Field(default=300, description="缓存 TTL（秒）")
    cache_key_prefix: str = Field(default="memory:digest:", description="缓存键前缀")
    max_tokens: int = Field(default=2000, description="Digest 最大 token 数")
    profile_max_items: int = Field(default=5, description="画像最大条数")
    skills_max_items: int = Field(default=10, description="技能最大条数")
    events_max_items: int = Field(default=10, description="事件最大条数")
    tasks_max_items: int = Field(default=5, description="任务最大条数")
    render_model: str = Field(default="gpt-4o-mini", description="渲染 LLM 模型")
    render_temperature: float = Field(default=0.0, description="渲染 LLM 温度")


class DecayConfig(BaseModel):
    """赫布衰减配置。"""

    lambda_decay: float = Field(default=0.05, description="时间衰减系数")
    alpha_cooccurrence: float = Field(default=0.2, description="共现增强系数")
    beta_interference: float = Field(default=0.15, description="干扰惩罚系数")
    cooccurrence_window_hours: int = Field(
        default=168, description="共现统计时间窗口（小时），默认 7 天"
    )
    hot_threshold: float = Field(default=0.7, description="热记忆权重阈值")
    warm_threshold: float = Field(default=0.3, description="温记忆权重阈值")


class ColdStorageEntry(BaseModel):
    """冷存储归档条目。"""

    entry_id: UUID = Field(default_factory=uuid4, description="归档条目唯一标识")
    node_id: UUID = Field(..., description="关联的 TKG 节点 ID")
    user_id: str = Field(..., description="用户标识")
    s3_key: str = Field(default="", description="S3/COS 对象键")
    archived_at: datetime = Field(default_factory=datetime.utcnow, description="归档时间")
    support_count: int = Field(default=0, description="支持计数")
    weight: float = Field(default=0.0, description="归档时权重")
    content: str = Field(default="", description="记忆原始内容（冷存储回热与 Key 重建用）")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="附加元数据（cooccurrence_count 等）"
    )


class RebuildResult(BaseModel):
    """Key 重建结果。"""

    success: bool = Field(default=True, description="是否成功")
    rebuilt_count: int = Field(default=0, description="重建数量")
    errors: list[str] = Field(default_factory=list, description="错误列表")
    duration_s: float = Field(default=0.0, description="执行耗时（秒）")


# ============================================================
# 巩固模型（来自文档3）
# ============================================================


class ConsolidationConfig(BaseModel):
    """巩固引擎配置。"""

    # 阶段 1: 情景→语义
    episode_age_days: int = Field(default=7, description="Episode 转语义的最低年龄（天）")
    semantic_min_examples: int = Field(
        default=3, description="提取语义的最少相似 Episode 数"
    )
    semantic_similarity_threshold: float = Field(default=0.8, description="语义相似度阈值")
    # 阶段 2: 冲突检测
    conflict_check_batch_size: int = Field(default=50, description="冲突检查批大小")
    conflict_similarity_threshold: float = Field(default=0.85, description="冲突相似度阈值")
    # 阶段 3: 层级迁移与合并
    cold_threshold: float = Field(default=0.3, description="冷存储权重阈值")
    merge_similarity_threshold: float = Field(default=0.9, description="合并相似度阈值")
    # LLM 调用
    llm_model: str = Field(default="gpt-4o-mini", description="巩固 LLM 模型")
    llm_temperature: float = Field(default=0.0, description="巩固 LLM 温度")


class ConsolidationReport(BaseModel):
    """巩固引擎单次执行的完整报告。

    Attributes:
        run_id: 本次运行的唯一标识
        started_at: 开始时间
        finished_at: 结束时间
        phases: 各阶段执行结果
        merged_count: 合并数量
        conflicts_resolved: 冲突解决数量
        cold_archived: 冷归档数量
        skills_emerged: 涌现技能数量
        errors: 执行过程中的错误列表
    """

    run_id: UUID = Field(default_factory=uuid4, description="运行唯一标识")
    started_at: datetime = Field(default_factory=datetime.utcnow, description="开始时间")
    finished_at: Optional[datetime] = Field(default=None, description="结束时间")
    phases: dict[str, dict] = Field(
        default_factory=dict, description="各阶段执行结果"
    )
    merged_count: int = Field(default=0, description="合并数量")
    conflicts_resolved: int = Field(default=0, description="冲突解决数量")
    cold_archived: int = Field(default=0, description="冷归档数量")
    skills_emerged: int = Field(default=0, description="涌现技能数量")
    errors: list[str] = Field(default_factory=list, description="错误列表")

    @property
    def total_items_processed(self) -> int:
        """各阶段处理条目总数。"""
        return sum(
            phase.get("count", 0) if isinstance(phase, dict) else 0
            for phase in self.phases.values()
        )

    @property
    def is_success(self) -> bool:
        """本次巩固是否成功（无错误即视为成功）。"""
        return len(self.errors) == 0


class ConflictResolution(BaseModel):
    """冲突解决记录。"""

    conflict_id: UUID = Field(default_factory=uuid4, description="冲突唯一标识")
    type: ConflictType = Field(..., description="冲突类型")
    resolution: str = Field(..., description="解决策略描述")
    winner_id: Optional[UUID] = Field(default=None, description="胜出方 ID")
    loser_id: Optional[UUID] = Field(default=None, description="落败方 ID")
    reason: str = Field(default="", description="解决理由")


class ConflictResult(BaseModel):
    """冲突检测结果。"""

    conflict_id: UUID = Field(default_factory=uuid4, description="冲突唯一标识")
    type: ConflictType = Field(..., description="冲突类型")
    entity_a: str = Field(..., description="实体 A")
    entity_b: str = Field(..., description="实体 B")
    similarity: float = Field(..., description="相似度")
    resolution: Optional[str] = Field(default=None, description="解决策略")


class DedupMerge(BaseModel):
    """冗余合并记录。"""

    source_id: UUID = Field(..., description="源节点 ID（被合并方）")
    target_id: UUID = Field(..., description="目标节点 ID（合并入）")
    similarity: float = Field(..., description="相似度")
    fields_merged: list[str] = Field(default_factory=list, description="合并的字段列表")


class TierTransition(BaseModel):
    """存储层级变更记录。"""

    node_id: UUID = Field(..., description="节点 ID")
    from_tier: StorageTier = Field(..., description="原存储层级")
    to_tier: StorageTier = Field(..., description="新存储层级")
    reason: str = Field(..., description="变更原因")
    weight: float = Field(..., description="变更时权重")
    at_time: datetime = Field(default_factory=datetime.utcnow, description="变更时间")


class Skill(BaseModel):
    """从用户行为数据中涌现的可复用行为模式。

    技能不是预先编程的，而是当同一行为模式重复出现超过阈值后
    自动创建，并通过后续相关经验增量更新逐渐成熟。

    Attributes:
        skill_id: 技能全局唯一标识
        name: 技能名称（如 "code_review_workflow"）
        pattern: 行为模式描述
        frequency: 技能被触发的累计次数
        maturity: 成熟度等级
        status: 生命周期状态
        confidence: 技能置信度 [0, 1]
        last_seen: 最后触发时间
        first_seen: 首次触发时间
        examples: 技能示例列表
    """

    skill_id: UUID = Field(default_factory=uuid4, description="技能唯一标识")
    name: str = Field(..., min_length=1, description="技能名称")
    pattern: str = Field(default="", description="行为模式描述")
    frequency: int = Field(default=0, description="触发累计次数")
    maturity: SkillMaturity = Field(default=SkillMaturity.EMERGING, description="成熟度等级")
    status: SkillStatus = Field(default=SkillStatus.EMERGING, description="生命周期状态")
    confidence: float = Field(default=0.0, description="技能置信度 [0, 1]")
    last_seen: datetime = Field(default_factory=datetime.utcnow, description="最后触发时间")
    first_seen: datetime = Field(default_factory=datetime.utcnow, description="首次触发时间")
    examples: list[str] = Field(default_factory=list, description="技能示例列表")


class AuditEntry(BaseModel):
    """审计日志条目。"""

    entry_id: UUID = Field(default_factory=uuid4, description="审计条目唯一标识")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="审计时间")
    actor: str = Field(..., description="操作者")
    action: str = Field(..., description="操作类型")
    target: str = Field(..., description="操作目标")
    before: Optional[dict[str, Any]] = Field(default=None, description="变更前状态")
    after: Optional[dict[str, Any]] = Field(default=None, description="变更后状态")


class PIIField(BaseModel):
    """PII 字段处理策略（mask/redact/retain）。"""

    field_name: str = Field(..., description="字段名称")
    value: str = Field(..., description="字段值")
    category: str = Field(..., description="PII 类别")
    action: str = Field(..., description="处理动作：mask/redact/retain")


# ============================================================
# 写入辅助模型
# ============================================================


class EntityCandidate(BaseModel):
    """实体消解候选。"""

    name: str = Field(..., description="候选实体名称")
    type: str = Field(default="unknown", description="实体类型")
    aliases: list[str] = Field(default_factory=list, description="别名列表")
    embedding: Optional[list[float]] = Field(default=None, description="语义嵌入向量")
    score: float = Field(default=0.0, description="候选得分")


class EntityResolutionResult(BaseModel):
    """实体消解结果。

    Attributes:
        merged_entity: 合并到的已有实体 ID（None 表示新建）
        candidates: 所有候选列表（调试/审计用）
        confidence: 消解置信度
        method: 消解方法
    """

    merged_entity: Optional[UUID] = Field(
        default=None, description="合并到的已有实体 ID（None 表示新建）"
    )
    candidates: list[EntityCandidate] = Field(
        default_factory=list, description="所有候选列表"
    )
    confidence: float = Field(default=0.0, description="消解置信度")
    method: str = Field(default="", description="消解方法")
