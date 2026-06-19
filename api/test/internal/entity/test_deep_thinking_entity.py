from internal.core.agent.entities.deep_thinking_entity import (
    DeepRouteDecision,
    DeepThinkingIntent,
    StructuredDocumentOutlinePlan,
    StructuredDocumentSectionPlan,
)


class TestDeepThinkingIntent:
    def test_default_should_not_need_deep_thinking(self):
        intent = DeepThinkingIntent()
        assert intent.needs_deep_thinking is False
        assert intent.reason == ""

    def test_explicit_need_with_reason(self):
        intent = DeepThinkingIntent(needs_deep_thinking=True, reason="需要多步推理")
        assert intent.needs_deep_thinking is True
        assert intent.reason == "需要多步推理"


class TestDeepRouteDecisionDefaults:
    def test_all_defaults_false(self):
        decision = DeepRouteDecision()
        assert decision.need_sandbox is False
        assert decision.need_file_io is False
        assert decision.need_execute is False
        assert decision.need_subagent is False
        assert decision.need_artifact_output is False


class TestStructuredDocumentPlans:
    def test_section_plan_defaults(self):
        plan = StructuredDocumentSectionPlan(title="概述")
        assert plan.title == "概述"
        assert plan.purpose == ""
        assert plan.key_points == []

    def test_outline_plan_defaults(self):
        plan = StructuredDocumentOutlinePlan()
        assert plan.document_title == ""
        assert plan.sections == []
