from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from internal.model.model_pool_entity import ModelKeyConfig, ModelPoolConfig
from internal.service.runtime_model_pool_service import RuntimeModelPoolService


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def _make_model(db, **overrides):
    model = ModelPoolConfig(
        id=overrides.pop("id", uuid4()),
        provider=overrides.pop("provider", "openai"),
        model_name=overrides.pop("model_name", "gpt-4o"),
        display_name=overrides.pop("display_name", ""),
        model_type=overrides.pop("model_type", "chat"),
        tier=overrides.pop("tier", "standard"),
        capabilities=overrides.pop("capabilities", ["chat"]),
        price_per_1k_tokens=overrides.pop("price_per_1k_tokens", Decimal("0.03")),
        max_tokens=overrides.pop("max_tokens", 128000),
        max_input_tokens=overrides.pop("max_input_tokens", 128000),
        max_output_tokens=overrides.pop("max_output_tokens", 0),
        status=overrides.pop("status", "active"),
        fallback_model_id=overrides.pop("fallback_model_id", None),
        priority=overrides.pop("priority", 0),
    )
    db.session.add(model)
    db.session.commit()
    return model


def _make_key(db, **overrides):
    key = ModelKeyConfig(
        id=overrides.pop("id", uuid4()),
        provider=overrides.pop("provider", "openai"),
        key_alias=overrides.pop("key_alias", "alias"),
        key_value_encrypted=overrides.pop("key_value_encrypted", ""),
        tenant_quota=overrides.pop("tenant_quota", Decimal("100.0000")),
        status=overrides.pop("status", "active"),
        failure_count=overrides.pop("failure_count", 0),
        last_used_at=overrides.pop("last_used_at", None),
        expires_at=overrides.pop("expires_at", None),
        used_credits=overrides.pop("used_credits", Decimal("0.0000")),
        model_id=overrides.pop("model_id", None),
    )
    db.session.add(key)
    db.session.commit()
    return key


def _service(db):
    from unittest.mock import MagicMock
    mock_manager = MagicMock()
    mock_manager.get_or_load_provider.return_value = MagicMock(default_base_url="https://api.openai.com/v1")
    return RuntimeModelPoolService(db=db, language_model_manager=mock_manager)


class TestRuntimeModelPoolService:
    def test_get_active_models_should_filter_by_tier_and_sort_by_priority(self, model_pool_db):
        _make_model(model_pool_db, provider="openai", model_name="a", priority=10)
        _make_model(model_pool_db, provider="openai", model_name="b", priority=5)
        _make_model(model_pool_db, provider="openai", model_name="c", priority=20, status="disabled")
        _make_model(model_pool_db, provider="deepseek", model_name="d", tier="strong", priority=1)

        service = _service(model_pool_db)
        models = service.get_active_models("standard")

        assert [m.model_name for m in models] == ["a", "b"]

    def test_select_model_with_fallback_should_return_primary_and_candidates(self, model_pool_db):
        primary = _make_model(model_pool_db, provider="openai", model_name="primary", priority=10)
        fallback = _make_model(model_pool_db, provider="deepseek", model_name="fallback", priority=5)

        service = _service(model_pool_db)
        head, candidates = service.select_model_with_fallback("standard")

        assert head.id == primary.id
        assert [c.id for c in candidates] == [fallback.id]

    def test_select_model_with_fallback_should_return_none_when_db_empty(self, model_pool_db):
        service = _service(model_pool_db)
        head, candidates = service.select_model_with_fallback("standard")

        assert head is None
        assert candidates == []

    def test_get_keys_for_model_should_filter_active_unexpired_and_with_quota(self, model_pool_db):
        model = _make_model(model_pool_db, provider="openai", model_name="m", priority=10)
        past = _now() - timedelta(hours=1)
        future = _now() + timedelta(days=1)

        k_active_low = _make_key(model_pool_db, key_alias="low", provider="openai", used_credits=Decimal("0"))
        k_active_high = _make_key(model_pool_db, key_alias="high", provider="openai", used_credits=Decimal("50"))
        k_bound = _make_key(model_pool_db, key_alias="bound", provider="openai", used_credits=Decimal("10"), model_id=str(model.id))
        k_expired = _make_key(model_pool_db, key_alias="expired", provider="openai", expires_at=past)
        k_exhausted = _make_key(model_pool_db, key_alias="exhausted", provider="openai", tenant_quota=Decimal("10"), used_credits=Decimal("10"))
        k_circuit = _make_key(model_pool_db, key_alias="circuit", provider="openai", status="circuit_open")
        k_other_model = _make_key(model_pool_db, key_alias="other", provider="openai", model_id=str(uuid4()))

        service = _service(model_pool_db)
        keys = service.get_keys_for_model(model.id)

        aliases = [k.key_alias for k in keys]
        assert "low" in aliases
        assert "bound" in aliases
        assert "high" in aliases
        assert aliases == ["low", "bound", "high"]
        assert "expired" not in aliases
        assert "exhausted" not in aliases
        assert "circuit" not in aliases
        assert "other" not in aliases
        _ = (k_active_low, k_active_high, k_bound, k_expired, k_exhausted, k_circuit, k_other_model, future)

    def test_select_key_should_pick_least_used_key_for_load_balancing(self, model_pool_db):
        model = _make_model(model_pool_db, provider="openai", model_name="m", priority=10)
        _make_key(model_pool_db, key_alias="busy", provider="openai", used_credits=Decimal("80"))
        _make_key(model_pool_db, key_alias="idle", provider="openai", used_credits=Decimal("1"))

        service = _service(model_pool_db)
        key = service.select_key(model.id)

        assert key.key_alias == "idle"

    def test_record_key_success_should_update_usage_and_disable_on_quota_exhaustion(self, model_pool_db):
        model = _make_model(model_pool_db, provider="openai", model_name="m", priority=10)
        key = _make_key(model_pool_db, key_alias="k", provider="openai", tenant_quota=Decimal("100"), used_credits=Decimal("0"))

        service = _service(model_pool_db)
        service.record_key_success(key.id, credits_used=30)

        refreshed = model_pool_db.session.query(ModelKeyConfig).filter(ModelKeyConfig.id == key.id).one()
        assert Decimal(str(refreshed.used_credits)) == Decimal("30")
        assert refreshed.last_used_at is not None
        assert refreshed.status == "active"

        service.record_key_success(key.id, credits_used=70)
        refreshed = model_pool_db.session.query(ModelKeyConfig).filter(ModelKeyConfig.id == key.id).one()
        assert Decimal(str(refreshed.used_credits)) >= Decimal("100")
        assert refreshed.status == "disabled"
        _ = model

    def test_record_key_failure_should_increment_count_and_open_circuit_at_threshold(self, model_pool_db):
        model = _make_model(model_pool_db, provider="openai", model_name="m", priority=10)
        key = _make_key(model_pool_db, key_alias="k", provider="openai")

        service = _service(model_pool_db)
        assert service.record_key_failure(key.id) is False
        assert service.record_key_failure(key.id) is False
        assert service.record_key_failure(key.id) is True

        refreshed = model_pool_db.session.query(ModelKeyConfig).filter(ModelKeyConfig.id == key.id).one()
        assert refreshed.failure_count == 3
        assert refreshed.status == "circuit_open"
        _ = model

    # ---------------- 输出长度上限注入（max_output_tokens → max_tokens 参数） ----------------

    def test_build_llm_config_should_inject_output_max_tokens(self, model_pool_db):
        model = _make_model(
            model_pool_db, provider="openai", model_name="m", priority=10,
            max_tokens=131072, max_input_tokens=131072, max_output_tokens=4096,
        )
        key = _make_key(model_pool_db, key_alias="k", provider="openai")

        service = _service(model_pool_db)
        config = service.build_llm_config(model, key)

        assert config["parameters"] == {"max_tokens": 4096}

    def test_build_llm_config_should_not_inject_when_output_zero(self, model_pool_db):
        model = _make_model(model_pool_db, provider="openai", model_name="m", priority=10)
        key = _make_key(model_pool_db, key_alias="k", provider="openai")

        service = _service(model_pool_db)
        config = service.build_llm_config(model, key)

        assert config["parameters"] == {}

    def test_build_llm_config_should_not_inject_for_context_less_model(self, model_pool_db):
        model = _make_model(
            model_pool_db, provider="openai", model_name="m", priority=10,
            model_type="tts", max_tokens=0, max_input_tokens=0, max_output_tokens=0,
        )
        key = _make_key(model_pool_db, key_alias="k", provider="openai")

        service = _service(model_pool_db)
        config = service.build_llm_config(model, key)

        assert config["parameters"] == {}
