from uuid import uuid4

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


class TestAdminAppHandler:
    def test_list_apps_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["app:read"])

        def _list(self, *, search, status, current_page, page_size):
            captured.update({"search": search, "status": status, "current_page": current_page, "page_size": page_size})
            return {
                "list": [{"id": "app-1", "name": "Demo", "icon": "", "description": "", "status": "draft", "is_public": False, "created_at": 1893456000, "updated_at": 1893456000}],
                "paginator": {"total_record": 1, "total_page": 1, "current_page": 1, "page_size": 20},
            }

        monkeypatch.setattr("internal.service.admin_app_service.AdminAppService.list_apps", _list, raising=False)

        resp = client.get(
            "/admin/apps?search=Demo&status=draft&current_page=1&page_size=20",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["name"] == "Demo"
        assert captured == {"search": "Demo", "status": "draft", "current_page": 1, "page_size": 20}

    def test_get_app_should_delegate_to_service(self, client, monkeypatch):
        app_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["app:read"])

        def _get(self, app_id_arg):
            captured["app_id"] = app_id_arg
            return {"id": str(app_id_arg), "name": "Demo", "icon": "", "description": "", "status": "draft", "is_public": False, "created_at": 1893456000, "updated_at": 1893456000}

        monkeypatch.setattr("internal.service.admin_app_service.AdminAppService.get_app", _get, raising=False)

        resp = client.get(f"/admin/apps/{app_id}", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["id"] == str(app_id)
        assert captured == {"app_id": app_id}

    def test_update_app_should_delegate_to_service(self, client, monkeypatch):
        app_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["app:update"])

        def _update(self, app_id_arg, *, status=None, is_public=None):
            captured.update({"app_id": app_id_arg, "status": status, "is_public": is_public})
            return {"id": str(app_id_arg), "name": "Demo", "icon": "", "description": "", "status": status, "is_public": is_public, "created_at": 1893456000, "updated_at": 1893456000}

        monkeypatch.setattr("internal.service.admin_app_service.AdminAppService.update_app", _update, raising=False)

        resp = client.patch(
            f"/admin/apps/{app_id}",
            json={"status": "published", "is_public": True},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured == {"app_id": app_id, "status": "published", "is_public": True}

    def test_offline_app_should_delegate_to_service(self, client, monkeypatch):
        app_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["app:update"])

        def _offline(self, app_id_arg):
            captured["app_id"] = app_id_arg

        monkeypatch.setattr("internal.service.admin_app_service.AdminAppService.offline_app", _offline, raising=False)

        resp = client.post(f"/admin/apps/{app_id}/offline", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["message"] == "下架应用成功"
        assert captured == {"app_id": app_id}

    def test_list_apps_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["admin:access"])

        resp = client.get("/admin/apps", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN
