from internal.service.routing_optimization_suggestion_service import (
    RoutingOptimizationSuggestionService,
)


def test_suggestions_should_collect_more_feedback_when_sample_is_low():
    suggestions = RoutingOptimizationSuggestionService().generate_suggestions({
        "total_count": 10,
        "feedback_count": 1,
        "fallback_rate": 0.1,
        "quality_by_model": {},
        "quality_by_tool_pool": {},
    })

    assert suggestions[0]["suggestion_type"] == "collect_more_feedback"
    assert suggestions[0]["status"] == "open"
    assert "evidence" in suggestions[0]


def test_suggestions_should_flag_high_fallback_rate():
    suggestions = RoutingOptimizationSuggestionService().generate_suggestions({
        "total_count": 20,
        "feedback_count": 10,
        "fallback_rate": 0.4,
        "quality_by_model": {},
        "quality_by_tool_pool": {},
    })

    assert suggestions[0]["suggestion_type"] == "review_fallback_rate"
    assert suggestions[0]["severity"] == "high"


def test_suggestions_should_flag_high_cost_low_rating_model():
    suggestions = RoutingOptimizationSuggestionService().generate_suggestions({
        "total_count": 20,
        "feedback_count": 12,
        "fallback_rate": 0.1,
        "quality_by_model": {
            "premium": {"count": 8, "avg_rating": 2.4, "avg_cost_credits": 8}
        },
        "quality_by_tool_pool": {},
    })

    assert suggestions[0]["target_type"] == "model"
    assert suggestions[0]["target_id"] == "premium"
    assert suggestions[0]["suggestion_type"] == "review_model_cost"


def test_suggestions_should_flag_low_quality_tool_pool():
    suggestions = RoutingOptimizationSuggestionService().generate_suggestions({
        "total_count": 20,
        "feedback_count": 12,
        "fallback_rate": 0.1,
        "quality_by_model": {},
        "quality_by_tool_pool": {
            "browser": {"count": 7, "avg_rating": 2.3}
        },
    })

    assert suggestions[0]["target_type"] == "tool_pool"
    assert suggestions[0]["target_id"] == "browser"
    assert suggestions[0]["suggestion_type"] == "review_tool_health"
