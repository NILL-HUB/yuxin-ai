from internal.model.model_pool_entity import ModelPoolConfig


def test_model_pool_config_has_cost_columns():
    columns = ModelPoolConfig.__table__.columns.keys()
    assert "input_cost_per_1k_tokens" in columns
    assert "output_cost_per_1k_tokens" in columns