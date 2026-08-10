from decimal import Decimal
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
