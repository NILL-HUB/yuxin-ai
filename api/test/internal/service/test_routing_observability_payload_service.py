from internal.entity.orchestrator_entity import (
    RoutingDecision,
)
from internal.service.routing_observability_payload_service import (
    RoutingObservabilityPayloadService,
)


def test_payload_service_should_build_phase7_log_payload_from_decision():
    decision = RoutingDecision(
        intent="tool_task",
        complexity="complex",
        execution_mode="multi_agent",
        needs_agent=True,
        agent_subset={
            "matched_pools": ["research"],
            "selected_agents": [{"agent_id": "agent-1"}],
        },
        tool_subset={
            "selected_tools": [{"name": "search", "pool": "web"}],
            "filtered_out_tools": [],
        },
        cost_policy={"model_tier": "cheap", "selected_model": "deepseek-chat"},
        billing_events=[{"event": "billing_delta", "total_credits": 3}],
        task_plan_summary={"task_count": 2},
        synthesis_summary={"user_warnings": ["fallback:task_failed"]},
        reason="complex_multi_domain",
    )

    payload = RoutingObservabilityPayloadService().build(
        user_query="帮我分析市场",
        decision=decision,
        latency_ms=1200,
    )

    assert payload["routing_decision"]["intent"] == "tool_task"
    assert payload["task_classification"] == {
        "intent": "tool_task",
        "complexity": "complex",
        "execution_mode": "multi_agent",
    }
    assert payload["model_selection"] == {
        "model_tier": "cheap",
        "model_id": "deepseek-chat",
    }
    assert payload["agent_pool_hits"] == [{"pool": "research"}]
    assert payload["tool_pool_hits"] == [{"pool": "web"}]
    assert payload["cost_summary"] == {"total_credits": 3}
    assert payload["latency_ms"] == 1200
    assert payload["fallback_reason"] == "fallback:task_failed"
    assert "raw_prompt" not in str(payload)
    assert "arguments" not in str(payload)


def test_payload_service_should_fallback_to_decision_reason():
    decision = RoutingDecision(
        intent="general_qa",
        complexity="simple",
        execution_mode="direct_answer",
        reason="fallback:classifier_error",
    )

    payload = RoutingObservabilityPayloadService().build(
        user_query="hello",
        decision=decision,
        latency_ms=0,
    )

    assert payload["fallback_reason"] == "fallback:classifier_error"
    assert payload["cost_summary"] == {"total_credits": 0}
