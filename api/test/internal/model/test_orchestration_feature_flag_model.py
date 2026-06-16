from internal.model.orchestration_feature_flag import (
    OrchestrationFeatureFlagModel,
)


def test_orchestration_feature_flag_model_should_define_required_columns():
    columns = OrchestrationFeatureFlagModel.__table__.columns

    for name in [
        "id",
        "code",
        "name",
        "description",
        "enabled",
        "risk_level",
        "fallback_behavior",
        "updated_by",
        "created_at",
        "updated_at",
    ]:
        assert name in columns


def test_orchestration_feature_flag_model_should_index_unique_code():
    constraints = OrchestrationFeatureFlagModel.__table__.constraints
    unique_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in constraints
    }

    assert unique_constraints["uq_orchestration_feature_flag_code"] == ("code",)
