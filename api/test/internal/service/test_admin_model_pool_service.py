from decimal import Decimal
import json
from uuid import UUID, uuid4

from sqlalchemy import text

from internal.model.model_pool_entity import ModelKeyConfig
from internal.model.model_provider_entity import ModelProviderConfig
from internal.service.admin_model_pool_service import AdminModelPoolService, _decrypt_key_value


def _seed_provider(db, name="openai"):
    """插入一条 active 供应商记录，供依赖 provider 校验的用例使用。"""
    from datetime import UTC, datetime

    now = datetime.now(UTC).replace(tzinfo=None)
    _ensure_provider_schema(db)
    provider = ModelProviderConfig(
        id=uuid4(),
        name=name,
        label=name,
        default_base_url="https://api.openai.com/v1",
        status="active",
        updated_at=now,
        created_at=now,
    )
    db.session.add(provider)
    db.session.commit()
    return provider


def _ensure_provider_schema(db):
    columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(model_provider_config)"))}
    if "is_full_url" not in columns:
        db.session.execute(text("ALTER TABLE model_provider_config ADD COLUMN is_full_url BOOLEAN NOT NULL DEFAULT 0"))
        db.session.commit()


_NEW_PRICING_COLUMNS = [
    ("peak_valley_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
    ("cache_pricing_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
    ("peak_windows", "TEXT NOT NULL DEFAULT '[]'"),
    ("input_cached_price_per_1k_tokens", "NUMERIC NOT NULL DEFAULT 0"),
    ("input_cached_cost_per_1k_tokens", "NUMERIC NOT NULL DEFAULT 0"),
    ("peak_input_price_per_1k_tokens", "NUMERIC NOT NULL DEFAULT 0"),
    ("peak_output_price_per_1k_tokens", "NUMERIC NOT NULL DEFAULT 0"),
    ("peak_input_cached_price_per_1k_tokens", "NUMERIC NOT NULL DEFAULT 0"),
    ("peak_input_cost_per_1k_tokens", "NUMERIC NOT NULL DEFAULT 0"),
    ("peak_output_cost_per_1k_tokens", "NUMERIC NOT NULL DEFAULT 0"),
    ("peak_input_cached_cost_per_1k_tokens", "NUMERIC NOT NULL DEFAULT 0"),
    ("valley_input_price_per_1k_tokens", "NUMERIC NOT NULL DEFAULT 0"),
    ("valley_output_price_per_1k_tokens", "NUMERIC NOT NULL DEFAULT 0"),
    ("valley_input_cached_price_per_1k_tokens", "NUMERIC NOT NULL DEFAULT 0"),
    ("valley_input_cost_per_1k_tokens", "NUMERIC NOT NULL DEFAULT 0"),
    ("valley_output_cost_per_1k_tokens", "NUMERIC NOT NULL DEFAULT 0"),
    ("valley_input_cached_cost_per_1k_tokens", "NUMERIC NOT NULL DEFAULT 0"),
]


def _ensure_new_pricing_columns(db):
    """为 model_pool_config 补齐峰谷/缓存定价新列（conftest DDL 尚未包含）。"""
    existing = {row[1] for row in db.session.execute(text("PRAGMA table_info(model_pool_config)"))}
    for name, ddl in _NEW_PRICING_COLUMNS:
        if name not in existing:
            db.session.execute(text(f"ALTER TABLE model_pool_config ADD COLUMN {name} {ddl}"))
    db.session.commit()


class TestAdminModelPoolKeyEncryption:
    def test_create_key_should_encrypt_with_fernet_and_mask_in_list(self, model_pool_db):
        _seed_provider(model_pool_db)
        service = AdminModelPoolService(session=model_pool_db.session)
        created = service.create_key({
            "provider": "openai",
            "key_alias": "fernet-key",
            "key_value": "sk-real-secret-1234567890",
            "tenant_quota": "1000",
        })

        raw = model_pool_db.session.query(ModelKeyConfig).filter(ModelKeyConfig.id == UUID(created["id"])).one()
        assert raw.key_value_encrypted != "sk-real-secret-1234567890"
        assert _decrypt_key_value(raw.key_value_encrypted) == "sk-real-secret-1234567890"
        assert created["key_mask"].startswith("sk-r")
        assert "*" in created["key_mask"]
        assert created["key_mask"] != "sk-real-secret-1234567890"

    def test_list_keys_should_return_masked_keys_without_raw_secret(self, model_pool_db):
        _seed_provider(model_pool_db)
        service = AdminModelPoolService(session=model_pool_db.session)
        service.create_key({
            "provider": "openai",
            "key_alias": "k1",
            "key_value": "sk-real-secret-1234567890",
            "tenant_quota": "1000",
        })

        result = service.list_keys(provider="openai", status="active", current_page=1, page_size=20)

        serialized = result["list"][0]
        assert serialized["key_alias"] == "k1"
        assert "key_value" not in serialized
        assert serialized["key_mask"] != "sk-real-secret-1234567890"
        assert "*" in serialized["key_mask"]

    def test_update_key_should_re_encrypt_new_value(self, model_pool_db):
        _seed_provider(model_pool_db)
        service = AdminModelPoolService(session=model_pool_db.session)
        created = service.create_key({
            "provider": "openai",
            "key_alias": "k",
            "key_value": "sk-old-1234567890",
            "tenant_quota": "10",
        })

        service.update_key(UUID(created["id"]), {"key_value": "sk-new-1234567890abcdef"})

        raw = model_pool_db.session.query(ModelKeyConfig).filter(ModelKeyConfig.id == UUID(created["id"])).one()
        assert _decrypt_key_value(raw.key_value_encrypted) == "sk-new-1234567890abcdef"
        assert raw.key_value_encrypted != "sk-old-1234567890"
        assert Decimal(str(raw.tenant_quota)) == Decimal("10.0000")


class TestAdminModelPoolPeakValleyPricing:
    def test_create_model_roundtrips_peak_valley_fields(self, model_pool_db):
        from werkzeug.datastructures import ImmutableMultiDict

        from internal.schema.admin_model_pool_schema import CreateAdminModelReq

        _ensure_new_pricing_columns(model_pool_db)
        _seed_provider(model_pool_db)
        service = AdminModelPoolService(session=model_pool_db.session)
        req = CreateAdminModelReq(formdata=ImmutableMultiDict([
            ("provider", "openai"),
            ("model_name", "pv-model"),
            ("peak_valley_enabled", "true"),
            ("cache_pricing_enabled", "true"),
            ("peak_windows", '[{"days":"0-6","start":"09:00","end":"18:00"}]'),
            ("peak_input_price_per_1k_tokens", "2.000000"),
            ("valley_input_price_per_1k_tokens", "1.000000"),
            ("input_cached_price_per_1k_tokens", "0.500000"),
        ]), meta={"csrf": False})
        assert req.peak_valley_enabled.data == "true"
        assert req.validate()

        req_bad = CreateAdminModelReq(formdata=ImmutableMultiDict([
            ("provider", "openai"),
            ("model_name", "pv-bad"),
            ("peak_valley_enabled", "maybe"),
        ]), meta={"csrf": False})
        assert not req_bad.validate()
        assert "peak_valley_enabled" in req_bad.errors

        created = service.create_model(req.data)
        assert created["id"]
        assert created["peak_valley_enabled"] == "true"
        assert created["cache_pricing_enabled"] == "true"
        assert json.loads(created["peak_windows"]) == [
            {"days": "0-6", "start": "09:00", "end": "18:00"}
        ]
        assert created["peak_input_price_per_1k_tokens"] == "2.000000"
        assert created["valley_input_price_per_1k_tokens"] == "1.000000"
        assert created["input_cached_price_per_1k_tokens"] == "0.500000"

        updated = service.update_model(UUID(created["id"]), {
            "peak_valley_enabled": "0",
            "valley_output_price_per_1k_tokens": "3.000000",
        })
        assert updated["peak_valley_enabled"] == "false"
        assert updated["valley_output_price_per_1k_tokens"] == "3.000000"
        assert json.loads(updated["peak_windows"]) == [
            {"days": "0-6", "start": "09:00", "end": "18:00"}
        ]
