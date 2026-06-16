from internal.service.cost_policy_service import CostPolicyService


def test_cost_policy_should_use_cheap_model_for_simple_task():
    policy = CostPolicyService().build_policy(
        task_complexity="simple",
        budget_level="normal",
        balance_credits=10,
        deep_thinking_requested=False,
    )

    assert policy == {
        "allowed": True,
        "model_tier": "cheap",
        "max_agent_count": 1,
        "max_tool_count": 3,
        "deep_thinking": False,
        "reason": "simple_task_low_cost",
    }


def test_cost_policy_should_allow_strong_model_and_deep_thinking_for_complex_task():
    policy = CostPolicyService().build_policy(
        task_complexity="complex",
        budget_level="normal",
        balance_credits=10,
        deep_thinking_requested=True,
    )

    assert policy["allowed"] is True
    assert policy["model_tier"] == "strong"
    assert policy["deep_thinking"] is True
    assert policy["max_agent_count"] == 5


def test_cost_policy_should_downgrade_for_low_budget():
    policy = CostPolicyService().build_policy(
        task_complexity="complex",
        budget_level="low",
        balance_credits=10,
        deep_thinking_requested=True,
    )

    assert policy["allowed"] is True
    assert policy["model_tier"] == "cheap"
    assert policy["deep_thinking"] is False
    assert policy["max_agent_count"] == 2
    assert policy["reason"] == "budget_downgraded"


def test_cost_policy_should_reject_when_balance_is_insufficient():
    policy = CostPolicyService(minimum_balance_credits=0.5).build_policy(
        task_complexity="medium",
        budget_level="normal",
        balance_credits=0.1,
        deep_thinking_requested=False,
    )

    assert policy == {
        "allowed": False,
        "model_tier": "cheap",
        "max_agent_count": 0,
        "max_tool_count": 0,
        "deep_thinking": False,
        "reason": "insufficient_balance",
    }
