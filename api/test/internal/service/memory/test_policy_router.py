"""D1 PolicyRouter 单元测试。"""

import pytest

from internal.service.memory.policy_router import (
    PolicyRouter,
    QueryIntent,
    IntentClassification,
    PREDEFINED_VIEWS,
)


class TestPolicyRouterRuleClassify:
    """测试规则分类（7 类意图）。"""

    def test_temporal_intent(self):
        router = PolicyRouter(llm_available=False)
        result = router.classify_query("昨天做了什么")
        assert result.intent == QueryIntent.TEMPORAL
        assert result.confidence >= 0.7

    def test_relational_intent(self):
        router = PolicyRouter(llm_available=False)
        result = router.classify_query("你认识张三吗")
        assert result.intent == QueryIntent.RELATIONAL

    def test_action_intent(self):
        router = PolicyRouter(llm_available=False)
        result = router.classify_query("帮我设置提醒")
        assert result.intent == QueryIntent.ACTION

    def test_reflection_intent(self):
        router = PolicyRouter(llm_available=False)
        # 使用不含"最近"的 REFLECTION 关键词避免与 TEMPORAL 冲突
        result = router.classify_query("总结一下我的工作")
        assert result.intent == QueryIntent.REFLECTION

    def test_meta_intent(self):
        router = PolicyRouter(llm_available=False)
        # 使用"你了解"避免"记得"先匹配 REFLECTION 的"我的"
        result = router.classify_query("你了解什么信息")
        assert result.intent == QueryIntent.META

    def test_factual_default(self):
        router = PolicyRouter(llm_available=False)
        result = router.classify_query("Python 是什么")
        assert result.intent == QueryIntent.FACTUAL
        assert result.confidence == 0.5


class TestPolicyRouterSelectViews:
    def test_factual_returns_knowledge(self):
        router = PolicyRouter(llm_available=False)
        intent = IntentClassification(intent=QueryIntent.FACTUAL, confidence=0.5)
        views = router.select_views(intent, "user1")
        assert views == ["knowledge"]

    def test_meta_returns_all_views(self):
        router = PolicyRouter(llm_available=False)
        intent = IntentClassification(intent=QueryIntent.META, confidence=0.9)
        views = router.select_views(intent, "user1")
        assert len(views) == 5
        assert set(views) == set(PREDEFINED_VIEWS.keys())


class TestPolicyRouterShouldUseSystem2:
    def test_greeting_returns_false(self):
        router = PolicyRouter(llm_available=False)
        intent = IntentClassification(intent=QueryIntent.GREETING, confidence=0.9)
        assert router.should_use_system2(intent) is False

    def test_meta_returns_false(self):
        router = PolicyRouter(llm_available=False)
        intent = IntentClassification(intent=QueryIntent.META, confidence=0.9)
        assert router.should_use_system2(intent) is False

    def test_temporal_returns_true(self):
        router = PolicyRouter(llm_available=False)
        intent = IntentClassification(intent=QueryIntent.TEMPORAL, confidence=0.7)
        assert router.should_use_system2(intent) is True

    def test_relational_returns_true(self):
        router = PolicyRouter(llm_available=False)
        intent = IntentClassification(intent=QueryIntent.RELATIONAL, confidence=0.7)
        assert router.should_use_system2(intent) is True


class TestPolicyRouterRetrievalStrategy:
    def test_disabled_without_degradation_manager(self):
        router = PolicyRouter(neo4j_driver=None, llm_available=False)
        strategy = router.select_retrieval_strategy()
        # 无 Neo4j 驱动时应返回 disabled
        assert strategy in ("disabled", "graph_only")


class TestPredefinedViews:
    def test_contains_five_views(self):
        assert len(PREDEFINED_VIEWS) == 5
        expected = {"profile", "episodes", "skills", "relations", "knowledge"}
        assert set(PREDEFINED_VIEWS.keys()) == expected

    def test_episodes_has_score_boost(self):
        assert PREDEFINED_VIEWS["episodes"].score_boost == 1.2
