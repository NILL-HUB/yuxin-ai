from unittest.mock import MagicMock, patch

from internal.entity.conductor_entity import ConductorPlan, ConductorMode
from internal.service.conductor_service import ConductorService


class _FakeToolBuilder:
    def build(self, account_id):
        return {
            "candidates": [
                {
                    "source_type": "builtin",
                    "provider_id": "search",
                    "name": "web_search",
                    "description": "search web",
                }
            ]
        }

    def build_ranked_subset(self, candidates):
        return {
            "selected_tools": candidates,
            "backup_tools": [],
            "filtered_out_tools": [],
        }


class _FakeToolSelector:
    def select_tools(self, query, candidates=None, max_tools=5):
        return list(candidates or [])[:1]


class _FakeCostPolicy:
    def build_policy(self, **kwargs):
        return {"allowed": True, "reason": "fake"}


def _service():
    return ConductorService(
        language_model_service=MagicMock(),
        tool_subset_builder=_FakeToolBuilder(),
        tool_selector_service=_FakeToolSelector(),
        cost_policy_service=_FakeCostPolicy(),
    )


def test_conductor_decide_enriches_tool_subset_and_cost_policy():
    service = _service()
    plan = ConductorPlan(
        execution_mode=ConductorMode.SINGLE_AGENT.value,
        intent="analysis",
        complexity="medium",
        reason="test",
    )

    with patch.object(service, "plan", return_value=plan):
        decision = service.decide(
            "查询",
            account_id="account-1",
            budget_level="normal",
            balance_credits=100,
        )

    assert decision["tool_subset"]["selected_tools"][0]["name"] == "web_search"
    assert decision["cost_policy"]["allowed"] is True


def test_conductor_decide_returns_empty_tool_subset_without_builder():
    service = ConductorService(
        language_model_service=MagicMock(),
        tool_subset_builder=None,
        tool_selector_service=None,
        cost_policy_service=None,
    )
    plan = ConductorPlan(
        execution_mode=ConductorMode.DIRECT_ANSWER.value,
        intent="general_qa",
        complexity="simple",
        reason="test",
        direct_answer="ok",
    )

    with patch.object(service, "plan", return_value=plan):
        decision = service.decide("你好")

    assert decision["tool_subset"]["selected_tools"] == []
    assert decision["cost_policy"]["allowed"] is True


def test_conductor_repair_plan_includes_failure_feedback():
    service = _service()
    plan = ConductorPlan(
        execution_mode=ConductorMode.SINGLE_AGENT.value,
        intent="analysis",
        complexity="medium",
        reason="repair",
    )

    with patch.object(service, "plan", return_value=plan) as mock_plan:
        repaired = service.repair_plan(
            "分析数据",
            [{"task_id": "t1", "errors": ["agent_execution_failed"]}],
        )

    assert repaired.reason == "repair"
    assert "agent_execution_failed" in mock_plan.call_args.args[0]
