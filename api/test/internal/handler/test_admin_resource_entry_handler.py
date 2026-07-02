import os

import pytest

from pkg.response import HttpCode

os.environ["ADMIN_BOOTSTRAP_ENABLED"] = "0"


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


class TestAdminResourceEntryHandler:
    def test_tool_entry_should_require_tool_read(self, app, monkeypatch):
        _mock_current_admin(monkeypatch, ["tool:read"])
        captured = {}

        def _list(self, **kwargs):
            captured.update(kwargs)
            return {"list": [{"tool_id": "api_tool_1"}], "paginator": {"total_record": 1, "total_page": 1, "current_page": 1, "page_size": 20}}

        monkeypatch.setattr("internal.service.admin_tool_governance_service.AdminToolGovernanceService.list_policies", _list, raising=False)

        with app.test_client() as http_client:
            resp = http_client.get("/admin/tools", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["tool_id"] == "api_tool_1"
        assert captured["source_type"] == "api_tool"

    def test_mcp_entry_should_require_mcp_read(self, app, monkeypatch):
        _mock_current_admin(monkeypatch, ["mcp:read"])
        captured = {}

        def _list(self, req):
            captured["search_word"] = req.search_word.data
            captured["category"] = req.category.data
            return (
                [
                    {
                        "id": "provider-1",
                        "provider_key": "db:provider-1",
                        "name": "weather_mcp",
                        "label": "天气MCP",
                        "icon": "",
                        "background": "#0f172a",
                        "description": "天气服务",
                        "category": "productivity",
                        "transport": "streamable_http",
                        "url": "https://example.com/mcp",
                        "command": "",
                        "headers": [],
                        "tool_names": [],
                        "args": [],
                        "env": {},
                        "timeout_seconds": 30,
                        "source_type": "custom",
                        "source_key": "weather_mcp",
                        "source_url": "https://example.com/mcp",
                        "creator_name": "Alice",
                        "creator_avatar": "",
                        "is_public": True,
                        "is_bindable": True,
                        "bind_reason": "",
                        "published_at": 1710000000,
                        "created_at": 1710000000,
                        "updated_at": 1710003600,
                        "tool_count": 3,
                        "tools": [],
                        "binding": {},
                    }
                ],
                {"total_record": 1, "total_page": 1, "current_page": 1, "page_size": 20},
            )

        monkeypatch.setattr("internal.service.mcp_service.McpService.get_admin_mcp_providers_with_page", _list, raising=False)

        with app.test_client() as http_client:
            resp = http_client.get("/admin/mcp", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["provider_key"] == "db:provider-1"
        assert resp.json["data"]["list"][0]["tool_count"] == 3
        assert captured["search_word"] == ""
        assert captured["category"] == ""

    def test_skill_entry_should_require_skill_read(self, app, monkeypatch):
        _mock_current_admin(monkeypatch, ["skill:read"])
        captured = {}

        def _list(self, req):
            captured["search_word"] = req.search_word.data
            captured["category"] = req.category.data
            return (
                [
                    {
                        "id": "skill-1",
                        "source_key": "frontend-skill",
                        "name": "frontend-skill",
                        "label": "Frontend Skill",
                        "icon": "",
                        "description": "Build strong frontend interfaces",
                        "readme": "",
                        "category": "frontend",
                        "tags": [],
                        "capabilities": {},
                        "executor_type": "prompt",
                        "tool_count": 0,
                        "tools": [],
                        "created_at": 1710000000,
                        "updated_at": 1710003600,
                    }
                ],
                {"total_record": 1, "total_page": 1, "current_page": 1, "page_size": 20},
            )

        monkeypatch.setattr("internal.service.skill_service.SkillService.get_skill_packages_with_page", _list, raising=False)

        with app.test_client() as http_client:
            resp = http_client.get("/admin/skills", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["source_key"] == "frontend-skill"
        assert resp.json["data"]["list"][0]["executor_type"] == "prompt"
        assert captured["search_word"] == ""
        assert captured["category"] == ""

    def test_tool_entry_should_reject_missing_permission(self, app, monkeypatch):
        _mock_current_admin(monkeypatch, ["admin:access"])

        with app.test_client() as http_client:
            resp = http_client.get("/admin/tools", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN
