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


_PLAN = {
    "id": "plan-1",
    "code": "pro",
    "name": "Pro",
    "description": "Pro plan",
    "duration_days": 30,
    "grant_token_credits": 100000,
    "price": "99.00",
    "status": "active",
    "sort_order": 10,
    "created_at": 1893456000,
    "updated_at": 1893542400,
}


class TestAdminBillingPlanHandler:
    def test_list_plans_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["plan:read"])

        def _list(self, *, keyword, status, current_page, page_size):
            captured.update({"keyword": keyword, "status": status, "current_page": current_page, "page_size": page_size})
            return {"list": [_PLAN], "paginator": {"total_record": 1, "total_page": 1, "current_page": 1, "page_size": 20}}

        monkeypatch.setattr("internal.service.admin_billing_plan_service.AdminBillingPlanService.list_plans", _list, raising=False)

        resp = client.get("/admin/plans?keyword=pro&status=active&current_page=1&page_size=20", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["code"] == "pro"
        assert captured == {"keyword": "pro", "status": "active", "current_page": 1, "page_size": 20}

    def test_get_plan_should_delegate_to_service(self, client, monkeypatch):
        plan_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["plan:read"])

        def _get(self, plan_id_arg):
            captured["plan_id"] = plan_id_arg
            return {**_PLAN, "id": str(plan_id_arg), "entitlements": []}

        monkeypatch.setattr("internal.service.admin_billing_plan_service.AdminBillingPlanService.get_plan", _get, raising=False)

        resp = client.get(f"/admin/plans/{plan_id}", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["id"] == str(plan_id)
        assert captured == {"plan_id": plan_id}

    def test_create_plan_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["plan:update"])

        def _create(self, payload, *, operator_id=None, ip="", user_agent=""):
            captured.update({"payload": payload, "operator_id": operator_id, "ip": ip, "user_agent": user_agent})
            return {**_PLAN, "code": payload["code"], "name": payload["name"]}

        monkeypatch.setattr("internal.service.admin_billing_plan_service.AdminBillingPlanService.create_plan", _create, raising=False)

        resp = client.post(
            "/admin/plans",
            json={
                "code": "team",
                "name": "Team",
                "duration_days": 90,
                "grant_token_credits": 300000,
                "price": "199.00",
                "status": "active",
                "entitlements": [{"feature_key": "max_agents", "feature_value": "20", "value_type": "number"}],
            },
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["code"] == "team"
        assert captured["operator_id"] == "admin-1"
        assert captured["payload"]["entitlements"][0]["feature_key"] == "max_agents"

    def test_update_plan_should_delegate_to_service(self, client, monkeypatch):
        plan_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["plan:update"])

        def _update(self, plan_id_arg, payload, *, operator_id=None, ip="", user_agent=""):
            captured.update({"plan_id": plan_id_arg, "payload": payload, "operator_id": operator_id})
            return {**_PLAN, "id": str(plan_id_arg), "name": payload["name"]}

        monkeypatch.setattr("internal.service.admin_billing_plan_service.AdminBillingPlanService.update_plan", _update, raising=False)

        resp = client.post(f"/admin/plans/{plan_id}", json={"name": "Pro Plus"}, headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["name"] == "Pro Plus"
        assert captured["plan_id"] == plan_id

    def test_set_plan_status_should_delegate_to_service(self, client, monkeypatch):
        plan_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["plan:update"])

        def _set_status(self, plan_id_arg, status, *, operator_id=None, ip="", user_agent=""):
            captured.update({"plan_id": plan_id_arg, "status": status, "operator_id": operator_id})
            return {**_PLAN, "id": str(plan_id_arg), "status": status}

        monkeypatch.setattr("internal.service.admin_billing_plan_service.AdminBillingPlanService.set_plan_status", _set_status, raising=False)

        resp = client.post(f"/admin/plans/{plan_id}/status", json={"status": "disabled"}, headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["status"] == "disabled"
        assert captured == {"plan_id": plan_id, "status": "disabled", "operator_id": "admin-1"}

    def test_list_plans_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["admin:access"])

        resp = client.get("/admin/plans", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN
