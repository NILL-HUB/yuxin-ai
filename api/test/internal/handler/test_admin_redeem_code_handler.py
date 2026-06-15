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


class TestAdminRedeemCodeHandler:
    def test_generate_codes_should_delegate_to_service(self, client, monkeypatch):
        plan_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["redeem_code:update"])

        def _generate(self, payload, *, operator_id=None, ip="", user_agent=""):
            captured.update({"payload": payload, "operator_id": operator_id, "ip": ip, "user_agent": user_agent})
            return {
                "batch": {"id": "batch-1", "name": payload["name"], "plan_id": str(plan_id), "quantity": payload["quantity"], "expires_at": None, "created_by": operator_id, "created_at": 1893456000},
                "codes": [{"plain_code": "OA-ABC", "code_mask": "OAAB****C"}],
            }

        monkeypatch.setattr("internal.service.admin_redeem_code_service.AdminRedeemCodeService.generate_codes", _generate, raising=False)

        resp = client.post(
            "/admin/redeem-code-batches",
            json={"name": "Batch", "plan_id": str(plan_id), "quantity": 1},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["codes"][0]["plain_code"] == "OA-ABC"
        assert captured["operator_id"] == "admin-1"
        assert captured["payload"]["plan_id"] == plan_id

    def test_list_batches_should_delegate_to_service(self, client, monkeypatch):
        captured = {}
        _mock_current_admin(monkeypatch, ["redeem_code:read"])

        def _list(self, *, keyword, current_page, page_size):
            captured.update({"keyword": keyword, "current_page": current_page, "page_size": page_size})
            return {"list": [], "paginator": {"total_record": 0, "total_page": 0, "current_page": 1, "page_size": 20}}

        monkeypatch.setattr("internal.service.admin_redeem_code_service.AdminRedeemCodeService.list_batches", _list, raising=False)

        resp = client.get(
            "/admin/redeem-code-batches",
            query_string={"keyword": "Batch", "current_page": 1, "page_size": 20},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured == {"keyword": "Batch", "current_page": 1, "page_size": 20}

    def test_list_codes_should_delegate_to_service_and_not_return_plain_code(self, client, monkeypatch):
        batch_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["redeem_code:read"])

        def _list_codes(self, *, batch_id=None, status="", code_keyword="", current_page=1, page_size=20):
            captured.update({"batch_id": batch_id, "status": status, "code_keyword": code_keyword, "current_page": current_page, "page_size": page_size})
            return {
                "list": [{"id": "code-1", "batch_id": str(batch_id), "plan_id": "plan-1", "code_mask": "OAAB****C", "status": "unused", "redeemed_by": None, "redeemed_at": None, "expires_at": None, "disabled_at": None, "created_at": 1893456000}],
                "paginator": {"total_record": 1, "total_page": 1, "current_page": 1, "page_size": 20},
            }

        monkeypatch.setattr("internal.service.admin_redeem_code_service.AdminRedeemCodeService.list_codes", _list_codes, raising=False)

        resp = client.get(f"/admin/redeem-codes?batch_id={batch_id}&status=unused&code_keyword=OAAB", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["code_mask"] == "OAAB****C"
        assert "plain_code" not in resp.json["data"]["list"][0]
        assert captured["batch_id"] == batch_id
        assert captured["code_keyword"] == "OAAB"

    def test_disable_code_should_delegate_to_service(self, client, monkeypatch):
        code_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["redeem_code:update"])

        def _disable(self, code_id_arg, *, operator_id=None, ip="", user_agent=""):
            captured.update({"code_id": code_id_arg, "operator_id": operator_id, "ip": ip, "user_agent": user_agent})
            return {"id": str(code_id_arg), "batch_id": None, "plan_id": "plan-1", "code_mask": "OAAB****C", "status": "disabled", "redeemed_by": None, "redeemed_at": None, "expires_at": None, "disabled_at": 1893456000, "created_at": 1893456000}

        monkeypatch.setattr("internal.service.admin_redeem_code_service.AdminRedeemCodeService.disable_code", _disable, raising=False)

        resp = client.post(f"/admin/redeem-codes/{code_id}/disable", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["status"] == "disabled"
        assert captured["code_id"] == code_id

    def test_disable_batch_should_delegate_to_service(self, client, monkeypatch):
        batch_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["redeem_code:update"])

        def _disable_batch(self, batch_id_arg, *, operator_id=None, ip="", user_agent=""):
            captured.update({"batch_id": batch_id_arg, "operator_id": operator_id, "ip": ip, "user_agent": user_agent})
            return {"id": str(batch_id_arg), "name": "Batch", "plan_id": "plan-1", "quantity": 1, "status": "disabled", "disabled_at": 1893456000, "expires_at": None, "created_by": operator_id, "created_at": 1893456000}

        monkeypatch.setattr("internal.service.admin_redeem_code_service.AdminRedeemCodeService.disable_batch", _disable_batch, raising=False)

        resp = client.post(f"/admin/redeem-code-batches/{batch_id}/disable", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["status"] == "disabled"
        assert captured["batch_id"] == batch_id

    def test_list_codes_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["admin:access"])

        resp = client.get("/admin/redeem-codes", headers={"Authorization": "Bearer admin-token"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN
