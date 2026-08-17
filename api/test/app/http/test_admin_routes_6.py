"""admin_routes_6（admin_auth / admin_user / admin_routing_quality / admin_tool_governance）Quart 端点测试。

测试模式参考 test/app/http/test_asgi_app.py：
- asyncio.run + asgi_app.quart_app.test_client()
- monkeypatch asgi_app._get_service 返回 fake service（SimpleNamespace 风格返回）
"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.admin_routes_6 import register_routes
from internal.service.admin_tool_governance_service import AdminToolGovernanceService
from internal.service.admin_user_service import AdminUserService
from internal.service.routing_optimization_suggestion_service import (
    RoutingOptimizationSuggestionService,
)
from internal.service.routing_policy_change_service import RoutingPolicyChangeService
from internal.service.routing_quality_feedback_service import RoutingQualityFeedbackService
from internal.service.routing_quality_metrics_service import RoutingQualityMetricsService

register_routes(asgi_app.quart_app)


class _FakeAdminUserService:
    def __init__(self):
        self.calls = []
        self.admin = {
            "id": str(uuid4()),
            "username": "admin",
            "email": "admin@example.com",
            "name": "管理员",
            "avatar": "",
            "status": "active",
            "roles": ["super_admin"],
            "permissions": [
                "admin_user:read",
                "admin_user:create",
                "admin_user:update",
                "admin_user:disable",
            ],
            "account_id": None,
            "created_at": 1710000000,
            "last_login_at": 1710000000,
            "last_login_ip": "1.2.3.4",
            "is_online": False,
        }
        self.page_result = {
            "list": [],
            "paginator": {
                "total_record": 0,
                "total_page": 0,
                "current_page": 1,
                "page_size": 20,
            },
        }

    def password_login(self, identifier, password, client_ip="", user_agent=""):
        self.calls.append(("password_login", identifier, password, client_ip, user_agent))
        return {
            "access_token": "jwt-token",
            "admin_access_token": "jwt-token",
            "expire_at": 1893456000,
            "admin_user": dict(self.admin),
        }

    def get_current_admin_from_token(self, token):
        self.calls.append(("me", token))
        return dict(self.admin)

    def logout(self, token):
        self.calls.append(("logout", token))

    def change_own_password(self, admin_user_id, *, current_password, new_password):
        self.calls.append(("change_password", admin_user_id, current_password, new_password))
        return dict(self.admin)

    def list_admin_users(self, *, search, status, current_page, page_size):
        self.calls.append(("list", search, status, current_page, page_size))
        return self.page_result

    def create_admin_user(self, *, email, name, password, role_codes, operator_id, ip, user_agent):
        self.calls.append(("create", name, email, password, role_codes, operator_id))
        return dict(self.admin)

    def get_admin_user(self, admin_id):
        self.calls.append(("get", admin_id))
        return dict(self.admin)

    def update_admin_user(self, admin_id, *, name, email, status, role_codes, operator_id, ip, user_agent):
        self.calls.append(("update", admin_id, name, email, status, role_codes))
        return dict(self.admin)

    def disable_admin_user(self, admin_id, *, operator_id, ip, user_agent):
        self.calls.append(("disable", admin_id))

    def enable_admin_user(self, admin_id, *, operator_id, ip, user_agent):
        self.calls.append(("enable", admin_id))
        return dict(self.admin)

    def reset_admin_user_password(self, admin_id, *, password, operator_id, ip, user_agent):
        self.calls.append(("reset_password", admin_id, password))
        return dict(self.admin)

    def revoke_admin_sessions(self, admin_user_id, *, operator_id, ip, user_agent):
        self.calls.append(("revoke_sessions", admin_user_id))
        return {"revoked_sessions": 2}


class TestAdminAuthRoutes:
    def _setup(self, monkeypatch):
        admin_service = _FakeAdminUserService()
        monkeypatch.setattr(
            support,
            "_get_service",
            lambda cls: admin_service if cls is AdminUserService else None,
        )
        return admin_service

    def test_login(self, monkeypatch):
        admin_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/auth/login",
                    json={"identifier": "admin", "password": "pass1234"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["access_token"] == "jwt-token"
        assert payload["data"]["admin_user"]["username"] == "admin"
        login_call = admin_service.calls[0]
        assert login_call[0] == "password_login"
        assert login_call[1] == "admin"
        assert login_call[2] == "pass1234"

    def test_login_missing_identifier(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/auth/login", json={"password": "pass1234"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert payload["message"] == "账号不能为空"

    def test_me(self, monkeypatch):
        admin_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    "/admin/auth/me",
                    headers={"Authorization": "Bearer token-abc"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["username"] == "admin"
        assert admin_service.calls[0] == ("me", "token-abc")

    def test_me_requires_token(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/auth/me")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 401
        assert payload["code"] == "unauthorized"

    def test_logout(self, monkeypatch):
        admin_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/auth/logout",
                    headers={"Authorization": "Bearer token-abc"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["message"] == "退出登录成功"
        assert admin_service.calls[0] == ("logout", "token-abc")

    def test_change_password(self, monkeypatch):
        admin_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/auth/password",
                    headers={"Authorization": "Bearer token-abc"},
                    json={"current_password": "old-pass", "new_password": "new-pass1"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["name"] == "管理员"
        assert admin_service.calls[0] == ("me", "token-abc")
        call = admin_service.calls[1]
        assert call[0] == "change_password"
        assert call[2] == "old-pass"
        assert call[3] == "new-pass1"

    def test_change_password_requires_fields(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/auth/password",
                    headers={"Authorization": "Bearer token-abc"},
                    json={"current_password": "old-pass"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert payload["message"] == "新密码不能为空"


class TestAdminUserRoutes:
    def _setup(self, monkeypatch):
        admin_service = _FakeAdminUserService()
        monkeypatch.setattr(
            support,
            "_get_service",
            lambda cls: admin_service if cls is AdminUserService else None,
        )
        return admin_service

    def test_list(self, monkeypatch):
        admin_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    "/admin/admin-users?search=abc&status=active&current_page=2&page_size=10"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["list"] == []
        assert admin_service.calls[0] == ("list", "abc", "active", 2, 10)

    def test_create(self, monkeypatch):
        admin_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/admin-users",
                    json={
                        "name": "新管理员",
                        "email": "new@example.com",
                        "password": "pass1234",
                        "role_codes": ["role-1"],
                    },
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["name"] == "管理员"
        call = admin_service.calls[0]
        assert call[0] == "create"
        assert call[1] == "新管理员"
        assert call[2] == "new@example.com"
        assert call[4] == ["role-1"]

    def test_create_missing_name(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/admin-users", json={"password": "pass1234"}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert payload["message"] == "名称不能为空"

    def test_get(self, monkeypatch):
        admin_service = self._setup(monkeypatch)
        admin_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/admin-users/{admin_id}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["username"] == "admin"
        assert admin_service.calls[0] == ("get", admin_id)

    def test_update(self, monkeypatch):
        admin_service = self._setup(monkeypatch)
        admin_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    f"/admin/admin-users/{admin_id}",
                    json={"name": "改名", "role_codes": ["role-2"]},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        call = admin_service.calls[0]
        assert call[0] == "update"
        assert call[1] == admin_id
        assert call[2] == "改名"
        assert call[5] == ["role-2"]

    def test_disable(self, monkeypatch):
        admin_service = self._setup(monkeypatch)
        admin_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/admin-users/{admin_id}/disable")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["message"] == "禁用管理员成功"
        assert admin_service.calls[0] == ("disable", admin_id)

    def test_enable(self, monkeypatch):
        admin_service = self._setup(monkeypatch)
        admin_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/admin-users/{admin_id}/enable")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["name"] == "管理员"
        assert admin_service.calls[0] == ("enable", admin_id)

    def test_reset_password(self, monkeypatch):
        admin_service = self._setup(monkeypatch)
        admin_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/admin-users/{admin_id}/reset-password",
                    json={"password": "newpass1"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert admin_service.calls[0] == ("reset_password", admin_id, "newpass1")

    def test_revoke_sessions(self, monkeypatch):
        admin_service = self._setup(monkeypatch)
        admin_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/admin-users/{admin_id}/sessions/revoke")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["revoked_sessions"] == 2
        assert admin_service.calls[0] == ("revoke_sessions", admin_id)


class _FakeRoutingQualityFeedbackService:
    def __init__(self):
        self.calls = []
        self.feedback = {
            "id": str(uuid4()),
            "routing_log_id": str(uuid4()),
            "source": "admin",
            "rating": 5,
            "dimension_scores": {},
            "comment": "不错",
            "metadata": {},
            "created_by": None,
            "created_at": None,
        }

    def create_feedback(self, *, routing_log_id, source, rating, dimension_scores, comment, metadata, created_by):
        self.calls.append(("create_feedback", routing_log_id, source, rating, created_by))
        return dict(self.feedback)

    def list_feedback(self, *, routing_log_id=None, source=None, page=1, page_size=20):
        self.calls.append(("list_feedback", routing_log_id, source, page, page_size))
        return [dict(self.feedback)]


class _FakeRoutingQualityMetricsService:
    def __init__(self):
        self.calls = []

    def build_metrics(self):
        self.calls.append(("build_metrics",))
        return {
            "total_count": 10,
            "feedback_count": 2,
            "avg_rating": 4.5,
            "fallback_rate": 0.1,
            "avg_latency_ms": 1200.5,
            "avg_cost_credits": 0.5,
            "quality_by_task_type": {},
            "quality_by_agent_pool": {},
            "quality_by_tool_pool": {},
            "quality_by_model": {},
        }


class _FakeRoutingOptimizationSuggestionService:
    def __init__(self):
        self.calls = []
        self.suggestion = {
            "id": str(uuid4()),
            "target_type": "routing_quality",
            "target_id": "feedback",
            "suggestion_type": "collect_more_feedback",
            "severity": "medium",
            "reason": "样本不足",
            "evidence": {},
            "status": "open",
            "dismiss_reason": None,
            "applied_by": None,
            "applied_at": None,
            "policy_change_draft_id": None,
        }

    def list_suggestions(self, status=""):
        self.calls.append(("list_suggestions", status))
        return [dict(self.suggestion)]

    def generate_suggestions(self, metrics):
        self.calls.append(("generate_suggestions", metrics))
        return [dict(self.suggestion)]

    def accept_suggestion(self, suggestion_id, admin_user_id):
        self.calls.append(("accept_suggestion", suggestion_id, admin_user_id))
        return {"suggestion_id": str(suggestion_id), "status": "accepted"}

    def dismiss_suggestion(self, suggestion_id, admin_user_id, reason):
        self.calls.append(("dismiss_suggestion", suggestion_id, admin_user_id, reason))
        return {"suggestion_id": str(suggestion_id), "status": "dismissed"}


class _FakeRoutingPolicyChangeService:
    def __init__(self):
        self.calls = []
        self.preview = {
            "suggestion_id": str(uuid4()),
            "policy_type": "model_routing",
            "target_id": "model-x",
            "before_config": {},
            "after_config": {},
            "diff": {},
            "impact": {},
            "status": "preview",
        }
        self.draft = {
            "id": str(uuid4()),
            "suggestion_id": str(uuid4()),
            "policy_type": "model_routing",
            "target_id": "model-x",
            "before_config": {},
            "after_config": {},
            "diff": {},
            "impact": {},
            "status": "applied",
            "applied_by": None,
            "applied_at": None,
            "rolled_back_at": None,
            "rollback_reason": None,
        }

    def generate_preview(self, suggestion_id):
        self.calls.append(("generate_preview", suggestion_id))
        return dict(self.preview)

    def apply_draft(self, suggestion_id, admin_user_id, preview_data):
        self.calls.append(("apply_draft", suggestion_id, admin_user_id, preview_data))
        return dict(self.draft)

    def rollback_draft(self, draft_id, admin_user_id, reason):
        self.calls.append(("rollback_draft", draft_id, admin_user_id, reason))
        return dict(self.draft)

    def list_drafts(self, status=""):
        self.calls.append(("list_drafts", status))
        return [dict(self.draft)]


class TestAdminRoutingQualityRoutes:
    def _setup(self, monkeypatch):
        feedback_service = _FakeRoutingQualityFeedbackService()
        metrics_service = _FakeRoutingQualityMetricsService()
        suggestion_service = _FakeRoutingOptimizationSuggestionService()
        policy_change_service = _FakeRoutingPolicyChangeService()
        services = {
            RoutingQualityFeedbackService: feedback_service,
            RoutingQualityMetricsService: metrics_service,
            RoutingOptimizationSuggestionService: suggestion_service,
            RoutingPolicyChangeService: policy_change_service,
        }
        monkeypatch.setattr(support, "_get_service", lambda cls: services.get(cls))
        return services

    def test_create_feedback(self, monkeypatch):
        services = self._setup(monkeypatch)
        routing_log_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/routing-quality/feedback",
                    json={"routing_log_id": str(routing_log_id), "rating": 5, "comment": "很好"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["rating"] == 5
        fb = services[RoutingQualityFeedbackService]
        call = fb.calls[0]
        assert call[0] == "create_feedback"
        assert call[1] == routing_log_id
        assert call[2] == "admin"

    def test_create_feedback_missing_fields(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/routing-quality/feedback", json={"rating": 5}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_list_feedback(self, monkeypatch):
        services = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    "/admin/routing-quality/feedback?source=admin&page=1&page_size=10"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert len(payload["data"]) == 1
        fb = services[RoutingQualityFeedbackService]
        assert fb.calls[0][0] == "list_feedback"
        assert fb.calls[0][3] == 1
        assert fb.calls[0][4] == 10

    def test_metrics(self, monkeypatch):
        services = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/routing-quality/metrics")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["total_count"] == 10
        assert services[RoutingQualityMetricsService].calls[0][0] == "build_metrics"

    def test_suggestions(self, monkeypatch):
        services = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/routing-quality/suggestions")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert len(payload["data"]) == 1
        assert services[RoutingOptimizationSuggestionService].calls[0][0] == "generate_suggestions"

    def test_suggestions_with_status(self, monkeypatch):
        services = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/routing-quality/suggestions?status=open")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        sugg = services[RoutingOptimizationSuggestionService]
        assert sugg.calls[0] == ("list_suggestions", "open")

    def test_accept_suggestion(self, monkeypatch):
        services = self._setup(monkeypatch)
        suggestion_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/routing-quality/suggestions/{suggestion_id}/accept"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["status"] == "accepted"
        sugg = services[RoutingOptimizationSuggestionService]
        call = sugg.calls[0]
        assert call[0] == "accept_suggestion"
        assert call[1] == suggestion_id

    def test_dismiss_suggestion(self, monkeypatch):
        services = self._setup(monkeypatch)
        suggestion_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/routing-quality/suggestions/{suggestion_id}/dismiss",
                    json={"reason": "不适用"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["status"] == "dismissed"
        sugg = services[RoutingOptimizationSuggestionService]
        call = sugg.calls[0]
        assert call[0] == "dismiss_suggestion"
        assert call[1] == suggestion_id
        assert call[3] == "不适用"

    def test_preview_policy_change(self, monkeypatch):
        services = self._setup(monkeypatch)
        suggestion_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/routing-quality/suggestions/{suggestion_id}/preview"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["policy_type"] == "model_routing"
        assert services[RoutingPolicyChangeService].calls[0][0] == "generate_preview"

    def test_apply_policy_change(self, monkeypatch):
        services = self._setup(monkeypatch)
        suggestion_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/routing-quality/suggestions/{suggestion_id}/apply",
                    json={"policy_type": "model_routing"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["status"] == "applied"
        pcs = services[RoutingPolicyChangeService]
        call = pcs.calls[0]
        assert call[0] == "apply_draft"
        assert call[1] == suggestion_id
        assert call[3]["policy_type"] == "model_routing"

    def test_list_policy_changes(self, monkeypatch):
        services = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/routing-quality/policy-changes?status=applied")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["total"] == 1
        assert services[RoutingPolicyChangeService].calls[0] == ("list_drafts", "applied")

    def test_rollback_policy_change(self, monkeypatch):
        services = self._setup(monkeypatch)
        draft_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/routing-quality/policy-changes/{draft_id}/rollback",
                    json={"reason": "回滚"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["status"] == "applied"
        pcs = services[RoutingPolicyChangeService]
        call = pcs.calls[0]
        assert call[0] == "rollback_draft"
        assert call[1] == draft_id
        assert call[3] == "回滚"


class _FakeAdminToolGovernanceService:
    def __init__(self):
        self.calls = []
        self.policy = {
            "id": str(uuid4()),
            "tool_id": "web_search",
            "tool_name": "搜索",
            "source_type": "builtin",
            "provider_id": None,
            "risk_level": "low",
            "visibility": "private",
            "allowed_pools": [],
            "enabled": True,
            "max_invocations_per_request": 5,
            "cooldown_seconds": 0,
            "require_confirmation": False,
            "description": "",
            "created_at": 1710000000,
            "updated_at": 1710000000,
        }
        self.page_result = {
            "list": [],
            "paginator": {
                "total_record": 0,
                "total_page": 0,
                "current_page": 1,
                "page_size": 20,
            },
        }

    def list_policies(self, *, current_page, page_size, source_type, risk_level, visibility, enabled, keyword):
        self.calls.append(
            ("list_policies", current_page, page_size, source_type, risk_level, visibility, enabled, keyword)
        )
        return self.page_result

    def create_policy(self, payload):
        self.calls.append(("create_policy", payload))
        return dict(self.policy)

    def get_policy(self, policy_id):
        self.calls.append(("get_policy", policy_id))
        return dict(self.policy)

    def update_policy(self, policy_id, payload):
        self.calls.append(("update_policy", policy_id, payload))
        return dict(self.policy)

    def delete_policy(self, policy_id):
        self.calls.append(("delete_policy", policy_id))

    def set_enabled(self, policy_id, enabled):
        self.calls.append(("set_enabled", policy_id, enabled))
        return dict(self.policy)

    def batch_update_risk(self, policy_ids, risk_level):
        self.calls.append(("batch_update_risk", policy_ids, risk_level))
        return {"updated": len(policy_ids), "risk_level": risk_level}

    def list_audit_logs(self, *, current_page, page_size, tool_id, status, start_date, end_date):
        self.calls.append(("list_audit_logs", current_page, page_size, tool_id, status, start_date, end_date))
        return self.page_result

    def get_governance_stats(self):
        self.calls.append(("get_governance_stats",))
        return {
            "total": 10,
            "enabled": 8,
            "disabled": 2,
            "enabled_rate": 0.8,
            "risk_distribution": {"low": 5, "medium": 3, "high": 2, "critical": 0},
            "source_distribution": {
                "api_tool": 1,
                "mcp": 2,
                "skill": 3,
                "builtin": 4,
                "knowledge": 0,
                "workflow": 0,
                "agent_binding": 0,
            },
            "visibility_distribution": {"private": 8, "tenant": 2, "public": 0},
        }


class TestAdminToolGovernanceRoutes:
    def _setup(self, monkeypatch):
        governance_service = _FakeAdminToolGovernanceService()
        monkeypatch.setattr(
            support,
            "_get_service",
            lambda cls: governance_service if cls is AdminToolGovernanceService else None,
        )
        return governance_service

    def test_list_policies(self, monkeypatch):
        governance_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    "/admin/tool-governance?source_type=builtin&enabled=true&current_page=1&page_size=10"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["list"] == []
        call = governance_service.calls[0]
        assert call[0] == "list_policies"
        assert call[1] == 1
        assert call[2] == 10
        assert call[3] == "builtin"
        assert call[6] == "true"

    def test_create_policy(self, monkeypatch):
        governance_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/tool-governance",
                    json={"tool_id": "web_search", "risk_level": "high"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["tool_id"] == "web_search"
        call = governance_service.calls[0]
        assert call[0] == "create_policy"
        assert call[1]["tool_id"] == "web_search"

    def test_get_policy(self, monkeypatch):
        governance_service = self._setup(monkeypatch)
        policy_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/tool-governance/{policy_id}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["tool_name"] == "搜索"
        assert governance_service.calls[0] == ("get_policy", policy_id)

    def test_update_policy(self, monkeypatch):
        governance_service = self._setup(monkeypatch)
        policy_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    f"/admin/tool-governance/{policy_id}",
                    json={"risk_level": "critical"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        call = governance_service.calls[0]
        assert call[0] == "update_policy"
        assert call[1] == policy_id
        assert call[2]["risk_level"] == "critical"

    def test_delete_policy(self, monkeypatch):
        governance_service = self._setup(monkeypatch)
        policy_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(f"/admin/tool-governance/{policy_id}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["message"] == "删除工具治理策略成功"
        assert governance_service.calls[0] == ("delete_policy", policy_id)

    def test_set_status(self, monkeypatch):
        governance_service = self._setup(monkeypatch)
        policy_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/tool-governance/{policy_id}/status",
                    json={"enabled": False},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["enabled"] is True
        assert governance_service.calls[0] == ("set_enabled", policy_id, False)

    def test_set_status_invalid(self, monkeypatch):
        self._setup(monkeypatch)
        policy_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/tool-governance/{policy_id}/status",
                    json={"enabled": "yes"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
        assert payload["message"] == "enabled 必须为布尔值"

    def test_batch_update_risk(self, monkeypatch):
        governance_service = self._setup(monkeypatch)
        policy_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/tool-governance/batch-risk",
                    json={"policy_ids": [str(policy_id)], "risk_level": "high"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["updated"] == 1
        call = governance_service.calls[0]
        assert call[0] == "batch_update_risk"
        assert call[1] == [str(policy_id)]
        assert call[2] == "high"

    def test_batch_update_risk_missing_level(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/tool-governance/batch-risk",
                    json={"policy_ids": [str(uuid4())]},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_list_audit_logs(self, monkeypatch):
        governance_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    "/admin/tool-governance/audit?tool_id=web_search&status=success"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["list"] == []
        call = governance_service.calls[0]
        assert call[0] == "list_audit_logs"
        assert call[3] == "web_search"
        assert call[4] == "success"

    def test_stats(self, monkeypatch):
        governance_service = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/admin/tool-governance/stats")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["data"]["total"] == 10
        assert payload["data"]["risk_distribution"]["low"] == 5
        assert governance_service.calls[0][0] == "get_governance_stats"
