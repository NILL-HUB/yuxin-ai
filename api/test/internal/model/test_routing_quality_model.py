from internal.model.routing_quality import (
    RoutingOptimizationSuggestionModel,
    RoutingQualityFeedbackModel,
)


def test_routing_quality_feedback_model_should_define_required_columns():
    columns = RoutingQualityFeedbackModel.__table__.columns

    for name in [
        "id",
        "routing_log_id",
        "source",
        "rating",
        "dimension_scores",
        "comment",
        "metadata",
        "created_by",
        "created_at",
    ]:
        assert name in columns


def test_routing_quality_feedback_model_should_index_routing_log_id():
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in RoutingQualityFeedbackModel.__table__.indexes
    }

    assert indexes["routing_quality_feedback_routing_log_id_idx"] == (
        "routing_log_id",
    )


def test_routing_optimization_suggestion_model_should_define_required_columns():
    columns = RoutingOptimizationSuggestionModel.__table__.columns

    for name in [
        "id",
        "target_type",
        "target_id",
        "suggestion_type",
        "severity",
        "reason",
        "evidence",
        "status",
        "created_at",
        "updated_at",
    ]:
        assert name in columns


def test_routing_optimization_suggestion_model_should_index_status():
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in RoutingOptimizationSuggestionModel.__table__.indexes
    }

    assert indexes["routing_optimization_suggestion_status_idx"] == ("status",)
