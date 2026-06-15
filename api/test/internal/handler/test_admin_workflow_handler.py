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


class TestAdminWorkflowHandler:
    def test_list_workflows_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["workflow:read"])

        def _list(self, *, search, status, current_page, page_size):
            captured.update({"search": search, "status": status, "current_page": current_page, "page_size": page_size})
            return {
                "list": [{"id": "workflow-1", "name": "Demo", "tool_call_name": "demo", "icon": "", "description": "", "status": "draft", "is_public": False, "created_at": 1893456000, "updated_at": 1893456000}],
                "paginator": {"total_record": 1, "total_page": 1, "current_page": 1, "page_size": 20},
            }

        monkeypatch.setattr("internal.service.admin_workflow_service.AdminWorkflowService.list_workflows", _list, raising=False)

        resp = client.get(
            "/admin/workflows?search=Demo&status=draft&current_page=1&page_size=20",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["name"] == "Demo"
        assert captured == {"search": "Demo", "status": "draft", "current_page": 1, "page_size": 20}

    def test_get_workflow_should_delegate_to_service(self, client, monkeypatch):
        workflow_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["workflow:read"])

        def _get(self, workflow_id_arg):
            captured["workflow_id"] = workflow_id_arg
            return {"id": str(workflow_id_arg), "name": "Demo", "tool_call_name": "demo", "icon": "", "description": "", "status": "draft", "is_public": False, "created_at": 1893456000, "updated_at": 1893456000}

        monkeypatch.setattr("internal.service.admin_workflow_service.AdminWorkflowService.get_workflow", _get, raising=False)

        resp = client.get(f"/admin/workflows/{workflow_id}", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["id"] == str(workflow_id)
        assert captured == {"workflow_id": workflow_id}

    def test_update_workflow_should_delegate_to_service(self, client, monkeypatch):
        workflow_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["workflow:update"])

        def _update(self, workflow_id_arg, *, status=None, is_public=None):
            captured.update({"workflow_id": workflow_id_arg, "status": status, "is_public": is_public})
            return {"id": str(workflow_id_arg), "name": "Demo", "tool_call_name": "demo", "icon": "", "description": "", "status": status, "is_public": is_public, "created_at": 1893456000, "updated_at": 1893456000}

        monkeypatch.setattr("internal.service.admin_workflow_service.AdminWorkflowService.update_workflow", _update, raising=False)

        resp = client.patch(
            f"/admin/workflows/{workflow_id}",
            json={"status": "published", "is_public": True},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured == {"workflow_id": workflow_id, "status": "published", "is_public": True}

    def test_offline_workflow_should_delegate_to_service(self, client, monkeypatch):
        workflow_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["workflow:update"])

        def _offline(self, workflow_id_arg):
            captured["workflow_id"] = workflow_id_arg

        monkeypatch.setattr("internal.service.admin_workflow_service.AdminWorkflowService.offline_workflow", _offline, raising=False)

        resp = client.post(f"/admin/workflows/{workflow_id}/offline", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["message"] == "下架工作流成功"
        assert captured == {"workflow_id": workflow_id}

    def test_list_workflows_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["admin:access"])

        resp = client.get("/admin/workflows", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN
