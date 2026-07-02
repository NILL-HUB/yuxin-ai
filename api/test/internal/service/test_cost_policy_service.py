from internal.service.cost_policy_service import (
    CostPolicyService,
    EscalationPolicy,
    EscalationPolicyService,
)


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


def test_cost_policy_should_use_standard_model_for_medium_task():
    policy = CostPolicyService().build_policy(
        task_complexity="medium",
        budget_level="normal",
        balance_credits=10,
        deep_thinking_requested=False,
    )

    assert policy["allowed"] is True
    assert policy["model_tier"] == "standard"
    assert policy["reason"] == "medium_task_standard_cost"
    assert policy["max_agent_count"] == 3


def test_escalation_policy_should_populate_default_maps():
    policy = EscalationPolicy()

    assert policy.complexity_escalation == {
        "simple": "cheap",
        "medium": "standard",
        "complex": "strong",
    }
    assert policy.budget_downgrade_map == {
        "low": "cheap",
        "medium": "standard",
        "high": "strong",
    }
    assert policy.token_escalation_threshold == 4000
    assert policy.balance_downgrade_threshold == 100.0


def test_should_escalate_true_when_complexity_requires_higher_tier():
    service = EscalationPolicyService()

    assert service.should_escalate("cheap", token_count=0, task_complexity="complex") is True
    assert service.should_escalate("cheap", token_count=0, task_complexity="medium") is True


def test_should_escalate_true_when_token_count_exceeds_threshold():
    service = EscalationPolicyService()

    assert service.should_escalate("cheap", token_count=5000, task_complexity="simple") is True


def test_should_escalate_false_when_no_reason_to_escalate():
    service = EscalationPolicyService()

    assert service.should_escalate("strong", token_count=0, task_complexity="complex") is False
    assert service.should_escalate("cheap", token_count=100, task_complexity="simple") is False


def test_should_downgrade_to_cheap_when_balance_below_threshold():
    service = EscalationPolicyService()

    should, tier = service.should_downgrade("strong", balance_credits=50.0, budget_level="high")

    assert should is True
    assert tier == "cheap"


def test_should_downgrade_when_budget_level_lower_than_current_tier():
    service = EscalationPolicyService()

    should, tier = service.should_downgrade("strong", balance_credits=500.0, budget_level="low")

    assert should is True
    assert tier == "cheap"


def test_should_downgrade_false_when_budget_allows_current_tier():
    service = EscalationPolicyService()

    should, tier = service.should_downgrade("cheap", balance_credits=500.0, budget_level="high")

    assert should is False
    assert tier == "cheap"


def test_resolve_tier_should_prioritize_balance_downgrade():
    service = EscalationPolicyService()

    tier = service.resolve_tier(
        current_tier="strong",
        token_count=0,
        task_complexity="complex",
        balance_credits=10.0,
        budget_level="high",
    )

    assert tier == "cheap"


def test_resolve_tier_should_escalate_when_complexity_requires_higher_tier():
    service = EscalationPolicyService()

    tier = service.resolve_tier(
        current_tier="cheap",
        token_count=0,
        task_complexity="complex",
        balance_credits=500.0,
        budget_level="high",
    )

    assert tier == "strong"


def test_resolve_tier_should_escalate_when_token_count_exceeds_threshold():
    service = EscalationPolicyService()

    tier = service.resolve_tier(
        current_tier="cheap",
        token_count=5000,
        task_complexity="medium",
        balance_credits=500.0,
        budget_level="high",
    )

    assert tier == "standard"


def test_resolve_tier_should_keep_current_when_no_rule_applies():
    service = EscalationPolicyService()

    tier = service.resolve_tier(
        current_tier="strong",
        token_count=0,
        task_complexity="simple",
        balance_credits=500.0,
        budget_level="high",
    )

    assert tier == "strong"


def test_resolve_tier_should_respect_custom_policy_thresholds():
    policy = EscalationPolicy(
        token_escalation_threshold=100,
        balance_downgrade_threshold=1000.0,
    )
    service = EscalationPolicyService(policy)

    assert service.should_escalate("cheap", token_count=200, task_complexity="simple") is True

    tier = service.resolve_tier(
        current_tier="strong",
        token_count=0,
        task_complexity="complex",
        balance_credits=500.0,
        budget_level="high",
    )
    assert tier == "cheap"
