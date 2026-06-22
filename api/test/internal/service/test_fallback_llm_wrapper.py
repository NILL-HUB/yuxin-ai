from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from internal.model.model_pool_entity import ModelKeyConfig, ModelPoolConfig
from internal.service.admin_model_pool_service import _decrypt_key_value, _encrypt_key_value
from internal.service.fallback_llm_wrapper import FallbackLLMWrapper
from internal.service.runtime_model_pool_service import RuntimeModelPoolService


class _FakeLLM:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.invoke_calls = 0

    def invoke(self, messages, **kwargs):
        self.invoke_calls += 1
        if self.error is not None:
            raise self.error
        return self.result

    def stream(self, messages, **kwargs):
        if self.error is not None:
            raise self.error
        for chunk in (self.result or []):
            yield chunk


def _make_model(db, **overrides):
    model = ModelPoolConfig(
        id=overrides.pop("id", uuid4()),
        provider=overrides.pop("provider", "openai"),
        model_name=overrides.pop("model_name", "gpt-4o"),
        display_name="",
        tier=overrides.pop("tier", "standard"),
        capabilities=["chat"],
        price_per_1k_tokens=Decimal("0.03"),
        max_tokens=128000,
        status=overrides.pop("status", "active"),
        fallback_model_id=None,
        priority=overrides.pop("priority", 0),
    )
    db.session.add(model)
    db.session.commit()
    return model


def _make_key(db, provider, **overrides):
    key = ModelKeyConfig(
        id=overrides.pop("id", uuid4()),
        provider=provider,
        key_alias=overrides.pop("key_alias", "alias"),
        key_value_encrypted=overrides.pop("key_value_encrypted", ""),
        tenant_quota=overrides.pop("tenant_quota", Decimal("100.0000")),
        status=overrides.pop("status", "active"),
        failure_count=overrides.pop("failure_count", 0),
        last_used_at=None,
        expires_at=None,
        used_credits=overrides.pop("used_credits", Decimal("0.0000")),
        model_id=overrides.pop("model_id", None),
    )
    db.session.add(key)
    db.session.commit()
    return key


def _wrapper(db, default_llm):
    svc = RuntimeModelPoolService(db=db)
    lms = SimpleNamespace(load_default_language_model=lambda: default_llm)
    return FallbackLLMWrapper(runtime_model_pool_service=svc, language_model_service=lms)


def _refresh(db, key):
    return db.session.query(ModelKeyConfig).filter(ModelKeyConfig.id == key.id).one()


class TestFallbackLLMWrapper:
    def test_primary_model_success_should_return_result_and_record_usage(self, model_pool_db):
        model = _make_model(model_pool_db, priority=10)
        key = _make_key(model_pool_db, "openai", used_credits=Decimal("0"))
        default_llm = _FakeLLM(result="default")

        wrapper = _wrapper(model_pool_db, default_llm)
        wrapper._build_llm = lambda model_, key_: _FakeLLM(result="ok")

        result = wrapper.invoke_with_fallback("standard", "hello")

        assert result == "ok"
        refreshed = _refresh(model_pool_db, key)
        assert refreshed.last_used_at is not None
        assert default_llm.invoke_calls == 0
        _ = model

    def test_should_switch_to_next_key_when_primary_key_fails(self, model_pool_db):
        model = _make_model(model_pool_db, priority=10)
        key_busy = _make_key(model_pool_db, "openai", key_alias="busy", used_credits=Decimal("0"))
        key_idle = _make_key(model_pool_db, "openai", key_alias="idle", used_credits=Decimal("5"))

        wrapper = _wrapper(model_pool_db, _FakeLLM(result="default"))

        def _build(model_, key_):
            if key_.id == key_busy.id:
                return _FakeLLM(error=RuntimeError("boom"))
            return _FakeLLM(result="ok")

        wrapper._build_llm = _build

        result = wrapper.invoke_with_fallback("standard", "hello")

        assert result == "ok"
        assert _refresh(model_pool_db, key_busy).failure_count == 1
        assert _refresh(model_pool_db, key_idle).last_used_at is not None

    def test_should_try_fallback_model_when_all_keys_of_primary_fail(self, model_pool_db):
        primary = _make_model(model_pool_db, provider="openai", model_name="p", priority=10)
        fallback = _make_model(model_pool_db, provider="deepseek", model_name="f", priority=5)
        key_p = _make_key(model_pool_db, "openai")
        key_f = _make_key(model_pool_db, "deepseek")

        wrapper = _wrapper(model_pool_db, _FakeLLM(result="default"))

        def _build(model_, key_):
            if key_.provider == "openai":
                return _FakeLLM(error=RuntimeError("boom"))
            return _FakeLLM(result="ok")

        wrapper._build_llm = _build

        result = wrapper.invoke_with_fallback("standard", "hello")

        assert result == "ok"
        assert _refresh(model_pool_db, key_p).failure_count == 1
        assert _refresh(model_pool_db, key_f).last_used_at is not None
        _ = (primary, fallback)

    def test_should_degrade_to_default_model_when_everything_fails(self, model_pool_db):
        model = _make_model(model_pool_db, priority=10)
        key = _make_key(model_pool_db, "openai")

        default_llm = _FakeLLM(result="default")
        wrapper = _wrapper(model_pool_db, default_llm)
        wrapper._build_llm = lambda model_, key_: _FakeLLM(error=RuntimeError("boom"))

        result = wrapper.invoke_with_fallback("standard", "hello")

        assert result == "default"
        assert default_llm.invoke_calls == 1
        assert _refresh(model_pool_db, key).failure_count == 1
        _ = model

    def test_should_degrade_to_default_when_db_has_no_pool_config(self, model_pool_db):
        default_llm = _FakeLLM(result="default")

        wrapper = _wrapper(model_pool_db, default_llm)

        result = wrapper.invoke_with_fallback("standard", "hello")

        assert result == "default"
        assert default_llm.invoke_calls == 1

    def test_key_encryption_should_roundtrip_with_fernet_and_build_llm_config(self, model_pool_db):
        model = _make_model(model_pool_db, priority=10)
        encrypted = _encrypt_key_value("sk-secret-123456")
        key = _make_key(model_pool_db, "openai", key_value_encrypted=encrypted)

        assert encrypted != "sk-secret-123456"
        assert _decrypt_key_value(encrypted) == "sk-secret-123456"
        assert _decrypt_key_value("not-a-fernet-token") == ""

        svc = RuntimeModelPoolService(db=model_pool_db)
        config = svc.build_llm_config(model, key)

        assert config["api_key"] == "sk-secret-123456"
        assert config["provider"] == "openai"
        assert config["model"] == "gpt-4o"
