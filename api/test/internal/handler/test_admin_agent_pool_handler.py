from uuid import uuid4

import pytest

from pkg.response import HttpCode


_CONFIG_ID = uuid4()
_APP_ID = uuid4()

_CONFIG = {
    "id": str(_CONFIG_ID),
    "app_id": str(_APP_ID),
    "primary_pool": "tenant",
    "secondary_pools": ["system", "global"],
    "risk_level": "medium",
    "model_tier": "standard",
    "model_id": "deepseek-chat",
    "routing_priority": 100,
    "enabled": True,
    "health_status": "healthy",
    "last_health_check_at": 1893542400,
    "metadata": {"source": "admin"},
    "created_at": 1893456000,
    "updated_at": 1893542400,
}

_STATS = {
    "list": [
        {"pool": "tenant", "total": 5, "enabled": 4, "healthy": 3},
        {"pool": "system", "total": 3, "enabled": 3, "healthy": 2},
        {"pool": "global", "total": 2, "enabled": 1, "healthy": 1},
    ]
}


@pytest.fixture
def db(app):
    from internal.extension.database_extension import db as _db
    with app.app_context():
        yield _db


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


class TestAdminAgentPoolHandler:
    def test_list_configs_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["agent_pool:read"])

        def _list(self, *, page, per_page, pool, enabled, keyword):
            captured.update({"page": page, "per_page": per_page, "pool": pool, "enabled": enabled, "keyword": keyword})
            return {"list": [_CONFIG], "paginator": {"total_record": 1, "total_page": 1, "current_page": 1, "page_size": 20}}

        monkeypatch.setattr("internal.service.admin_agent_pool_service.AdminAgentPoolService.list_configs", _list, raising=False)

        resp = client.get(
            "/admin/agent-pool?keyword=tenant&pool=tenant&enabled=true&current_page=1&page_size=20",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["primary_pool"] == "tenant"
        assert captured == {"page": 1, "per_page": 20, "pool": "tenant", "enabled": "true", "keyword": "tenant"}

    def test_create_config_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["agent_pool:manage"])

        def _create(self, payload):
            captured["payload"] = payload
            return {**_CONFIG, "primary_pool": payload.get("primary_pool", _CONFIG["primary_pool"])}

        monkeypatch.setattr("internal.service.admin_agent_pool_service.AdminAgentPoolService.create_config", _create, raising=False)

        resp = client.post(
            "/admin/agent-pool",
            json={
                "app_id": str(_APP_ID),
                "primary_pool": "system",
                "secondary_pools": ["global"],
                "risk_level": "low",
                "model_tier": "cheap",
                "model_id": "deepseek-chat",
                "routing_priority": 50,
                "enabled": "true",
            },
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["primary_pool"] == "system"
        assert captured["payload"]["app_id"] == str(_APP_ID)
        assert captured["payload"]["primary_pool"] == "system"

    def test_get_config_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["agent_pool:read"])

        def _get(self, config_id_arg):
            captured["config_id"] = config_id_arg
            return {**_CONFIG, "id": str(config_id_arg)}

        monkeypatch.setattr("internal.service.admin_agent_pool_service.AdminAgentPoolService.get_config", _get, raising=False)

        resp = client.get(f"/admin/agent-pool/{_CONFIG_ID}", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["id"] == str(_CONFIG_ID)
        assert captured == {"config_id": _CONFIG_ID}

    def test_update_config_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["agent_pool:manage"])

        def _update(self, config_id_arg, payload):
            captured.update({"config_id": config_id_arg, "payload": payload})
            return {**_CONFIG, "id": str(config_id_arg), "risk_level": payload.get("risk_level", _CONFIG["risk_level"])}

        monkeypatch.setattr("internal.service.admin_agent_pool_service.AdminAgentPoolService.update_config", _update, raising=False)

        resp = client.patch(
            f"/admin/agent-pool/{_CONFIG_ID}",
            json={"risk_level": "high", "model_tier": "strong"},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["risk_level"] == "high"
        assert captured["config_id"] == _CONFIG_ID
        assert captured["payload"]["risk_level"] == "high"

    def test_delete_config_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["agent_pool:manage"])

        def _delete(self, config_id_arg):
            captured["config_id"] = config_id_arg

        monkeypatch.setattr("internal.service.admin_agent_pool_service.AdminAgentPoolService.delete_config", _delete, raising=False)

        resp = client.delete(f"/admin/agent-pool/{_CONFIG_ID}", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured == {"config_id": _CONFIG_ID}

    def test_set_status_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["agent_pool:manage"])

        def _set_enabled(self, config_id_arg, enabled):
            captured.update({"config_id": config_id_arg, "enabled": enabled})
            return {**_CONFIG, "id": str(config_id_arg), "enabled": enabled}

        monkeypatch.setattr("internal.service.admin_agent_pool_service.AdminAgentPoolService.set_enabled", _set_enabled, raising=False)

        resp = client.post(
            f"/admin/agent-pool/{_CONFIG_ID}/status",
            json={"enabled": "false"},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["enabled"] is False
        assert captured == {"config_id": _CONFIG_ID, "enabled": False}

    def test_set_status_should_enable_config(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["agent_pool:manage"])

        def _set_enabled(self, config_id_arg, enabled):
            captured.update({"config_id": config_id_arg, "enabled": enabled})
            return {**_CONFIG, "id": str(config_id_arg), "enabled": enabled}

        monkeypatch.setattr("internal.service.admin_agent_pool_service.AdminAgentPoolService.set_enabled", _set_enabled, raising=False)

        resp = client.post(
            f"/admin/agent-pool/{_CONFIG_ID}/status",
            json={"enabled": "true"},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["enabled"] is True
        assert captured == {"config_id": _CONFIG_ID, "enabled": True}

    def test_check_health_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["agent_pool:manage"])

        def _check(self, config_id_arg):
            captured["config_id"] = config_id_arg
            return {**_CONFIG, "id": str(config_id_arg), "health_status": "healthy"}

        monkeypatch.setattr("internal.service.admin_agent_pool_service.AdminAgentPoolService.check_health", _check, raising=False)

        resp = client.post(f"/admin/agent-pool/{_CONFIG_ID}/health", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["health_status"] == "healthy"
        assert captured == {"config_id": _CONFIG_ID}

    def test_list_stats_should_delegate_to_service(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["agent_pool:read"])

        def _stats(self):
            return _STATS

        monkeypatch.setattr("internal.service.admin_agent_pool_service.AdminAgentPoolService.list_pool_stats", _stats, raising=False)

        resp = client.get("/admin/agent-pool/stats", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert len(resp.json["data"]["list"]) == 3
        assert resp.json["data"]["list"][0]["pool"] == "tenant"
        assert resp.json["data"]["list"][0]["total"] == 5
        assert resp.json["data"]["list"][0]["enabled"] == 4
        assert resp.json["data"]["list"][0]["healthy"] == 3

    def test_list_configs_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["admin:access"])

        resp = client.get("/admin/agent-pool", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN

    def test_create_config_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["agent_pool:read"])

        resp = client.post(
            "/admin/agent-pool",
            json={"app_id": str(_APP_ID), "primary_pool": "tenant"},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN

    def test_check_health_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["agent_pool:read"])

        resp = client.post(f"/admin/agent-pool/{_CONFIG_ID}/health", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN

    def test_list_stats_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["admin:access"])

        resp = client.get("/admin/agent-pool/stats", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN
