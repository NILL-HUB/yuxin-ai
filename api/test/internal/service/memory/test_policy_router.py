"""D1 PolicyRouter 单元测试。"""

import pytest

from internal.service.memory.policy_router import (
    PolicyRouter,
    ConversationIntent,
    IntentClassification,
    PREDEFINED_VIEWS,
)


class TestPolicyRouterRuleClassify:
    """测试规则分类（7 类意图）。"""

    def test_temporal_intent(self):
        router = PolicyRouter(llm_available=False)
        result = router.classify_query("昨天做了什么")
        assert result.intent == ConversationIntent.TEMPORAL
        assert result.confidence >= 0.7

    def test_relational_intent(self):
        router = PolicyRouter(llm_available=False)
        result = router.classify_query("你认识张三吗")
        assert result.intent == ConversationIntent.RELATIONAL

    def test_action_intent(self):
        router = PolicyRouter(llm_available=False)
        result = router.classify_query("帮我设置提醒")
        assert result.intent == ConversationIntent.ACTION

    def test_reflection_intent(self):
        router = PolicyRouter(llm_available=False)
        # 使用不含"最近"的 REFLECTION 关键词避免与 TEMPORAL 冲突
        result = router.classify_query("总结一下我的工作")
        assert result.intent == ConversationIntent.REFLECTION

    def test_meta_intent(self):
        router = PolicyRouter(llm_available=False)
        # 使用"你了解"避免"记得"先匹配 REFLECTION 的"我的"
        result = router.classify_query("你了解什么信息")
        assert result.intent == ConversationIntent.META

    def test_factual_default(self):
        router = PolicyRouter(llm_available=False)
        result = router.classify_query("Python 是什么")
        assert result.intent == ConversationIntent.FACTUAL
        assert result.confidence == 0.5


class TestPolicyRouterSelectViews:
    def test_factual_returns_knowledge(self):
        router = PolicyRouter(llm_available=False)
        intent = IntentClassification(intent=ConversationIntent.FACTUAL, confidence=0.5)
        views = router.select_views(intent, "user1")
        assert views == ["knowledge"]

    def test_meta_returns_all_views(self):
        router = PolicyRouter(llm_available=False)
        intent = IntentClassification(intent=ConversationIntent.META, confidence=0.9)
        views = router.select_views(intent, "user1")
        assert len(views) == len(PREDEFINED_VIEWS)
        assert set(views) == set(PREDEFINED_VIEWS.keys())

    def test_reflection_includes_themes(self):
        """REFLECTION 需主题层聚合证据（2026-10-04 扩展）。"""
        router = PolicyRouter(llm_available=False)
        intent = IntentClassification(intent=ConversationIntent.REFLECTION, confidence=0.9)
        views = router.select_views(intent, "user1")
        assert "themes" in views
        assert "episodes" in views and "profile" in views

    def test_temporal_limits_to_episodes(self):
        router = PolicyRouter(llm_available=False)
        intent = IntentClassification(intent=ConversationIntent.TEMPORAL, confidence=0.9)
        assert router.select_views(intent, "user1") == ["episodes"]


class TestPolicyRouterShouldUseSystem2:
    def test_greeting_returns_false(self):
        router = PolicyRouter(llm_available=False)
        intent = IntentClassification(intent=ConversationIntent.GREETING, confidence=0.9)
        assert router.should_use_system2(intent) is False

    def test_meta_returns_false(self):
        router = PolicyRouter(llm_available=False)
        intent = IntentClassification(intent=ConversationIntent.META, confidence=0.9)
        assert router.should_use_system2(intent) is False

    def test_temporal_returns_true(self):
        router = PolicyRouter(llm_available=False)
        intent = IntentClassification(intent=ConversationIntent.TEMPORAL, confidence=0.7)
        assert router.should_use_system2(intent) is True

    def test_relational_returns_true(self):
        router = PolicyRouter(llm_available=False)
        intent = IntentClassification(intent=ConversationIntent.RELATIONAL, confidence=0.7)
        assert router.should_use_system2(intent) is True


class TestPolicyRouterRetrievalStrategy:
    def test_disabled_without_degradation_manager(self, monkeypatch):
        import internal.service.memory.degradation_manager as degradation_module

        monkeypatch.setattr(degradation_module, "get_degradation_manager", lambda: None)
        router = PolicyRouter(neo4j_driver=None, llm_available=False)
        strategy = router.select_retrieval_strategy()
        # 无 DegradationManager 且无 Neo4j 驱动时应返回 disabled
        assert strategy == "disabled"


class TestPredefinedViews:
    def test_contains_six_views(self):
        """themes（Community 主题层，P5）自 2026-10-04 起纳入视图集。"""
        assert len(PREDEFINED_VIEWS) == 6
        expected = {"profile", "episodes", "skills", "relations", "knowledge", "themes"}
        assert set(PREDEFINED_VIEWS.keys()) == expected

    def test_labels_match_real_graph_schema(self):
        """标签必须照实（设计稿的 Person/Organization/Fact 在图中不存在）。"""
        assert PREDEFINED_VIEWS["profile"].node_labels == ["User", "Trait", "Preference"]
        assert PREDEFINED_VIEWS["episodes"].node_labels == ["Episode"]
        assert PREDEFINED_VIEWS["skills"].node_labels == ["Skill"]
        assert PREDEFINED_VIEWS["relations"].node_labels == ["Entity"]
        assert PREDEFINED_VIEWS["knowledge"].node_labels == ["SemanticMemory"]
        assert PREDEFINED_VIEWS["themes"].node_labels == ["Community"]

    def test_pg_memory_types_declared(self):
        """pgvector 侧过滤取值：只有存在于 user_memory 的视图才声明类型。"""
        assert PREDEFINED_VIEWS["episodes"].pg_memory_types == ["episode"]
        assert PREDEFINED_VIEWS["relations"].pg_memory_types == ["entity"]
        assert set(PREDEFINED_VIEWS["profile"].pg_memory_types) == {
            "preference", "habit", "identity", "goal", "capability"
        }
        assert PREDEFINED_VIEWS["skills"].pg_memory_types == []
        assert PREDEFINED_VIEWS["knowledge"].pg_memory_types == []

    def test_episodes_has_score_boost(self):
        assert PREDEFINED_VIEWS["episodes"].score_boost == 1.2
