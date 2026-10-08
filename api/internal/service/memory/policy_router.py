"""D1 PolicyRouter 策略路由器。

查询意图分类、视图选择、System 1/2 路由判定与依赖故障时的降级路由。
该组件不操作 Ledger，仅做决策路由。

意图分类:
    - 规则分类优先（关键词匹配），置信度 < 0.7 时调用 LLM 分类
    - LLM 调用失败时回退到规则分类结果

接线（2026-10-04）:
    - 消费方：``MemoryRetriever.route_policy`` / ``retrieve_for_chat``——用户侧对话召回
      （``user_memory_recall``）与 admin 侧（``admin_memory_recall``）共用同一入口；
      REST ``POST /memory/retrieve`` 回填 ``intent`` 字段并支持显式 ``view_names``。
    - 对话召回固定 ``llm_available=False``（规则通道微秒级，不占 1.2s 召回预算）；
      LLM 分类仅在显式启用时发生。
    - ``PREDEFINED_VIEWS`` 的 ``node_labels`` / ``pg_memory_types`` 是**检索过滤的唯一事实源**
      （标签/边名照实取自真实 schema，勿改回设计稿的臆想标签）。

设计参考:
    docs/prd/memory-system/03-consolidation-skill-policy-api.md §9.1
    docs/prd/memory-system/02-storage-and-retrieval.md §6.2（策略路由与视图限定）
    docs/prd/memory-system/execution/05-track-d-policy-governance.md D1
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ConversationIntent(str, Enum):
    """查询意图枚举（7 类）。"""

    FACTUAL = "factual"
    TEMPORAL = "temporal"
    RELATIONAL = "relational"
    ACTION = "action"
    REFLECTION = "reflection"
    GREETING = "greeting"
    META = "meta"


class IntentClassification(BaseModel):
    """意图分类结果。"""

    intent: ConversationIntent
    confidence: float = Field(ge=0.0, le=1.0)
    entities: list[str] = Field(default_factory=list)
    time_reference: Optional[str] = None


class ViewProfile(BaseModel):
    """视图配置。

    ``node_labels`` / ``pg_memory_types`` 是**检索过滤的唯一事实源**：
    ``MemoryRetriever`` 用后者把视图限制下推到 Neo4j 标签谓词与 pgvector
    ``user_memory.memory_type`` 过滤（四个召回分支——TKG 全文 / 向量 / Community
    主题 / 图扩展——全部受同一约束，不允许有分支绕过）。
    """

    view_name: str
    description: str
    node_labels: list[str]
    edge_types: list[str]
    score_boost: float = 1.0
    # pgvector 侧：user_memory.memory_type 的允许取值；空列表 = 该视图没有向量行
    # （如 skills / knowledge / themes 只存在于图内），向量分支直接返回空。
    pg_memory_types: list[str] = Field(default_factory=list)


# =========================================================
# 预定义视图（6 个）
# =========================================================

# 2026-10-04 修正：标签与边名**照实**取自真实 schema（`migration/neo4j_init.cypher`
# 的约束/索引 + 各写入点 CREATE/MERGE），不再沿用设计稿中的臆想标签
# （Person / Organization / Fact 等在图里并不存在，会导致视图过滤恒空）。
PREDEFINED_VIEWS: dict[str, ViewProfile] = {
    "profile": ViewProfile(
        view_name="profile",
        description="用户画像视图（落库的 User/Trait/Preference）",
        node_labels=["User", "Trait", "Preference"],
        edge_types=["HAS_TRAIT", "HAS_PREFERENCE", "HAS_EXPLICIT_MEMORY"],
        pg_memory_types=["preference", "habit", "identity", "goal", "capability"],
    ),
    "episodes": ViewProfile(
        view_name="episodes",
        description="事件记忆视图（Episode，含 Episode:MemoryNode）",
        node_labels=["Episode"],
        edge_types=["CONTAINS", "IS_ABSTRACTION_OF", "SUPERSEDED_BY"],
        score_boost=1.2,
        pg_memory_types=["episode"],
    ),
    "skills": ViewProfile(
        view_name="skills",
        description="技能视图（Skill；只存图内，无向量行）",
        node_labels=["Skill"],
        edge_types=["MEMBER_OF"],
    ),
    "relations": ViewProfile(
        view_name="relations",
        description="关系网络视图（Entity 及其共现/归属边）",
        node_labels=["Entity"],
        edge_types=["CO_OCCUR_WITH", "CONTAINS", "MEMBER_OF"],
        pg_memory_types=["entity"],
    ),
    "knowledge": ViewProfile(
        view_name="knowledge",
        description="知识视图（巩固产出的 SemanticMemory，只存图内）",
        node_labels=["SemanticMemory"],
        edge_types=["IS_ABSTRACTION_OF", "MERGED_INTO", "TOPIC_OF"],
    ),
    "themes": ViewProfile(
        view_name="themes",
        description="主题视图（Community 高层主题聚合，P5 新皮层层）",
        node_labels=["Community"],
        edge_types=["TOPIC_OF", "MEMBER_OF", "EVOLVED_INTO", "MERGED_INTO"],
    ),
}


# =========================================================
# 规则分类关键词表
# =========================================================

_RULE_KEYWORDS: list[tuple[ConversationIntent, float, list[str]]] = [
    (ConversationIntent.TEMPORAL, 0.7, ["昨天", "上周", "前天", "最近", "什么时候", "几号", "哪天", "去年", "今天", "明天"]),
    (ConversationIntent.RELATIONAL, 0.7, ["关系", "认识", "朋友", "同事", "谁是", "谁认识", "联系人"]),
    (ConversationIntent.ACTION, 0.8, ["帮我", "安排", "设置", "提醒", "创建", "删除", "修改", "添加"]),
    (ConversationIntent.REFLECTION, 0.7, ["我最近", "总结", "回顾", "我的", "忙什么", "做了什么", "在做什么"]),
    (ConversationIntent.GREETING, 0.9, ["你好", "嗨", "hello", "hi", "早上好", "晚上好", "哈喽"]),
    (ConversationIntent.META, 0.7, ["你记得", "你认识", "你知道什么", "记忆", "你了解", "你还知道"]),
]


class PolicyRouter:
    """策略路由器（同步实现）。

    不使用 ``@inject``：无注入依赖，通过构造函数接收 Neo4j 驱动。
    LLM 调用通过 ``LanguageModelService.get_cheap_chat_model()`` 获取。
    """

    def __init__(self, neo4j_driver=None, llm_available: bool = True) -> None:
        """初始化策略路由器。

        Args:
            neo4j_driver: Neo4j 驱动（同步），用于视图可用性检查
            llm_available: 是否启用 LLM 分类（False 时仅用规则分类）
        """
        self._neo4j_driver = neo4j_driver
        self._llm_available = llm_available

    def classify_query(self, query: str) -> IntentClassification:
        """分类查询意图。

        规则分类优先，置信度 < 0.7 且 LLM 可用时调用 LLM 分类。
        LLM 失败时回退到规则分类结果。

        Args:
            query: 用户查询文本

        Returns:
            IntentClassification 意图分类结果
        """
        rule_result = self._rule_classify(query)

        # 规则置信度足够，直接返回
        if rule_result.confidence >= 0.7:
            return rule_result

        # LLM 不可用或失败，返回规则结果
        if not self._llm_available:
            return rule_result

        try:
            llm_result = self._llm_classify(query)
            if llm_result is not None:
                return llm_result
        except Exception:
            logger.warning("PolicyRouter: LLM 分类失败，回退到规则分类", exc_info=True)

        return rule_result

    def select_views(self, intent: IntentClassification, user_id: str) -> list[str]:
        """根据意图映射到预定义视图子集（检索视图限制的唯一事实源）。

        Args:
            intent: 意图分类结果
            user_id: 主体标识（保留参数：当前视图集合与主体无关，未来若需按主体
                可用性裁剪视图再启用）

        Returns:
            视图名列表（过滤后存在于 PREDEFINED_VIEWS 的）；映射之外一律回退
            ``["knowledge"]``，保证任何意图都有可检索的视图集。
        """
        mapping: dict[ConversationIntent, list[str]] = {
            ConversationIntent.FACTUAL: ["knowledge"],
            ConversationIntent.TEMPORAL: ["episodes"],
            ConversationIntent.RELATIONAL: ["relations"],
            ConversationIntent.ACTION: ["profile", "skills"],
            # REFLECTION（自省/总结）额外纳入 themes：回顾类提问需要主题层聚合证据
            # （2026-10-04 扩展；原设计写于 Community 层落地之前）。
            ConversationIntent.REFLECTION: ["profile", "episodes", "knowledge", "themes"],
            ConversationIntent.GREETING: ["profile"],
            ConversationIntent.META: list(PREDEFINED_VIEWS.keys()),
        }

        views = mapping.get(intent.intent, ["knowledge"])
        return [v for v in views if v in PREDEFINED_VIEWS]

    def should_use_system2(self, intent: IntentClassification) -> bool:
        """判断是否应使用 System 2 深度路径。

        GREETING / META → False（System 1 足够）
        TEMPORAL / RELATIONAL / REFLECTION → True
        FACTUAL 且 confidence < 0.9 → True
        其余 → False

        Args:
            intent: 意图分类结果

        Returns:
            True 表示使用 System 2，False 表示 System 1
        """
        if intent.intent in (ConversationIntent.GREETING, ConversationIntent.META):
            return False
        if intent.intent in (ConversationIntent.TEMPORAL, ConversationIntent.RELATIONAL, ConversationIntent.REFLECTION):
            return True
        if intent.intent == ConversationIntent.FACTUAL and intent.confidence < 0.9:
            return True
        return False

    def select_retrieval_strategy(self) -> str:
        """根据依赖健康状态返回降级策略。

        委托 DegradationManager 获取状态，未初始化时尝试直接检查 Neo4j。

        Returns:
            "full" | "vector_only" | "graph_only" | "digest_only" | "disabled"
        """
        from internal.service.memory.degradation_manager import get_degradation_manager

        dm = get_degradation_manager()
        if dm is not None:
            return dm.get_retrieval_strategy()

        # DegradationManager 未初始化，降级直接检查 Neo4j
        neo4j_ok = self._check_neo4j_quick()
        if neo4j_ok:
            return "graph_only"
        return "disabled"

    # =========================================================
    # 内部方法
    # =========================================================

    @staticmethod
    def _rule_classify(query: str) -> IntentClassification:
        """基于关键词匹配的规则分类。

        Args:
            query: 用户查询文本

        Returns:
            IntentClassification 分类结果
        """
        query_lower = query.lower()

        for intent, confidence, keywords in _RULE_KEYWORDS:
            for kw in keywords:
                if kw in query_lower:
                    return IntentClassification(
                        intent=intent,
                        confidence=confidence,
                        entities=[],
                        time_reference=None,
                    )

        # 默认 → FACTUAL
        return IntentClassification(
            intent=ConversationIntent.FACTUAL,
            confidence=0.5,
            entities=[],
            time_reference=None,
        )

    def _llm_classify(self, query: str) -> Optional[IntentClassification]:
        """使用 LLM 进行意图分类。

        Args:
            query: 用户查询文本

        Returns:
            IntentClassification 或 None（调用失败时）
        """
        try:
            from internal.service.language_model_service import LanguageModelService
            from internal.service.memory.llm_activity_probe import LLMActivityProbe
            from internal.service.system_prompt_library_service import SystemPromptLibraryService

            prompt = SystemPromptLibraryService().get_prompt_or_default(
                "memory_query_intent_prompt"
            ).format(query=query)

            llm = LanguageModelService.get_feature_model("memory_policy_routing")
            response = LLMActivityProbe.invoke_with_probe(
                llm, prompt, feature_key="memory_policy_routing"
            )
            content = response.content if hasattr(response, "content") else str(response)

            # 解析 JSON
            data = json.loads(content)
            intent_str = data.get("intent", "factual")
            try:
                intent = ConversationIntent(intent_str)
            except ValueError:
                intent = ConversationIntent.FACTUAL

            confidence = float(data.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))

            entities = data.get("entities", []) or []
            time_ref = data.get("time_reference")
            if time_ref == "null":
                time_ref = None

            return IntentClassification(
                intent=intent,
                confidence=confidence,
                entities=entities,
                time_reference=time_ref,
            )
        except Exception:
            logger.warning("PolicyRouter._llm_classify: LLM 调用失败", exc_info=True)
            return None

    def _check_neo4j_quick(self) -> bool:
        """快速检查 Neo4j 连通性（不带超时，仅供降级时使用）。"""
        if self._neo4j_driver is None:
            return False
        try:
            with self._neo4j_driver.session() as session:
                session.run("RETURN 1").consume()
            return True
        except Exception:
            return False
