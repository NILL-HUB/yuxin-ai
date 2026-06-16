import pytest

from internal.entity.routing_quality_entity import (
    ROUTING_QUALITY_DIMENSIONS,
    ROUTING_QUALITY_FEEDBACK_SOURCES,
    RoutingOptimizationSuggestion,
    RoutingQualityFeedback,
)


def test_routing_quality_feedback_should_serialize_stable_shape():
    feedback = RoutingQualityFeedback(
        routing_log_id="log-1",
        source="admin",
        rating=4,
        dimension_scores={"accuracy": 5, "latency": 3},
        comment="answer was useful",
        metadata={"ticket_id": "T-1"},
    )

    assert feedback.to_dict() == {
        "routing_log_id": "log-1",
        "source": "admin",
        "rating": 4,
        "dimension_scores": {"accuracy": 5, "latency": 3},
        "comment": "answer was useful",
        "metadata": {"ticket_id": "T-1"},
    }


def test_routing_quality_feedback_should_validate_source_and_rating():
    assert ROUTING_QUALITY_FEEDBACK_SOURCES == [
        "admin",
        "system",
        "user_signal",
    ]

    with pytest.raises(ValueError):
        RoutingQualityFeedback(
            routing_log_id="log-1",
            source="unknown",
            rating=4,
        )

    with pytest.raises(ValueError):
        RoutingQualityFeedback(
            routing_log_id="log-1",
            source="admin",
            rating=6,
        )


def test_routing_quality_feedback_should_validate_dimensions():
    assert ROUTING_QUALITY_DIMENSIONS == [
        "completeness",
        "accuracy",
        "latency",
        "cost",
        "safety",
    ]

    with pytest.raises(ValueError):
        RoutingQualityFeedback(
            routing_log_id="log-1",
            source="admin",
            rating=4,
            dimension_scores={"unknown": 1},
        )


def test_routing_optimization_suggestion_should_default_open_status():
    suggestion = RoutingOptimizationSuggestion(
        target_type="model",
        target_id="cheap",
        suggestion_type="review_model_cost",
        severity="medium",
        reason="high cost with low rating",
        evidence={"avg_rating": 2.2, "avg_cost_credits": 10},
    )

    assert suggestion.to_dict() == {
        "target_type": "model",
        "target_id": "cheap",
        "suggestion_type": "review_model_cost",
        "severity": "medium",
        "reason": "high cost with low rating",
        "evidence": {"avg_rating": 2.2, "avg_cost_credits": 10},
        "status": "open",
    }
