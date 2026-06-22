from types import SimpleNamespace
from uuid import uuid4

import pytest

from pkg.response import HttpCode


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


def _mock_current_user(monkeypatch, account_id):
    monkeypatch.setattr(
        "internal.handler.showcase_handler.current_user",
        SimpleNamespace(id=account_id, is_authenticated=True),
    )


class TestShowcaseHandler:
    def test_create_case_should_delegate_to_service_with_current_user(self, client, monkeypatch):
        account_id = uuid4()
        conversation_id = uuid4()
        captured = {}
        _mock_current_user(monkeypatch, account_id)

        def _create(self, **kwargs):
            captured.update(kwargs)
            return {
                "id": "case-1",
                "conversation_id": str(kwargs.get("conversation_id")),
                "account_id": str(kwargs.get("account_id")),
                "title": kwargs.get("title"),
                "summary": kwargs.get("summary"),
                "query": kwargs.get("query"),
                "answer": kwargs.get("answer"),
                "tags": kwargs.get("tags"),
                "rating": kwargs.get("rating"),
                "status": "pending",
                "reject_reason": "",
                "created_at": 0,
                "approved_at": None,
                "approved_by": None,
                "updated_at": 0,
            }

        monkeypatch.setattr("internal.service.showcase_service.ShowcaseService.create_case", _create, raising=False)

        resp = client.post(
            "/showcase/cases",
            json={
                "conversation_id": str(conversation_id),
                "title": "好案例",
                "summary": "摘要",
                "query": "问题",
                "answer": "回答",
                "tags": ["ai", "demo"],
                "rating": 5,
            },
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured["account_id"] == account_id
        assert captured["conversation_id"] == str(conversation_id)
        assert captured["title"] == "好案例"
        assert captured["summary"] == "摘要"
        assert captured["query"] == "问题"
        assert captured["answer"] == "回答"
        assert captured["tags"] == ["ai", "demo"]
        assert captured["rating"] == 5
        assert resp.json["data"]["status"] == "pending"

    def test_create_case_should_reject_invalid_payload(self, client, monkeypatch):
        _mock_current_user(monkeypatch, uuid4())

        resp = client.post("/showcase/cases", json={})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.VALIDATE_ERROR

    def test_list_cases_should_return_only_approved(self, client, monkeypatch):
        _mock_current_user(monkeypatch, uuid4())
        captured = {}

        def _list(self, **kwargs):
            captured.update(kwargs)
            return {
                "list": [
                    {"id": "1", "status": "approved", "title": "A"},
                    {"id": "2", "status": "approved", "title": "B"},
                ],
                "paginator": {"total_record": 2, "total_page": 1, "current_page": 1, "page_size": 20},
            }

        monkeypatch.setattr("internal.service.showcase_service.ShowcaseService.list_public_cases", _list, raising=False)

        resp = client.get("/showcase/cases")

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured["page"] == 1
        assert captured["per_page"] == 20
        assert captured["tag"] == ""
        assert captured["keyword"] == ""
        assert all(c["status"] == "approved" for c in resp.json["data"]["list"])
        assert len(resp.json["data"]["list"]) == 2

    def test_list_cases_should_pass_query_params(self, client, monkeypatch):
        _mock_current_user(monkeypatch, uuid4())
        captured = {}

        def _list(self, **kwargs):
            captured.update(kwargs)
            return {
                "list": [{"id": "1", "status": "approved"}],
                "paginator": {"total_record": 1, "total_page": 1, "current_page": 2, "page_size": 10},
            }

        monkeypatch.setattr("internal.service.showcase_service.ShowcaseService.list_public_cases", _list, raising=False)

        resp = client.get("/showcase/cases?current_page=2&page_size=10&tag=ai&keyword=好")

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured["page"] == 2
        assert captured["per_page"] == 10
        assert captured["tag"] == "ai"
        assert captured["keyword"] == "好"

    def test_get_case_should_delegate_to_service(self, client, monkeypatch):
        _mock_current_user(monkeypatch, uuid4())
        case_id = uuid4()
        captured = {}

        def _get(self, case_id_arg):
            captured["case_id"] = case_id_arg
            return {
                "id": str(case_id_arg),
                "status": "approved",
                "title": "X",
                "tags": [],
                "rating": 5,
                "reject_reason": "",
                "created_at": 0,
                "approved_at": 0,
                "approved_by": "admin-1",
                "updated_at": 0,
            }

        monkeypatch.setattr("internal.service.showcase_service.ShowcaseService.get_case", _get, raising=False)

        resp = client.get(f"/showcase/cases/{case_id}")

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured["case_id"] == case_id
        assert resp.json["data"]["id"] == str(case_id)
        assert resp.json["data"]["status"] == "approved"

    def test_admin_list_cases_should_delegate_to_service(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["showcase:read"])
        captured = {}

        def _list(self, **kwargs):
            captured.update(kwargs)
            return {
                "list": [
                    {"id": "1", "status": "pending"},
                    {"id": "2", "status": "approved"},
                    {"id": "3", "status": "rejected"},
                ],
                "paginator": {"total_record": 3, "total_page": 1, "current_page": 1, "page_size": 20},
            }

        monkeypatch.setattr("internal.service.showcase_service.ShowcaseService.admin_list_cases", _list, raising=False)

        resp = client.get(
            "/admin/showcase/cases?current_page=1&page_size=20&status=all",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured["page"] == 1
        assert captured["per_page"] == 20
        assert captured["status"] == "all"
        assert len(resp.json["data"]["list"]) == 3

    def test_approve_case_should_delegate_to_service(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["showcase:approve"])
        case_id = uuid4()
        captured = {}

        def _approve(self, case_id_arg, *, admin_id):
            captured.update({"case_id": case_id_arg, "admin_id": admin_id})
            return {"id": str(case_id_arg), "status": "approved", "approved_by": admin_id}

        monkeypatch.setattr("internal.service.showcase_service.ShowcaseService.approve_case", _approve, raising=False)

        resp = client.post(
            f"/admin/showcase/cases/{case_id}/approve",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured["case_id"] == case_id
        assert captured["admin_id"] == "admin-1"
        assert resp.json["data"]["status"] == "approved"

    def test_reject_case_should_delegate_to_service_with_reason(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["showcase:approve"])
        case_id = uuid4()
        captured = {}

        def _reject(self, case_id_arg, *, admin_id, reason):
            captured.update({"case_id": case_id_arg, "admin_id": admin_id, "reason": reason})
            return {"id": str(case_id_arg), "status": "rejected", "reject_reason": reason}

        monkeypatch.setattr("internal.service.showcase_service.ShowcaseService.reject_case", _reject, raising=False)

        resp = client.post(
            f"/admin/showcase/cases/{case_id}/reject",
            json={"reason": "内容不合适"},
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured["case_id"] == case_id
        assert captured["admin_id"] == "admin-1"
        assert captured["reason"] == "内容不合适"
        assert resp.json["data"]["status"] == "rejected"

    def test_offline_case_should_delegate_to_service(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["showcase:approve"])
        case_id = uuid4()
        captured = {}

        def _offline(self, case_id_arg, *, admin_id):
            captured.update({"case_id": case_id_arg, "admin_id": admin_id})
            return {"id": str(case_id_arg), "status": "offline"}

        monkeypatch.setattr("internal.service.showcase_service.ShowcaseService.offline_case", _offline, raising=False)

        resp = client.post(
            f"/admin/showcase/cases/{case_id}/offline",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert captured["case_id"] == case_id
        assert captured["admin_id"] == "admin-1"
        assert resp.json["data"]["status"] == "offline"

    def test_approve_case_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["showcase:read"])
        case_id = uuid4()

        resp = client.post(
            f"/admin/showcase/cases/{case_id}/approve",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN

    def test_admin_list_cases_should_reject_without_admin_token(self, client, monkeypatch):
        resp = client.get("/admin/showcase/cases")

        assert resp.json["code"] == HttpCode.UNAUTHORIZED
