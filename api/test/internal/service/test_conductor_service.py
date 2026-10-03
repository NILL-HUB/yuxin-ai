from unittest.mock import MagicMock, patch

from internal.entity.conductor_entity import ConductorPlan, ConductorMode
from internal.service.conductor_service import ConductorService


class _FakeCostPolicy:
    def build_policy(self, **kwargs):
        return {"allowed": True, "reason": "fake"}


def _service():
    return ConductorService(
        language_model_service=MagicMock(),
        cost_policy_service=_FakeCostPolicy(),
    )


def test_conductor_decide_leaves_tool_subset_to_orchestrator():
    """工具子集不在指挥官层构建（唯一权威入口是 OrchestratorService.build_tool_subset）。"""
    service = _service()
    plan = ConductorPlan(
        execution_mode=ConductorMode.SINGLE_AGENT.value,
        intent="analysis",
        complexity="medium",
        reason="test",
    )

    with patch.object(service, "plan", return_value=plan):
        decision = service.decide("查询", budget_level="normal", balance_credits=100)

    assert decision["tool_subset"] is None
    assert decision["cost_policy"]["allowed"] is True


def test_conductor_should_not_depend_on_tool_selection():
    """指挥官只派活 + 定档位，永不接触工具清单：构造不再依赖工具选择组件。"""
    service = _service()

    assert not hasattr(service, "tool_subset_builder")
    assert not hasattr(service, "tool_selector_service")


def test_conductor_decide_handles_missing_cost_policy_service():
    service = ConductorService(
        language_model_service=MagicMock(),
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

    assert decision["tool_subset"] is None
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


def _fake_model(**kwargs):
    model = MagicMock()
    for key, value in kwargs.items():
        setattr(model, key, value)
    return model


def test_build_model_summary_reads_active_models_directly():
    """模型摘要直查 model_pool_config（不再走向量索引快照），且 cost_tier 取真实档位。"""
    from internal.service import conductor_service as conductor_mod

    fake_model = _fake_model(
        id="m1",
        display_name="GPT-X",
        model_name="gpt-x",
        capabilities=["coding"],
        model_type="chat",
        tier="3",
    )
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.order_by.return_value = query_chain
    query_chain.limit.return_value = query_chain
    query_chain.all.return_value = [fake_model]
    fake_db = MagicMock()
    fake_db.session.query.return_value = query_chain

    with patch("internal.extension.database_extension.db", fake_db):
        summary = conductor_mod._build_model_summary(top_k=5)

    assert summary == [
        {
            "model_id": "m1",
            "model_name": "GPT-X",
            "capabilities": ["coding"],
            "sub_pool": "coding",
            "cost_tier": "3",
            "model_type": "chat",
        }
    ]
    query_chain.limit.assert_called_once_with(5)


def test_build_model_summary_degrades_to_empty_on_failure():
    from internal.service import conductor_service as conductor_mod

    fake_db = MagicMock()
    fake_db.session.query.side_effect = RuntimeError("boom")

    with patch("internal.extension.database_extension.db", fake_db):
        assert conductor_mod._build_model_summary() == []


def test_infer_model_sub_pool_by_capability_and_type():
    from internal.service import conductor_service as conductor_mod

    assert conductor_mod._infer_model_sub_pool(["coding"], "chat") == "coding"
    assert conductor_mod._infer_model_sub_pool(["research"], "chat") == "research"
    assert conductor_mod._infer_model_sub_pool([], "image_generation") == "creative"
    assert conductor_mod._infer_model_sub_pool(["anything"], "chat") == "general"
