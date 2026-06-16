from internal.entity.billing_runtime_entity import ModelPoolItem
from internal.service.model_pool_service import ModelPoolService


def _model(model, tier, capabilities=None, health_status="healthy", enabled=True):
    return ModelPoolItem.from_dict(
        {
            "provider": "openai",
            "model": model,
            "tier": tier,
            "capabilities": capabilities or ["chat"],
            "health_status": health_status,
            "enabled": enabled,
            "price_per_1k_input_tokens": {
                "cheap": 0.01,
                "standard": 0.03,
                "strong": 0.1,
            }[tier],
        }
    )


def test_model_pool_service_should_select_model_by_capability_and_tier():
    service = ModelPoolService(
        models=[
            _model("cheap-chat", "cheap", ["chat"]),
            _model("standard-tool", "standard", ["chat", "tool_calling"]),
            _model("strong-tool", "strong", ["chat", "tool_calling"]),
        ]
    )

    result = service.select_model(
        required_capabilities=["tool_calling"], preferred_tier="standard"
    )

    assert result.model == "standard-tool"


def test_model_pool_service_should_skip_unhealthy_and_disabled_models():
    service = ModelPoolService(
        models=[
            _model("standard-disabled", "standard", enabled=False),
            _model("standard-unhealthy", "standard", health_status="unknown"),
            _model("standard-healthy", "standard"),
        ]
    )

    result = service.select_model(
        required_capabilities=["chat"], preferred_tier="standard"
    )

    assert result.model == "standard-healthy"


def test_model_pool_service_should_fallback_to_lower_cost_available_model():
    service = ModelPoolService(models=[_model("cheap-chat", "cheap", ["chat"])])

    result = service.select_model(required_capabilities=["chat"], preferred_tier="strong")

    assert result.model == "cheap-chat"
    assert result.tier == "cheap"


def test_model_pool_service_should_return_none_when_no_model_matches():
    service = ModelPoolService(models=[_model("cheap-chat", "cheap", ["chat"])])

    assert (
        service.select_model(required_capabilities=["vision"], preferred_tier="cheap")
        is None
    )
