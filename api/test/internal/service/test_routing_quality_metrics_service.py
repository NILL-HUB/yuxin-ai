from types import SimpleNamespace
from uuid import uuid4

from internal.service.routing_quality_metrics_service import (
    RoutingQualityMetricsService,
)


def _routing_log(**kwargs):
    defaults = {
        "id": uuid4(),
        "routing_decision": {
            "intent": "qa",
            "recommended_model_tier": "cheap",
            "agent_subset": {"matched_agent_pools": ["general"]},
            "tool_subset": {"matched_tool_pools": ["search"]},
        },
        "cost_summary": {"estimated_credits": 2},
        "latency_ms": 100,
        "fallback_reason": "",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _feedback(routing_log_id, rating=4):
    return SimpleNamespace(routing_log_id=routing_log_id, rating=rating)


def test_quality_metrics_should_return_empty_structure():
    metrics = RoutingQualityMetricsService().build_metrics(
        routing_logs=[],
        feedback_items=[],
    )

    assert metrics == {
        "total_count": 0,
        "feedback_count": 0,
        "avg_rating": 0,
        "fallback_rate": 0,
        "avg_latency_ms": 0,
        "avg_cost_credits": 0,
        "quality_by_task_type": {},
        "quality_by_agent_pool": {},
        "quality_by_tool_pool": {},
        "quality_by_model": {},
    }


def test_quality_metrics_should_calculate_aggregate_values():
    log_a = _routing_log()
    log_b = _routing_log(
        routing_decision={
            "intent": "analysis",
            "recommended_model_tier": "premium",
            "agent_subset": {"matched_agent_pools": ["research"]},
            "tool_subset": {"matched_tool_pools": ["browser"]},
        },
        cost_summary={"estimated_credits": 6},
        latency_ms=300,
        fallback_reason="timeout",
    )

    metrics = RoutingQualityMetricsService().build_metrics(
        routing_logs=[log_a, log_b],
        feedback_items=[_feedback(log_a.id, 5), _feedback(log_b.id, 3)],
    )

    assert metrics["total_count"] == 2
    assert metrics["feedback_count"] == 2
    assert metrics["avg_rating"] == 4
    assert metrics["fallback_rate"] == 0.5
    assert metrics["avg_latency_ms"] == 200
    assert metrics["avg_cost_credits"] == 4
    assert metrics["quality_by_task_type"]["qa"]["avg_rating"] == 5
    assert metrics["quality_by_agent_pool"]["research"]["avg_rating"] == 3
    assert metrics["quality_by_tool_pool"]["browser"]["count"] == 1
    assert metrics["quality_by_model"]["premium"]["avg_rating"] == 3


def test_quality_metrics_should_derive_pool_hits_when_decision_subset_missing():
    log = _routing_log(
        routing_decision={
            "intent": "qa",
            "recommended_model_tier": "cheap",
            "agent_subset": {},
            "tool_subset": {},
        },
        agent_pool_hits=[
            {"metadata": {"primary_pool": "research"}},
            {"pool": "general"},
        ],
        tool_pool_hits=[
            {"metadata": {"tool_pool": "builtin"}},
            {"source_type": "knowledge"},
        ],
    )

    metrics = RoutingQualityMetricsService().build_metrics(
        routing_logs=[log],
        feedback_items=[],
    )

    assert metrics["quality_by_agent_pool"]["research"]["count"] == 1
    assert metrics["quality_by_agent_pool"]["general"]["count"] == 1
    assert metrics["quality_by_tool_pool"]["builtin"]["count"] == 1
    assert metrics["quality_by_tool_pool"]["knowledge"]["count"] == 1
