from uuid import uuid4

import pytest

from pkg.response import HttpCode


_POLICY_ID = uuid4()
_AUDIT_ID = uuid4()

_POLICY = {
    "id": str(_POLICY_ID),
    "tool_id": "weather_api",
    "tool_name": "天气查询",
    "source_type": "api_tool",
    "provider_id": "prov-1",
    "risk_level": "medium",
    "visibility": "tenant",
    "allowed_pools": ["tenant", "system"],
    "enabled": True,
    "max_invocations_per_request": 5,
    "cooldown_seconds": 10,
    "require_confirmation": False,
    "description": "查询天气信息",
    "created_at": 1893456000,
    "updated_at": 1893542400,
}

_AUDIT = {
    "id": str(_AUDIT_ID),
    "tool_id": "weather_api",
    "tool_name": "天气查询",
    "account_id": "",
    "conversation_id": "",
    "invocation_status": "success",
    "duration_ms": 120,
    "error_message": "",
    "created_at": 1893456000,
}

_STATS = {
    "total": 10,
    "enabled": 8,
    "disabled": 2,
    "enabled_rate": 0.8,
    "risk_distribution": {"low": 4, "medium": 3, "high": 2, "critical": 1},
    "source_distribution": {"api_tool": 4, "mcp": 3, "skill": 2, "builtin": 1},
    "visibility_distribution": {"private": 5, "tenant": 3, "public": 2},
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


class TestAdminToolGovernanceHandler:
    def test_list_policies_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["tool_governance:read"])

        def _list(self, **kwargs):
            captured.update(kwargs)
            return {"list": [_POLICY], "paginator": {"total_record": 1, "total_page": 1, "current_page": 1, "page_size": 20}}

        monkeypatch.setattr("internal.service.admin_tool_governance_service.AdminToolGovernanceService.list_policies", _list, raising=False)

        resp = client.get(
            "/admin/tool-governance?source_type=api_tool&risk_level=medium&visibility=tenant&enabled=true&keyword=weather&current_page=1&page_size=20",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["tool_id"] == "weather_api"
        assert captured == {
            "source_type": "api_tool",
            "risk_level": "medium",
            "visibility": "tenant",
            "enabled": "true",
            "keyword": "weather",
            "current_page": 1,
            "page_size": 20,
        }

    def test_create_policy_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["tool_governance:manage"])

        def _create(self, payload):
            captured["payload"] = payload
            return {**_POLICY, "tool_id": payload["tool_id"]}

        monkeypatch.setattr("internal.service.admin_tool_governance_service.AdminToolGovernanceService.create_policy", _create, raising=False)

        resp = client.post(
            "/admin/tool-governance",
            json={
                "tool_id": "weather_api",
                "tool_name": "天气查询",
                "source_type": "api_tool",
                "risk_level": "medium",
                "visibility": "tenant",
                "allowed_pools": ["tenant", "system"],
            },
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["tool_id"] == "weather_api"
        assert captured["payload"]["source_type"] == "api_tool"

    def test_get_policy_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["tool_governance:read"])

        def _get(self, policy_id_arg):
            captured["policy_id"] = policy_id_arg
            return {**_POLICY, "id": str(policy_id_arg)}

        monkeypatch.setattr("internal.service.admin_tool_governance_service.AdminToolGovernanceService.get_policy", _get, raising=False)

        resp = client.get(f"/admin/tool-governance/{_POLICY_ID}", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["id"] == str(_POLICY_ID)
        assert captured == {"policy_id": _POLICY_ID}

    def test_update_policy_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["tool_governance:manage"])

        def _update(self, policy_id_arg, payload):
            captured.update({"policy_id": policy_id_arg, "payload": payload})
            return {**_POLICY, "id": str(policy_id_arg), "risk_level": payload.get("risk_level", _POLICY["risk_level"])}

        monkeypatch.setattr("internal.service.admin_tool_governance_service.AdminToolGovernanceService.update_policy", _update, raising=False)

        resp = client.patch(
            f"/admin/tool-governance/{_POLICY_ID}",
            json={"risk_level": "high", "visibility": "public"},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["risk_level"] == "high"
        assert captured["policy_id"] == _POLICY_ID
        assert captured["payload"]["visibility"] == "public"

    def test_delete_policy_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["tool_governance:manage"])

        def _delete(self, policy_id_arg):
            captured["policy_id"] = policy_id_arg

        monkeypatch.setattr("internal.service.admin_tool_governance_service.AdminToolGovernanceService.delete_policy", _delete, raising=False)

        resp = client.delete(f"/admin/tool-governance/{_POLICY_ID}", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured == {"policy_id": _POLICY_ID}

    def test_set_status_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["tool_governance:manage"])

        def _set_enabled(self, policy_id_arg, enabled):
            captured.update({"policy_id": policy_id_arg, "enabled": enabled})
            return {**_POLICY, "id": str(policy_id_arg), "enabled": enabled}

        monkeypatch.setattr("internal.service.admin_tool_governance_service.AdminToolGovernanceService.set_enabled", _set_enabled, raising=False)

        resp = client.post(
            f"/admin/tool-governance/{_POLICY_ID}/status",
            json={"enabled": False},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["enabled"] is False
        assert captured == {"policy_id": _POLICY_ID, "enabled": False}

    def test_batch_update_risk_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["tool_governance:manage"])
        other_id = uuid4()

        def _batch(self, policy_ids, risk_level):
            captured.update({"policy_ids": policy_ids, "risk_level": risk_level})
            return {"updated": len(policy_ids), "risk_level": risk_level}

        monkeypatch.setattr("internal.service.admin_tool_governance_service.AdminToolGovernanceService.batch_update_risk", _batch, raising=False)

        resp = client.post(
            "/admin/tool-governance/batch-risk",
            json={"policy_ids": [str(_POLICY_ID), str(other_id)], "risk_level": "critical"},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["updated"] == 2
        assert resp.json["data"]["risk_level"] == "critical"
        assert captured["risk_level"] == "critical"
        assert captured["policy_ids"] == [str(_POLICY_ID), str(other_id)]

    def test_list_audit_logs_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["tool_governance:read"])

        def _list(self, **kwargs):
            captured.update(kwargs)
            return {"list": [_AUDIT], "paginator": {"total_record": 1, "total_page": 1, "current_page": 1, "page_size": 20}}

        monkeypatch.setattr("internal.service.admin_tool_governance_service.AdminToolGovernanceService.list_audit_logs", _list, raising=False)

        resp = client.get(
            "/admin/tool-governance/audit?tool_id=weather_api&status=success&start_date=2025-01-01&end_date=2025-12-31&current_page=1&page_size=20",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["tool_id"] == "weather_api"
        assert captured == {
            "tool_id": "weather_api",
            "status": "success",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "current_page": 1,
            "page_size": 20,
        }

    def test_stats_should_delegate_to_service(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["tool_governance:read"])

        def _stats(self):
            return _STATS

        monkeypatch.setattr("internal.service.admin_tool_governance_service.AdminToolGovernanceService.get_governance_stats", _stats, raising=False)

        resp = client.get("/admin/tool-governance/stats", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["total"] == 10
        assert resp.json["data"]["enabled"] == 8
        assert resp.json["data"]["risk_distribution"]["critical"] == 1
        assert resp.json["data"]["source_distribution"]["mcp"] == 3

    def test_list_policies_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["admin:access"])

        resp = client.get("/admin/tool-governance", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN

    def test_create_policy_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["tool_governance:read"])

        resp = client.post(
            "/admin/tool-governance",
            json={"tool_id": "weather_api"},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN

    def test_set_status_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["tool_governance:read"])

        resp = client.post(
            f"/admin/tool-governance/{_POLICY_ID}/status",
            json={"enabled": False},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN

    def test_batch_update_risk_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["tool_governance:read"])

        resp = client.post(
            "/admin/tool-governance/batch-risk",
            json={"policy_ids": [str(_POLICY_ID)], "risk_level": "high"},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN
