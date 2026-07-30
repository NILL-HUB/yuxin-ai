"""D1 PolicyRouter 策略路由器。

查询意图分类、视图选择、System 1/2 路由判定与依赖故障时的降级路由。
该组件不操作 Ledger，仅做决策路由。

意图分类:
    - 规则分类优先（关键词匹配），置信度 < 0.7 时调用 LLM 分类
    - LLM 调用失败时回退到规则分类结果

设计参考:
    docs/prd/memory-system/03-consolidation-skill-policy-api.md §9.1
    docs/prd/memory-system/execution/05-track-d-policy-governance.md D1
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class QueryIntent(str, Enum):
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

    intent: QueryIntent
    confidence: float = Field(ge=0.0, le=1.0)
    entities: list[str] = Field(default_factory=list)
    time_reference: Optional[str] = None


class ViewProfile(BaseModel):
    """视图配置。"""

    view_name: str
    description: str
    node_labels: list[str]
    edge_types: list[str]
    score_boost: float = 1.0


# =========================================================
# 预定义视图（5 个）
# =========================================================

PREDEFINED_VIEWS: dict[str, ViewProfile] = {
    "profile": ViewProfile(
        view_name="profile",
        description="用户画像视图",
        node_labels=["User", "Trait", "Preference"],
        edge_types=["HAS_TRAIT", "HAS_PREFERENCE"],
    ),
    "episodes": ViewProfile(
        view_name="episodes",
        description="事件记忆视图",
        node_labels=["Episode"],
        edge_types=["NEXT", "CAUSED_BY"],
        score_boost=1.2,
    ),
    "skills": ViewProfile(
        view_name="skills",
        description="技能视图",
        node_labels=["Skill"],
        edge_types=["REQUIRES", "BELONGS_TO"],
    ),
    "relations": ViewProfile(
        view_name="relations",
        description="关系网络视图",
        node_labels=["Person", "Organization"],
        edge_types=["KNOWS", "WORKS_WITH", "RELATED_TO"],
    ),
    "knowledge": ViewProfile(
        view_name="knowledge",
        description="知识视图",
        node_labels=["SemanticMemory", "Fact"],
        edge_types=["SUPPORTS", "CONTRADICTS"],
    ),
}


# =========================================================
# 规则分类关键词表
# =========================================================

_RULE_KEYWORDS: list[tuple[QueryIntent, float, list[str]]] = [
    (QueryIntent.TEMPORAL, 0.7, ["昨天", "上周", "前天", "最近", "什么时候", "几号", "哪天", "去年", "今天", "明天"]),
    (QueryIntent.RELATIONAL, 0.7, ["关系", "认识", "朋友", "同事", "谁是", "谁认识", "联系人"]),
    (QueryIntent.ACTION, 0.8, ["帮我", "安排", "设置", "提醒", "创建", "删除", "修改", "添加"]),
    (QueryIntent.REFLECTION, 0.7, ["我最近", "总结", "回顾", "我的", "忙什么", "做了什么", "在做什么"]),
    (QueryIntent.GREETING, 0.9, ["你好", "嗨", "hello", "hi", "早上好", "晚上好", "哈喽"]),
    (QueryIntent.META, 0.7, ["你记得", "你认识", "你知道什么", "记忆", "你了解", "你还知道"]),
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
        """根据意图映射到预定义视图子集。

        Args:
            intent: 意图分类结果
            user_id: 用户标识

        Returns:
            视图名列表（过滤后存在于 PREDEFINED_VIEWS 的）
        """
        mapping: dict[QueryIntent, list[str]] = {
            QueryIntent.FACTUAL: ["knowledge"],
            QueryIntent.TEMPORAL: ["episodes"],
            QueryIntent.RELATIONAL: ["relations"],
            QueryIntent.ACTION: ["profile", "skills"],
            QueryIntent.REFLECTION: ["profile", "episodes", "knowledge"],
            QueryIntent.GREETING: ["profile"],
            QueryIntent.META: list(PREDEFINED_VIEWS.keys()),
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
        if intent.intent in (QueryIntent.GREETING, QueryIntent.META):
            return False
        if intent.intent in (QueryIntent.TEMPORAL, QueryIntent.RELATIONAL, QueryIntent.REFLECTION):
            return True
        if intent.intent == QueryIntent.FACTUAL and intent.confidence < 0.9:
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
            intent=QueryIntent.FACTUAL,
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

            prompt = f"""请对以下用户查询进行意图分类。

查询: {query}

意图类别（只能选一个）:
- factual: 事实查询（询问知识、定义、属性）
- temporal: 时间查询（涉及时间、日期、历史事件）
- relational: 关系查询（询问人/物之间的关系）
- action: 行动指令（要求执行某个操作）
- reflection: 自省（回顾、总结自己的行为）
- greeting: 问候
- meta: 元查询（询问系统知道/记得什么）

请返回 JSON，格式:
{{
  "intent": "factual|temporal|relational|action|reflection|greeting|meta",
  "confidence": 0.0-1.0,
  "entities": ["实体1", "实体2"],
  "time_reference": "时间引用或null"
}}

只返回 JSON，不要其他内容。"""

            llm = LanguageModelService.get_feature_model("memory_policy_routing")
            response = LLMActivityProbe.invoke_with_probe(
                llm, prompt, feature_key="memory_policy_routing"
            )
            content = response.content if hasattr(response, "content") else str(response)

            # 解析 JSON
            data = json.loads(content)
            intent_str = data.get("intent", "factual")
            try:
                intent = QueryIntent(intent_str)
            except ValueError:
                intent = QueryIntent.FACTUAL

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
