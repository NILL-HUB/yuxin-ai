from unittest.mock import MagicMock, patch

from internal.entity.conductor_entity import ConductorAgentTask, ConductorMode, ConductorPlan
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


# ── 校验失败回喂重试（幻觉 agent_pool 不再让整任务退化为简单问答）──────


def _plan_with_hallucinated_pool() -> ConductorPlan:
    """结构合法但 agent_pool 为真正的幻觉值（不在注册表任何池定义中）→ 校验必失败。

    注意：不能用 "knowledge" 等 DB 注册表里真实存在的池——那些是**合法**的
    （历史 bug 正是硬编码白名单与注册表脱节把它们误判为非法）。
    """
    return ConductorPlan(
        execution_mode=ConductorMode.SINGLE_AGENT.value,
        intent="content_generation",
        complexity="medium",
        reason="bad",
        agents=[
            ConductorAgentTask(
                task_id="t1",
                title="做视频",
                description="把文档做成视频",
                agent_pool="writing_pool_not_exist",
                model_tier="2",
            )
        ],
    )


def test_resolve_valid_agent_pools_matches_registry():
    """合法池集合必须与 Agent 池注册表（含 DB 覆盖）严格同源——防「模型合法输出被判非法」回归。"""
    from internal.entity.agent_pool_entity import AgentSubPoolRegistry
    from internal.entity.conductor_entity import resolve_valid_agent_pools

    registry_names = {pool["name"] for pool in AgentSubPoolRegistry().list_pools()}
    assert resolve_valid_agent_pools() == registry_names


def test_validator_accepts_pool_name_from_registry():
    """注册表中真实存在的池名（含 DB 里的 knowledge 等）必须通过校验。"""
    from internal.entity.agent_pool_entity import AgentSubPoolRegistry
    from internal.entity.conductor_entity import ConductorPlanValidator

    pool_name = AgentSubPoolRegistry().list_pools()[0]["name"]
    plan = ConductorPlan(
        execution_mode=ConductorMode.SINGLE_AGENT.value,
        intent="content_generation",
        complexity="medium",
        reason="ok",
        agents=[
            ConductorAgentTask(
                task_id="t1",
                title="做视频",
                description="把文档做成视频",
                agent_pool=pool_name,
                model_tier="2",
            )
        ],
    )

    ok, err = ConductorPlanValidator.validate(plan)

    assert ok, err


def test_conductor_plan_retries_once_with_validation_feedback():
    """首次校验失败 → 把错误原因回喂模型重试一次；第二次合法则采用（不再回退）。"""
    service = _service()
    invalid = _plan_with_hallucinated_pool()
    valid = ConductorPlan(
        execution_mode=ConductorMode.DIRECT_ANSWER.value,
        intent="general_qa",
        complexity="simple",
        reason="good",
        direct_answer="好的",
    )
    feedback: list[str] = []

    def _fake_invoke_llm(**kwargs):
        feedback.append(kwargs.get("validation_error", ""))
        return object()

    service._invoke_llm = _fake_invoke_llm
    service._to_plan = lambda model: invalid if len(feedback) == 1 else valid

    plan = service.plan("把文档做成视频")

    assert plan is valid
    assert len(feedback) == 2
    assert "invalid agent_pool" in feedback[1]


def test_conductor_plan_falls_back_when_retry_also_invalid():
    """重试后仍校验失败 → 回退 fallback 计划，且只重试一次（不无限烧 token）。"""
    service = _service()
    invalid = _plan_with_hallucinated_pool()
    feedback: list[str] = []

    def _fake_invoke_llm(**kwargs):
        feedback.append(kwargs.get("validation_error", ""))
        return object()

    service._invoke_llm = _fake_invoke_llm
    service._to_plan = lambda model: invalid

    plan = service.plan("把文档做成视频")

    assert plan.intent == "fallback"
    assert plan.execution_mode == ConductorMode.DIRECT_ANSWER.value
    assert len(feedback) == 2
