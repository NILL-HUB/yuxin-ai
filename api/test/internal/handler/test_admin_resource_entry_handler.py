from pkg.response import HttpCode


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
    def test_dataset_entry_should_require_dataset_read(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["dataset:read"])

        resp = client.get("/admin/datasets", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"] == {"list": [], "paginator": {"total_record": 0, "total_page": 0, "current_page": 1, "page_size": 20}}

    def test_tool_entry_should_require_tool_read(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["tool:read"])

        resp = client.get("/admin/tools", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"] == []

    def test_mcp_entry_should_require_mcp_read(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["mcp:read"])

        resp = client.get("/admin/mcp", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"] == []

    def test_skill_entry_should_require_skill_read(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["skill:read"])

        resp = client.get("/admin/skills", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"] == []

    def test_resource_entry_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["admin:access"])

        resp = client.get("/admin/datasets", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN
