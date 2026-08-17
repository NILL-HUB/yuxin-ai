import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.admin_routes_3 import register_routes

register_routes(asgi_app.quart_app)


def _mock_resolve_account(monkeypatch, account):
    """模拟已认证用户：替换 support._resolve_account 直接返回该账号（C-1 加固后测试模拟登录的方式）。"""

    async def _fake_resolve_account(account_id_override=None):
        return account, None

    monkeypatch.setattr(support, "_resolve_account", _fake_resolve_account)
    return account


_PROVIDER = {
    "id": str(uuid4()),
    "name": "openai",
    "label": "OpenAI",
    "description": "desc",
    "icon": "",
    "background": "#FFFFFF",
    "default_base_url": "https://api.openai.com/v1",
    "is_full_url": False,
    "supported_model_types": ["chat"],
    "status": "active",
    "model_count": 0,
    "created_at": 1893456000,
    "updated_at": 1893542400,
}

_PROVIDER_OPTION = {
    "id": str(uuid4()),
    "name": "openai",
    "label": "OpenAI",
    "description": "desc",
    "default_base_url": "https://api.openai.com/v1",
    "is_full_url": False,
    "supported_model_types": ["chat"],
}

_MODEL = {
    "id": str(uuid4()),
    "provider": "openai",
    "model_name": "gpt-4o",
    "display_name": "GPT-4o",
    "description": "",
    "tier": "standard",
    "capabilities": ["chat"],
    "price_per_1k_tokens": "0.030000",
    "max_tokens": 128000,
    "max_input_tokens": 124000,
    "max_output_tokens": 4000,
    "status": "active",
    "model_type": "chat",
    "compatible_api": "openai",
    "embedding_dimension": None,
    "created_at": 1893456000,
    "updated_at": 1893542400,
}

_KEY = {
    "id": str(uuid4()),
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
    "tier_name": "标准型",
    "sort_order": 2,
    "allowed_models": ["gpt-4o"],
    "default_model": "gpt-4o",
    "routing_rules": {},
    "created_at": 1893456000,
    "updated_at": 1893542400,
}

_COST_POLICY = {
    "id": str(uuid4()),
    "policy_name": "default",
    "model_tier": "standard",
    "max_cost_per_request": "0.500000",
    "billing_mode": "token",
    "upgrade_threshold": "0.100000",
    "created_at": 1893456000,
    "updated_at": 1893542400,
}


class _FakeAdminModelProviderService:
    def __init__(self):
        self.calls = []

    def list_providers(self, **kwargs):
        self.calls.append(("list_providers", kwargs))
        return {
            "list": [dict(_PROVIDER)],
            "paginator": {
                "total_record": 1,
                "total_page": 1,
                "current_page": 1,
                "page_size": 20,
            },
        }

    def list_provider_options(self):
        self.calls.append(("list_provider_options",))
        return {"options": [dict(_PROVIDER_OPTION)]}

    def create_provider(self, payload):
        self.calls.append(("create_provider", payload))
        return dict(_PROVIDER)

    def get_provider(self, provider_id):
        self.calls.append(("get_provider", provider_id))
        return dict(_PROVIDER, id=str(provider_id))

    def update_provider(self, provider_id, payload):
        self.calls.append(("update_provider", provider_id, payload))
        return dict(_PROVIDER, id=str(provider_id))

    def delete_provider(self, provider_id):
        self.calls.append(("delete_provider", provider_id))

    def set_provider_status(self, provider_id, status):
        self.calls.append(("set_provider_status", provider_id, status))
        return dict(_PROVIDER, id=str(provider_id), status=status)


class TestAdminModelProviderRoutes:
    def _setup(self, monkeypatch):
        from internal.service.admin_model_provider_service import (
            AdminModelProviderService,
        )

        account = SimpleNamespace(id=uuid4())
        fake = _FakeAdminModelProviderService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(
            support,
            "_get_service",
            lambda cls: fake if cls is AdminModelProviderService else None,
        )
        _mock_resolve_account(monkeypatch, account)
        return account, fake

    def test_list_providers(self, monkeypatch):
        _, fake = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/model-providers?account_id={uuid4()}&search=gpt&status=active&current_page=1&page_size=20"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["list"][0]["name"] == "openai"
        kwargs = fake.calls[0][1]
        assert kwargs["search"] == "gpt"
        assert kwargs["status"] == "active"
        assert kwargs["current_page"] == 1
        assert kwargs["page_size"] == 20

    def test_list_provider_options(self, monkeypatch):
        _, fake = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/model-providers/options?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["options"][0]["name"] == "openai"
        assert fake.calls[0][0] == "list_provider_options"

    def test_create_provider(self, monkeypatch):
        _, fake = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/model-providers?account_id={uuid4()}",
                    json={
                        "name": "openai",
                        "label": "OpenAI",
                        "default_base_url": "https://api.openai.com/v1",
                    },
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["name"] == "openai"
        assert fake.calls[0][0] == "create_provider"
        assert fake.calls[0][1]["is_full_url"] is False

    def test_create_provider_missing_required(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/model-providers?account_id={uuid4()}",
                    json={"name": "openai"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_get_provider(self, monkeypatch):
        _, fake = self._setup(monkeypatch)
        provider_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/model-providers/{provider_id}?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["id"] == str(provider_id)
        assert fake.calls[0] == ("get_provider", provider_id)

    def test_update_provider(self, monkeypatch):
        _, fake = self._setup(monkeypatch)
        provider_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    f"/admin/model-providers/{provider_id}?account_id={uuid4()}",
                    json={"label": "OpenAI Plus", "status": "disabled"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert fake.calls[0][0] == "update_provider"
        assert fake.calls[0][1] == provider_id
        assert fake.calls[0][2]["label"] == "OpenAI Plus"

    def test_update_provider_no_valid_fields(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    f"/admin/model-providers/{uuid4()}?account_id={uuid4()}",
                    json={"name": "not-allowed"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_delete_provider(self, monkeypatch):
        _, fake = self._setup(monkeypatch)
        provider_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(
                    f"/admin/model-providers/{provider_id}?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "删除成功"
        assert fake.calls[0] == ("delete_provider", provider_id)

    def test_set_provider_status(self, monkeypatch):
        _, fake = self._setup(monkeypatch)
        provider_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/model-providers/{provider_id}/status?account_id={uuid4()}",
                    json={"status": "disabled"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["status"] == "disabled"
        assert fake.calls[0] == ("set_provider_status", provider_id, "disabled")

    def test_set_provider_status_missing_status(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/model-providers/{uuid4()}/status?account_id={uuid4()}",
                    json={},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"


class _FakeAdminModelPoolService:
    def __init__(self):
        self.calls = []

    def list_models(self, **kwargs):
        self.calls.append(("list_models", kwargs))
        return {
            "list": [dict(_MODEL)],
            "paginator": {
                "total_record": 1,
                "total_page": 1,
                "current_page": 1,
                "page_size": 20,
            },
        }

    def create_model(self, payload):
        self.calls.append(("create_model", payload))
        return dict(_MODEL)

    def get_model(self, model_id):
        self.calls.append(("get_model", model_id))
        return dict(_MODEL, id=str(model_id))

    def update_model(self, model_id, payload):
        self.calls.append(("update_model", model_id, payload))
        return dict(_MODEL, id=str(model_id))

    def delete_model(self, model_id):
        self.calls.append(("delete_model", model_id))

    def set_model_status(self, model_id, status):
        self.calls.append(("set_model_status", model_id, status))
        return dict(_MODEL, id=str(model_id), status=status)

    def list_keys(self, **kwargs):
        self.calls.append(("list_keys", kwargs))
        return {
            "list": [dict(_KEY)],
            "paginator": {
                "total_record": 1,
                "total_page": 1,
                "current_page": 1,
                "page_size": 20,
            },
        }

    def create_key(self, payload):
        self.calls.append(("create_key", payload))
        return dict(_KEY)

    def update_key(self, key_id, payload):
        self.calls.append(("update_key", key_id, payload))
        return dict(_KEY, id=str(key_id))

    def delete_key(self, key_id):
        self.calls.append(("delete_key", key_id))

    def set_key_status(self, key_id, status):
        self.calls.append(("set_key_status", key_id, status))
        return dict(_KEY, id=str(key_id), status=status)

    def list_tier_policies(self):
        self.calls.append(("list_tier_policies",))
        return {"list": [dict(_TIER)]}

    def create_tier_policy(self, payload):
        self.calls.append(("create_tier_policy", payload))
        return dict(_TIER)

    def update_tier_policy(self, tier_code, payload):
        self.calls.append(("update_tier_policy", tier_code, payload))
        return dict(_TIER, tier_code=tier_code)

    def delete_tier_policy(self, tier_code):
        self.calls.append(("delete_tier_policy", tier_code))

    def list_cost_policies(self):
        self.calls.append(("list_cost_policies",))
        return {"list": [dict(_COST_POLICY)]}

    def create_cost_policy(self, payload):
        self.calls.append(("create_cost_policy", payload))
        return dict(_COST_POLICY)

    def update_cost_policy(self, policy_id, payload):
        self.calls.append(("update_cost_policy", policy_id, payload))
        return dict(_COST_POLICY, id=str(policy_id))


class TestAdminModelPoolRoutes:
    def _setup(self, monkeypatch):
        from internal.service.admin_model_pool_service import AdminModelPoolService

        account = SimpleNamespace(id=uuid4())
        fake = _FakeAdminModelPoolService()
        monkeypatch.setattr(support, "_load_account", lambda _aid: account)
        monkeypatch.setattr(
            support,
            "_get_service",
            lambda cls: fake if cls is AdminModelPoolService else None,
        )
        _mock_resolve_account(monkeypatch, account)
        return account, fake

    def test_list_models(self, monkeypatch):
        _, fake = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/models?account_id={uuid4()}&search=gpt&provider=openai&tier=standard&status=active&current_page=1&page_size=20"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["list"][0]["model_name"] == "gpt-4o"
        kwargs = fake.calls[0][1]
        assert kwargs["search"] == "gpt"
        assert kwargs["provider"] == "openai"
        assert kwargs["tier"] == "standard"
        assert kwargs["status"] == "active"
        assert kwargs["current_page"] == 1
        assert kwargs["page_size"] == 20

    def test_create_model(self, monkeypatch):
        _, fake = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/models?account_id={uuid4()}",
                    json={
                        "provider": "openai",
                        "model_name": "gpt-4o",
                        "tier": "standard",
                    },
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["model_name"] == "gpt-4o"
        assert fake.calls[0][0] == "create_model"
        assert fake.calls[0][1]["model_name"] == "gpt-4o"

    def test_get_model(self, monkeypatch):
        _, fake = self._setup(monkeypatch)
        model_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/models/{model_id}?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["id"] == str(model_id)
        assert fake.calls[0] == ("get_model", model_id)

    def test_update_model(self, monkeypatch):
        _, fake = self._setup(monkeypatch)
        model_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    f"/admin/models/{model_id}?account_id={uuid4()}",
                    json={"display_name": "GPT-4o Plus"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert fake.calls[0][0] == "update_model"
        assert fake.calls[0][1] == model_id
        assert fake.calls[0][2]["display_name"] == "GPT-4o Plus"

    def test_delete_model(self, monkeypatch):
        _, fake = self._setup(monkeypatch)
        model_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(
                    f"/admin/models/{model_id}?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "删除模型配置成功"
        assert fake.calls[0] == ("delete_model", model_id)

    def test_set_model_status(self, monkeypatch):
        _, fake = self._setup(monkeypatch)
        model_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/models/{model_id}/status?account_id={uuid4()}",
                    json={"status": "disabled"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["status"] == "disabled"
        assert fake.calls[0] == ("set_model_status", model_id, "disabled")

    def test_set_model_status_missing_status(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/models/{uuid4()}/status?account_id={uuid4()}",
                    json={},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_list_keys(self, monkeypatch):
        _, fake = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/model-keys?account_id={uuid4()}&provider=openai&status=active&current_page=1&page_size=20"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["list"][0]["key_alias"] == "main-key"
        kwargs = fake.calls[0][1]
        assert kwargs["provider"] == "openai"
        assert kwargs["status"] == "active"
        assert kwargs["current_page"] == 1
        assert kwargs["page_size"] == 20

    def test_create_key(self, monkeypatch):
        _, fake = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/model-keys?account_id={uuid4()}",
                    json={
                        "provider": "openai",
                        "key_alias": "main-key",
                        "key_value": "sk-1234567890",
                    },
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["key_alias"] == "main-key"
        assert fake.calls[0][0] == "create_key"
        assert fake.calls[0][1]["key_value"] == "sk-1234567890"

    def test_update_key(self, monkeypatch):
        _, fake = self._setup(monkeypatch)
        key_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    f"/admin/model-keys/{key_id}?account_id={uuid4()}",
                    json={"key_alias": "backup-key"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert fake.calls[0][0] == "update_key"
        assert fake.calls[0][1] == key_id
        assert fake.calls[0][2]["key_alias"] == "backup-key"

    def test_delete_key(self, monkeypatch):
        _, fake = self._setup(monkeypatch)
        key_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(
                    f"/admin/model-keys/{key_id}?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "删除模型Key成功"
        assert fake.calls[0] == ("delete_key", key_id)

    def test_set_key_status(self, monkeypatch):
        _, fake = self._setup(monkeypatch)
        key_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/model-keys/{key_id}/status?account_id={uuid4()}",
                    json={"status": "disabled"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["status"] == "disabled"
        assert fake.calls[0] == ("set_key_status", key_id, "disabled")

    def test_set_key_status_missing_status(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/model-keys/{uuid4()}/status?account_id={uuid4()}",
                    json={},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_list_tier_policies(self, monkeypatch):
        _, fake = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/model-tiers?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["list"][0]["tier_code"] == "standard"
        assert fake.calls[0][0] == "list_tier_policies"

    def test_create_tier_policy(self, monkeypatch):
        _, fake = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/model-tiers?account_id={uuid4()}",
                    json={"tier_code": "premium", "tier_name": "旗舰型"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["tier_code"] == "standard"
        assert fake.calls[0][0] == "create_tier_policy"
        assert fake.calls[0][1]["tier_code"] == "premium"

    def test_update_tier_policy(self, monkeypatch):
        _, fake = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.put(
                    f"/admin/model-tiers/standard?account_id={uuid4()}",
                    json={"default_model": "gpt-4o-mini"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert fake.calls[0][0] == "update_tier_policy"
        assert fake.calls[0][1] == "standard"
        assert fake.calls[0][2]["default_model"] == "gpt-4o-mini"

    def test_delete_tier_policy(self, monkeypatch):
        _, fake = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(
                    f"/admin/model-tiers/standard?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["message"] == "删除档位策略成功"
        assert fake.calls[0] == ("delete_tier_policy", "standard")

    def test_list_cost_policies(self, monkeypatch):
        _, fake = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/cost-policies?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["list"][0]["policy_name"] == "default"
        assert fake.calls[0][0] == "list_cost_policies"

    def test_create_cost_policy(self, monkeypatch):
        _, fake = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/cost-policies?account_id={uuid4()}",
                    json={
                        "policy_name": "default",
                        "model_tier": "standard",
                        "billing_mode": "token",
                    },
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["billing_mode"] == "token"
        assert fake.calls[0][0] == "create_cost_policy"
        assert fake.calls[0][1]["policy_name"] == "default"

    def test_update_cost_policy(self, monkeypatch):
        _, fake = self._setup(monkeypatch)
        policy_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.put(
                    f"/admin/cost-policies/{policy_id}?account_id={uuid4()}",
                    json={"max_cost_per_request": "0.800000", "billing_mode": "request"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert fake.calls[0][0] == "update_cost_policy"
        assert fake.calls[0][1] == policy_id
        assert fake.calls[0][2]["billing_mode"] == "request"
