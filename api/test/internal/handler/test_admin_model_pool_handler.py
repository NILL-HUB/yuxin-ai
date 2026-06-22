from decimal import Decimal
from uuid import UUID, uuid4

from pkg.response import HttpCode
from internal.model.model_pool_entity import ModelKeyConfig
from internal.service.admin_model_pool_service import AdminModelPoolService, _decrypt_key_value


_MODEL_ID = uuid4()
_KEY_ID = uuid4()
_POLICY_ID = uuid4()

_MODEL = {
    "id": str(_MODEL_ID),
    "provider": "openai",
    "model_name": "gpt-4o",
    "display_name": "GPT-4o",
    "tier": "standard",
    "capabilities": ["chat", "tool_calling"],
    "price_per_1k_tokens": "0.030000",
    "max_tokens": 128000,
    "status": "active",
    "created_at": 1893456000,
    "updated_at": 1893542400,
}

_KEY = {
    "id": str(_KEY_ID),
    "provider": "openai",
    "key_alias": "main-key",
    "key_mask": "sk-1****abcd",
    "tenant_quota": "1000.0000",
    "status": "active",
    "failure_count": 0,
    "created_at": 1893456000,
    "updated_at": 1893542400,
}

_TIER = {
    "id": "tier-1",
    "tier_code": "standard",
    "allowed_models": ["gpt-4o", "gpt-4o-mini"],
    "default_model": "gpt-4o",
    "routing_rules": {"strategy": "cost_first"},
    "created_at": 1893456000,
    "updated_at": 1893542400,
}

_COST_POLICY = {
    "id": str(_POLICY_ID),
    "policy_name": "default",
    "model_tier": "standard",
    "max_cost_per_request": "0.500000",
    "billing_mode": "token",
    "upgrade_threshold": "0.100000",
    "created_at": 1893456000,
    "updated_at": 1893542400,
}


def _mock_current_admin(monkeypatch, permissions):
    def _get_current_admin_from_token(self, token):
        return {
            "id": "admin-1",
            "email": "root@example.com",
            "name": "Root",
            "avatar": "",
            "status": "active",
            "roles": ["super_admin"],
            "permissions": permissions,
        }

    monkeypatch.setattr(
        "internal.service.admin_user_service.AdminUserService.get_current_admin_from_token",
        _get_current_admin_from_token,
    )


class TestAdminModelPoolHandler:
    def test_list_models_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["model_pool:read"])

        def _list(self, *, search, provider, tier, status, current_page, page_size):
            captured.update({"search": search, "provider": provider, "tier": tier, "status": status, "current_page": current_page, "page_size": page_size})
            return {"list": [_MODEL], "paginator": {"total_record": 1, "total_page": 1, "current_page": 1, "page_size": 20}}

        monkeypatch.setattr("internal.service.admin_model_pool_service.AdminModelPoolService.list_models", _list, raising=False)

        resp = client.get("/admin/models?search=gpt&provider=openai&tier=standard&status=active&current_page=1&page_size=20", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["model_name"] == "gpt-4o"
        assert captured == {"search": "gpt", "provider": "openai", "tier": "standard", "status": "active", "current_page": 1, "page_size": 20}

    def test_create_model_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["model_pool:manage"])

        def _create(self, payload):
            captured["payload"] = payload
            return {**_MODEL, "model_name": payload["model_name"]}

        monkeypatch.setattr("internal.service.admin_model_pool_service.AdminModelPoolService.create_model", _create, raising=False)

        resp = client.post(
            "/admin/models",
            json={"provider": "openai", "model_name": "gpt-4o", "tier": "standard", "capabilities": ["chat"], "price_per_1k_tokens": "0.03", "max_tokens": 128000},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["model_name"] == "gpt-4o"
        assert captured["payload"]["provider"] == "openai"

    def test_get_model_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["model_pool:read"])

        def _get(self, model_id_arg):
            captured["model_id"] = model_id_arg
            return {**_MODEL, "id": str(model_id_arg)}

        monkeypatch.setattr("internal.service.admin_model_pool_service.AdminModelPoolService.get_model", _get, raising=False)

        resp = client.get(f"/admin/models/{_MODEL_ID}", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["id"] == str(_MODEL_ID)
        assert captured == {"model_id": _MODEL_ID}

    def test_update_model_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["model_pool:manage"])

        def _update(self, model_id_arg, payload):
            captured.update({"model_id": model_id_arg, "payload": payload})
            return {**_MODEL, "id": str(model_id_arg), "display_name": payload.get("display_name", _MODEL["display_name"])}

        monkeypatch.setattr("internal.service.admin_model_pool_service.AdminModelPoolService.update_model", _update, raising=False)

        resp = client.patch(f"/admin/models/{_MODEL_ID}", json={"display_name": "GPT-4o Plus"}, headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["display_name"] == "GPT-4o Plus"
        assert captured["model_id"] == _MODEL_ID

    def test_delete_model_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["model_pool:manage"])

        def _delete(self, model_id_arg):
            captured["model_id"] = model_id_arg

        monkeypatch.setattr("internal.service.admin_model_pool_service.AdminModelPoolService.delete_model", _delete, raising=False)

        resp = client.delete(f"/admin/models/{_MODEL_ID}", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured == {"model_id": _MODEL_ID}

    def test_set_model_status_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["model_pool:manage"])

        def _set_status(self, model_id_arg, status):
            captured.update({"model_id": model_id_arg, "status": status})
            return {**_MODEL, "id": str(model_id_arg), "status": status}

        monkeypatch.setattr("internal.service.admin_model_pool_service.AdminModelPoolService.set_model_status", _set_status, raising=False)

        resp = client.post(f"/admin/models/{_MODEL_ID}/status", json={"status": "disabled"}, headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["status"] == "disabled"
        assert captured == {"model_id": _MODEL_ID, "status": "disabled"}

    def test_list_keys_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["model_pool:read"])

        def _list(self, *, provider, status, current_page, page_size):
            captured.update({"provider": provider, "status": status, "current_page": current_page, "page_size": page_size})
            return {"list": [_KEY], "paginator": {"total_record": 1, "total_page": 1, "current_page": 1, "page_size": 20}}

        monkeypatch.setattr("internal.service.admin_model_pool_service.AdminModelPoolService.list_keys", _list, raising=False)

        resp = client.get("/admin/model-keys?provider=openai&status=active&current_page=1&page_size=20", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["key_alias"] == "main-key"
        assert captured == {"provider": "openai", "status": "active", "current_page": 1, "page_size": 20}

    def test_create_key_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["model_pool:manage"])

        def _create(self, payload):
            captured["payload"] = payload
            return {**_KEY, "key_alias": payload["key_alias"]}

        monkeypatch.setattr("internal.service.admin_model_pool_service.AdminModelPoolService.create_key", _create, raising=False)

        resp = client.post(
            "/admin/model-keys",
            json={"provider": "openai", "key_alias": "main-key", "key_value": "sk-1234567890abcdef", "tenant_quota": "1000"},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["key_alias"] == "main-key"
        assert captured["payload"]["key_value"] == "sk-1234567890abcdef"

    def test_update_key_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["model_pool:manage"])

        def _update(self, key_id_arg, payload):
            captured.update({"key_id": key_id_arg, "payload": payload})
            return {**_KEY, "id": str(key_id_arg), "key_alias": payload.get("key_alias", _KEY["key_alias"])}

        monkeypatch.setattr("internal.service.admin_model_pool_service.AdminModelPoolService.update_key", _update, raising=False)

        resp = client.patch(f"/admin/model-keys/{_KEY_ID}", json={"key_alias": "backup-key"}, headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["key_alias"] == "backup-key"
        assert captured["key_id"] == _KEY_ID

    def test_delete_key_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["model_pool:manage"])

        def _delete(self, key_id_arg):
            captured["key_id"] = key_id_arg

        monkeypatch.setattr("internal.service.admin_model_pool_service.AdminModelPoolService.delete_key", _delete, raising=False)

        resp = client.delete(f"/admin/model-keys/{_KEY_ID}", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured == {"key_id": _KEY_ID}

    def test_set_key_status_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["model_pool:manage"])

        def _set_status(self, key_id_arg, status):
            captured.update({"key_id": key_id_arg, "status": status})
            return {**_KEY, "id": str(key_id_arg), "status": status}

        monkeypatch.setattr("internal.service.admin_model_pool_service.AdminModelPoolService.set_key_status", _set_status, raising=False)

        resp = client.post(f"/admin/model-keys/{_KEY_ID}/status", json={"status": "disabled"}, headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["status"] == "disabled"
        assert captured == {"key_id": _KEY_ID, "status": "disabled"}

    def test_list_tier_policies_should_delegate_to_service(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["model_pool:read"])

        def _list(self):
            return {"list": [_TIER]}

        monkeypatch.setattr("internal.service.admin_model_pool_service.AdminModelPoolService.list_tier_policies", _list, raising=False)

        resp = client.get("/admin/model-tiers", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["tier_code"] == "standard"

    def test_update_tier_policy_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["model_pool:manage"])

        def _update(self, tier_code, payload):
            captured.update({"tier_code": tier_code, "payload": payload})
            return {**_TIER, "tier_code": tier_code, "default_model": payload.get("default_model", _TIER["default_model"])}

        monkeypatch.setattr("internal.service.admin_model_pool_service.AdminModelPoolService.update_tier_policy", _update, raising=False)

        resp = client.put("/admin/model-tiers/standard", json={"default_model": "gpt-4o-mini", "allowed_models": ["gpt-4o", "gpt-4o-mini"]}, headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["default_model"] == "gpt-4o-mini"
        assert captured == {"tier_code": "standard", "payload": {"default_model": "gpt-4o-mini", "allowed_models": ["gpt-4o", "gpt-4o-mini"]}}

    def test_list_cost_policies_should_delegate_to_service(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["model_pool:read"])

        def _list(self):
            return {"list": [_COST_POLICY]}

        monkeypatch.setattr("internal.service.admin_model_pool_service.AdminModelPoolService.list_cost_policies", _list, raising=False)

        resp = client.get("/admin/cost-policies", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["policy_name"] == "default"

    def test_update_cost_policy_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["model_pool:manage"])

        def _update(self, policy_id_arg, payload):
            captured.update({"policy_id": policy_id_arg, "payload": payload})
            return {**_COST_POLICY, "id": str(policy_id_arg), "max_cost_per_request": payload.get("max_cost_per_request", _COST_POLICY["max_cost_per_request"])}

        monkeypatch.setattr("internal.service.admin_model_pool_service.AdminModelPoolService.update_cost_policy", _update, raising=False)

        resp = client.put(f"/admin/cost-policies/{_POLICY_ID}", json={"max_cost_per_request": "0.800000", "billing_mode": "request"}, headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["max_cost_per_request"] == "0.800000"
        assert captured["policy_id"] == _POLICY_ID

    def test_list_models_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["admin:access"])

        resp = client.get("/admin/models", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN

    def test_list_keys_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["admin:access"])

        resp = client.get("/admin/model-keys", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN


class TestAdminModelPoolKeyEncryption:
    def test_create_key_should_encrypt_with_fernet_and_mask_in_list(self, model_pool_db):
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
