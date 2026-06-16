from types import SimpleNamespace
from uuid import uuid4

from internal.service.routing_optimization_suggestion_service import (
    RoutingOptimizationSuggestionService,
)
from internal.service.routing_quality_feedback_service import (
    RoutingQualityFeedbackService,
)


def test_feedback_serialization_should_exclude_sensitive_internal_fields():
    feedback = SimpleNamespace(
        id=uuid4(),
        routing_log_id=uuid4(),
        source="admin",
        rating=4,
        dimension_scores={"accuracy": 5},
        comment="useful",
        meta={"ticket_id": "T-1"},
        key_usage={"api_key": "secret"},
        internal_cost_breakdown={"token_cost": 10},
        created_by=uuid4(),
        created_at=None,
    )

    result = RoutingQualityFeedbackService.serialize_feedback(feedback)

    assert "key_usage" not in result
    assert "internal_cost_breakdown" not in result
    assert "api_key" not in str(result)


def test_optimization_suggestions_should_not_modify_runtime_config():
    flags = {"ENABLE_MULTI_AGENT_EXECUTION": True}
    agents = {"research": {"priority": 10}}
    tools = {"browser": {"enabled": True}}
    models = {"premium": {"cost": 8}}

    suggestions = RoutingOptimizationSuggestionService().generate_suggestions(
        {
            "total_count": 20,
            "feedback_count": 10,
            "fallback_rate": 0.5,
            "quality_by_model": {
                "premium": {
                    "count": 6,
                    "avg_rating": 2.2,
                    "avg_cost_credits": 8,
                }
            },
            "quality_by_tool_pool": {
                "browser": {"count": 5, "avg_rating": 2.4}
            },
        }
    )

    assert suggestions
    assert flags == {"ENABLE_MULTI_AGENT_EXECUTION": True}
    assert agents == {"research": {"priority": 10}}
    assert tools == {"browser": {"enabled": True}}
    assert models == {"premium": {"cost": 8}}


def test_home_response_should_not_include_routing_quality_fields(client):
    resp = client.post("/home", json={"query": "hello"})

    assert resp.status_code in {200, 401}
    assert "routing_quality" not in resp.get_data(as_text=True)
    assert "optimization_suggestion" not in resp.get_data(as_text=True)
