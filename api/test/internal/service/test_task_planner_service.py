from internal.entity.orchestrator_entity import (
    ExecutionMode,
    RiskLevel,
    RoutingDecision,
)
from internal.service.task_planner_service import TaskPlannerService


def _decision(**kwargs):
    defaults = {
        "intent": "general_qa",
        "complexity": "simple",
        "execution_mode": ExecutionMode.DIRECT_ANSWER.value,
        "risk_level": RiskLevel.SAFE.value,
        "reason": "simple",
        "cost_policy": {"max_agent_count": 3},
    }
    defaults.update(kwargs)
    return RoutingDecision(**defaults)


def test_task_planner_should_create_single_plan_for_direct_answer():
    plan = TaskPlannerService().plan("解释 Python list", _decision())

    assert plan.execution_mode == "direct_answer"
    assert plan.reason == "simple"
    assert len(plan.items) == 1
    assert plan.items[0].agent_pool == "general"
    assert plan.items[0].required_capabilities == []


def test_task_planner_should_create_single_agent_task():
    plan = TaskPlannerService().plan(
        "写一个登录页面",
        _decision(
            intent="frontend_development",
            complexity="medium",
            execution_mode=ExecutionMode.SINGLE_AGENT.value,
            needs_agent=True,
            agent_subset={
                "selected_agents": [
                    {"agent_id": "frontend-agent", "primary_pool": "frontend"}
                ]
            },
        ),
    )

    assert plan.execution_mode == "single_agent"
    assert len(plan.items) == 1
    assert plan.items[0].agent_pool == "frontend"
    assert plan.items[0].required_capabilities == ["frontend_development"]


def test_task_planner_should_create_limited_multi_agent_tasks():
    plan = TaskPlannerService().plan(
        "调研市场并设计落地页和后端接口",
        _decision(
            intent="cross_domain_project",
            complexity="complex",
            execution_mode=ExecutionMode.MULTI_AGENT.value,
            needs_multi_agent=True,
            cost_policy={"max_agent_count": 2},
            agent_subset={
                "matched_pools": ["research", "frontend", "backend"],
            },
        ),
    )

    assert plan.execution_mode == "multi_agent_parallel"
    assert [item.agent_pool for item in plan.items] == ["research", "frontend"]
    assert [item.execution_order for item in plan.items] == [0, 1]


def test_task_planner_should_create_deep_thinking_stage_tasks():
    plan = TaskPlannerService().plan(
        "制定复杂产品战略",
        _decision(
            complexity="complex",
            execution_mode="deep_thinking",
            cost_policy={"max_agent_count": 5},
        ),
    )

    assert plan.execution_mode == "deep_thinking"
    assert [item.agent_pool for item in plan.items] == [
        "research",
        "analysis",
        "synthesis",
    ]
    assert plan.items[1].depends_on == [plan.items[0].task_id]


def test_task_planner_should_block_reject_or_confirm_decisions():
    plan = TaskPlannerService().plan(
        "删除全部数据",
        _decision(
            execution_mode=ExecutionMode.REJECT_OR_CONFIRM.value,
            risk_level=RiskLevel.HIGH.value,
        ),
    )

    assert plan.execution_mode == "blocked"
    assert len(plan.items) == 0
    assert plan.reason == "reject_or_confirm"
