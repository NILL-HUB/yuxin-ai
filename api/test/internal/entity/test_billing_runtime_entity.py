from internal.entity.billing_runtime_entity import ModelKeyItem, ModelPoolItem


def test_model_pool_item_should_normalize_defaults_and_prices():
    item = ModelPoolItem.from_dict(
        {
            "provider": " openai ",
            "model": " gpt-4o-mini ",
            "tier": "",
            "capabilities": ["chat", "chat", "tool_calling"],
            "price_per_1k_input_tokens": -1,
            "price_per_1k_output_tokens": 0.03,
            "context_window": -100,
            "health_status": "broken",
            "rate_limit_per_minute": -1,
            "enabled": "true",
        }
    )

    assert item.provider == "openai"
    assert item.model == "gpt-4o-mini"
    assert item.tier == "2"
    assert item.capabilities == ["chat", "tool_calling"]
    assert item.price_per_1k_input_tokens == 0
    assert item.price_per_1k_output_tokens == 0.03
    assert item.context_window == 0
    assert item.health_status == "unknown"
    assert item.rate_limit_per_minute == 0
    assert item.enabled is True


def test_model_key_item_should_hide_secret_and_normalize_quota_state():
    item = ModelKeyItem.from_dict(
        {
            "provider": " openai ",
            "key_id": " key-1 ",
            "secret": "sk-live-secret",
            "tenant_scope": " tenant-1 ",
            "status": "invalid",
            "quota_credits": 100,
            "used_credits": 150,
            "failure_count": -2,
        }
    )

    assert item.provider == "openai"
    assert item.key_id == "key-1"
    assert item.secret == ""
    assert item.tenant_scope == "tenant-1"
    assert item.status == "inactive"
    assert item.quota_credits == 100
    assert item.used_credits == 100
    assert item.remaining_credits == 0
    assert item.failure_count == 0
    assert "secret" not in item.to_safe_dict()
