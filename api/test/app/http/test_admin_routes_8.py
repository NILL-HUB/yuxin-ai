"""Admin 管理端点 Quart 异步端点（app.http.admin_routes_8）单元测试。

批次 8 覆盖：prompt_template / builtin_tool / public_ai_feature /
app_assignment / routing_log / resource_entry / recycle_bin /
cost_stats / orchestration_flag / audit_log / orchestration_release /
upload_file。
"""
import asyncio
import io
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from werkzeug.datastructures import FileStorage

import app.http.asgi_app as asgi_app
from app.http import support
import app.http.admin_routes_8 as admin_routes_8
from app.http.admin_routes_8 import register_routes

register_routes(asgi_app.quart_app)


@dataclass
class _Paginator:
    total_page: int = 1
    total_record: int = 1
    current_page: int = 1
    page_size: int = 20


def _setup(monkeypatch, services):
    account = SimpleNamespace(id=uuid4())
    admin_id = uuid4()

    async def _resolve_admin_permission(permission_code):
        return {
            "id": str(admin_id),
            "permissions": [
                "orchestration_flag:read",
                "orchestration_flag:update",
            ],
        }, None

    monkeypatch.setattr(support, "_load_account", lambda _aid: account)
    monkeypatch.setattr(support, "_get_service", lambda cls: services.get(cls))
    monkeypatch.setattr(
        support,
        "_resolve_admin_permission",
        _resolve_admin_permission,
    )
    return account


def _prompt_detail(prompt_key):
    return {
        "prompt_key": prompt_key,
        "name": "Prompt 模板",
        "category": "general",
        "description": "desc",
        "content": "hello {name}",
        "variables": {"name": {"description": "name"}},
        "source": "system",
        "source_path": "prompts/general.yaml",
        "content_hash": "hash",
        "enabled": True,
        "version": 1,
        "updated_at": 1710000000,
        "created_at": 1710000000,
    }


def _builtin_tool_dict(tool_id):
    return {
        "id": str(tool_id),
        "provider_id": str(uuid4()),
        "name": "web_search",
        "label": "Web Search",
        "description": "desc",
        "params": [],
        "task_keywords": ["search"],
        "python_module": "web_search",
        "source": "builtin",
        "enabled": True,
        "updated_at": 1710000000,
        "created_at": 1710000000,
        "provider": {
            "id": str(uuid4()),
            "name": "web",
            "label": "Web",
            "description": "",
            "icon": "",
            "background": "",
            "category": "general",
        },
    }


def _feature_record(feature_key):
    return SimpleNamespace(
        feature_key=feature_key,
        feature_name="路由",
        feature_category="routing",
        feature_description="desc",
        model_config_id=str(uuid4()),
        enabled=True,
        fallback_tier="1",
        model_type="llm",
        billable=True,
        deprecated=False,
        last_called_at=None,
        extra_config={},
        updated_at=datetime(2026, 8, 8, 8, 0, 0),
        created_at=datetime(2026, 8, 8, 8, 0, 0),
    )


def _app_assignment_dict():
    return {
        "id": str(uuid4()),
        "app_id": str(uuid4()),
        "account_id": str(uuid4()),
        "assigned_by": str(uuid4()),
        "status": "active",
        "assigned_at": 1710000000,
        "revoked_at": None,
        "app": None,
    }


def _routing_log_dict():
    return {
        "id": str(uuid4()),
        "account_id": str(uuid4()),
        "message_id": str(uuid4()),
        "routing_decision": {},
        "agent_candidates": [],
        "filtered_out_agents": [],
        "tool_candidates": [],
        "filtered_out_tools": [],
        "knowledge_hits": [],
        "billing_events": [],
        "invoke_from": "app",
        "user_query": "hello",
        "task_classification": {},
        "model_selection": {},
        "agent_pool_hits": [],
        "tool_pool_hits": [],
        "key_usage": {},
        "cost_summary": {},
        "latency_ms": 100,
        "fallback_reason": "",
        "redaction_enabled": False,
        "retention_expires_at": None,
        "status": "success",
        "created_at": 1710000000,
    }


def _mcp_provider_dict():
    return {
        "id": str(uuid4()),
        "provider_key": "fake",
        "name": "fake",
        "label": "Fake",
        "icon": "",
        "background": "",
        "description": "",
        "category": "general",
        "transport": "http",
        "url": "http://localhost",
        "command": "",
        "timeout_seconds": 30,
        "source_type": "custom",
    }


def _skill_package_dict():
    return {
        "id": str(uuid4()),
        "source_key": "skill-key",
        "source_path": "skills/xxx",
        "name": "skill",
        "label": "Skill",
        "description": "",
        "category": "general",
        "tags": [],
        "executor_type": "scf",
    }


def _recycle_item(item_id):
    return SimpleNamespace(
        id=item_id,
        resource_type="knowledge_base",
        resource_id=str(uuid4()),
        resource_key="kb-key",
        resource_name="知识库",
        deleted_by=str(uuid4()),
        deleted_by_name="管理员",
        deleted_by_type="admin",
        deleted_at=datetime(2026, 8, 8, 8, 0, 0),
        retention_days=7,
        expire_at=datetime(2026, 8, 15, 8, 0, 0),
        status="pending",
        remark="",
        snapshot={},
    )


class _FakePromptSyncService:
    def __init__(self):
        self.calls = []

    def list_prompts(self, category=None):
        self.calls.append(("list", category))
        return [_prompt_detail("pt_optimizer")]

    def get_prompt_detail(self, prompt_key):
        self.calls.append(("get", prompt_key))
        if prompt_key == "pt_missing":
            return None
        return _prompt_detail(prompt_key)

    def update_prompt(self, prompt_key, *, content=None, description=None, enabled=None):
        self.calls.append(("update", prompt_key, content, description, enabled))
        return _prompt_detail(prompt_key)

    def reset_prompt(self, prompt_key):
        self.calls.append(("reset", prompt_key))
        return _prompt_detail(prompt_key)


class _FakeSystemPromptLibraryService:
    def __init__(self):
        self.calls = []

    def load_yaml_prompts(self):
        self.calls.append(("yaml",))
        return {"pt_optimizer": "system", "pt_review": "system"}

    def list_managed_prompts(self, category=None):
        self.calls.append(("managed_list", category))
        return [_prompt_detail("pt_optimizer")]

    def get_managed_prompt_detail(self, prompt_key):
        self.calls.append(("managed_get", prompt_key))
        return _prompt_detail(prompt_key)

    def update_managed_prompt(self, prompt_key, *, content=None, description=None, enabled=None):
        self.calls.append(("managed_update", prompt_key, content, description, enabled))
        return _prompt_detail(prompt_key)

    def reset_managed_prompt(self, prompt_key):
        self.calls.append(("managed_reset", prompt_key))
        return _prompt_detail(prompt_key)

    def delete_managed_prompt(self, prompt_key, *, deleted_by=None, retention_days=None):
        self.calls.append(("managed_delete", prompt_key, deleted_by, retention_days))
        return True


class _FakeBuiltinToolService:
    def __init__(self):
        self.calls = []

    def get_builtin_tools(self):
        self.calls.append(("tools",))
        return [_builtin_tool_dict(uuid4())]

    def get_categories(self):
        self.calls.append(("categories",))
        return [{"name": "general", "label": "通用"}]


class _FakePublicAIFeatureService:
    def __init__(self):
        self.calls = []

    def list_all_features(self):
        self.calls.append(("list",))
        return [_feature_record("feature_routing"), _feature_record("feature_memory")]

    def get_feature_config(self, feature_key):
        self.calls.append(("get", feature_key))
        if feature_key == "feature_missing":
            return None
        return _feature_record(feature_key)


class _FakeAdminAppAssignmentService:
    def __init__(self):
        self.calls = []

    def list_assignments(self, account_id):
        self.calls.append(("list", account_id))
        return {"list": [_app_assignment_dict()]}

    def assign_apps(self, account_id, app_ids, *, operator_id=None, ip="", user_agent=""):
        self.calls.append(("assign", account_id, app_ids, operator_id, ip, user_agent))
        return {"assigned": 1, "reactivated": 0, "skipped": 0, "list": []}

    def revoke_assignment(self, account_id, assignment_id, *, operator_id=None, ip="", user_agent=""):
        self.calls.append(("revoke", account_id, assignment_id, operator_id, ip, user_agent))
        return _app_assignment_dict()


class _FakeRoutingLogService:
    def __init__(self):
        self.calls = []

    def page(self, **kwargs):
        self.calls.append(("page", kwargs))
        return {
            "list": [_routing_log_dict()],
            "paginator": {
                "total_record": 1,
                "total_page": 1,
                "current_page": kwargs.get("page", 1),
                "page_size": kwargs.get("page_size", 20),
            },
            "summary": {"total_cost": "0.1", "success_rate": "1.0"},
        }


class _FakeRoutingLogRetentionService:
    def __init__(self):
        self.calls = []

    def describe(self):
        self.calls.append(("describe",))
        return {
            "retention_days": 7,
            "default_retention_days": 7,
            "min_retention_days": 1,
            "max_retention_days": 3650,
            "code": "routing_log_retention",
        }

    def set_retention_days(self, retention_days, admin_user_id):
        self.calls.append(("set", retention_days, admin_user_id))
        return retention_days


class _FakeAdminToolGovernanceService:
    def __init__(self):
        self.calls = []

    def list_policies(self, *, source_type, current_page=1, page_size=20, keyword=""):
        self.calls.append(("policies", source_type, current_page, page_size, keyword))
        return {
            "list": [{"id": str(uuid4()), "name": "web_search"}],
            "paginator": {
                "total_record": 1,
                "total_page": 1,
                "current_page": current_page,
                "page_size": page_size,
            },
        }


class _FakeMcpService:
    def __init__(self):
        self.calls = []

    def get_admin_mcp_providers_with_page(self, req):
        self.calls.append(("mcp", req.current_page.data, req.page_size.data, req.search_word.data))
        return [_mcp_provider_dict()], _Paginator()


class _FakeSkillService:
    def __init__(self):
        self.calls = []

    def get_skill_packages_with_page(self, req):
        self.calls.append(("skills", req.current_page.data, req.page_size.data, req.category.data))
        return [_skill_package_dict()], _Paginator()


class _FakeRecycleBinService:
    def __init__(self):
        self.calls = []

    def list_items(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {
            "items": [_recycle_item(1)],
            "total": 1,
            "page": kwargs.get("page", 1),
            "page_size": kwargs.get("page_size", 20),
            "total_pages": 1,
            "total_record": 1,
        }

    def get_item(self, item_id):
        self.calls.append(("get", item_id))
        return _recycle_item(item_id)

    def restore_item(self, item_id, *, admin_user_id=None):
        self.calls.append(("restore", item_id, admin_user_id))
        return _recycle_item(item_id)


class _FakeCostStatsService:
    def __init__(self):
        self.calls = []

    def overview(self, *, start_at=None, end_at=None):
        self.calls.append(("overview", start_at, end_at))
        return {
            "total_credits": 100,
            "total_requests": 10,
            "avg_cost_per_request": 10.0,
            "total_input_tokens": 1000,
            "total_output_tokens": 500,
        }

    def by_dimension(self, *, dimension="user", start_at=None, end_at=None, limit=10):
        self.calls.append(("by_dimension", dimension, start_at, end_at, limit))
        return {
            "dimension": dimension,
            "items": [{"name": "u1", "total_credits": 50, "request_count": 5, "avg_credits": 10.0, "percentage": 50.0}],
            "total_credits": 50,
        }

    def timeseries(self, *, granularity="day", start_at=None, end_at=None):
        self.calls.append(("timeseries", granularity, start_at, end_at))
        return {
            "granularity": granularity,
            "points": [{"timestamp": 1710000000, "total_credits": 10, "request_count": 2}],
        }


class _FakeOrchestrationFeatureFlagService:
    def __init__(self):
        self.calls = []

    def list_flags(self):
        self.calls.append(("list",))
        return [
            {
                "code": "flag_enable_xxx",
                "name": "功能开关",
                "description": "desc",
                "enabled": True,
                "risk_level": "low",
                "fallback_behavior": "off",
                "updated_by": str(uuid4()),
            }
        ]

    def update_flag(self, *, code, enabled=False, operator_id=None):
        self.calls.append(("update", code, enabled, operator_id))
        return {
            "code": code,
            "name": "功能开关",
            "description": "desc",
            "enabled": enabled,
            "risk_level": "low",
            "fallback_behavior": "off",
            "updated_by": str(operator_id),
        }


class _FakeAuditLogService:
    def __init__(self):
        self.calls = []

    def list_audit_logs(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {
            "list": [
                {
                    "id": str(uuid4()),
                    "admin_user_id": str(uuid4()),
                    "admin_user_name": "管理员",
                    "account_id": None,
                    "account_name": None,
                    "action": kwargs.get("action", ""),
                    "resource_type": kwargs.get("resource_type", ""),
                    "resource_id": str(uuid4()),
                    "ip": "127.0.0.1",
                    "user_agent": "pytest",
                    "before_data": {},
                    "after_data": {},
                    "created_at": 1710000000,
                }
            ],
            "paginator": {
                "total_record": 1,
                "total_page": 1,
                "current_page": kwargs.get("current_page", 1),
                "page_size": kwargs.get("page_size", 20),
            },
        }


class _FakeOrchestrationReleaseCheckService:
    def __init__(self):
        self.calls = []

    def build_report(self):
        self.calls.append(("build",))
        return {
            "test_status": {"passed": True},
            "migration_status": {"pending": []},
            "feature_flags": [{"code": "flag_1", "enabled": True}],
            "security_checklist": {"ok": True},
            "cost_metrics": {"total_credits": 100},
            "routing_metrics": {"success_rate": 1.0},
            "rollback_plan": {"steps": []},
            "warnings": [],
        }


class _FakeCosService:
    def __init__(self):
        self.calls = []

    def upload_file(self, file, only_image=True, account=None):
        self.calls.append(("upload", file.filename, only_image))
        return SimpleNamespace(key="path/key.png")

    def get_file_url(self, key, download_name=None):
        self.calls.append(("url", key))
        return "https://cdn.example/key.png"


class TestAdminRoutes8Registered:
    def test_routes_registered(self):
        rules = [r.rule for r in asgi_app.quart_app.url_map.iter_rules()]
        assert "/admin/prompt-templates" in rules
        assert "/admin/builtin-tools" in rules
        assert "/admin/public-ai-features/models" in rules
        assert "/admin/users/<uuid:account_id>/app-assignments" in rules
        assert "/admin/routing-logs/retention" in rules
        assert "/admin/recycle-bin" in rules
        assert "/admin/cost-stats/overview" in rules
        assert "/admin/orchestration-flags" in rules
        assert "/admin/audit-logs" in rules
        assert "/admin/orchestration-release-check" in rules
        assert "/admin/upload-files/image" in rules

    def test_register_routes_idempotent(self):
        admin_routes_8.register_routes(asgi_app.quart_app)
        assert admin_routes_8._registered is True


class TestAdminPromptTemplate:
    def _setup(self, monkeypatch):
        from internal.service.prompt_sync_service import PromptSyncService
        from internal.service.system_prompt_library_service import SystemPromptLibraryService

        sync_svc = _FakePromptSyncService()
        library_svc = _FakeSystemPromptLibraryService()
        _setup(
            monkeypatch,
            {PromptSyncService: sync_svc, SystemPromptLibraryService: library_svc},
        )
        return sync_svc, library_svc

    def test_list(self, monkeypatch):
        sync_svc, library_svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/prompt-templates?account_id={uuid4()}&category=general")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert len(payload["data"]["items"]) == 2
        assert sync_svc.calls[0][0] == "list"
        assert library_svc.calls[0][0] == "managed_list"

    def test_get_system_prompt(self, monkeypatch):
        _, library_svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/prompt-templates/pt_optimizer?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["prompt_key"] == "pt_optimizer"
        assert library_svc.calls[0][0] == "yaml"
        assert library_svc.calls[1][0] == "managed_get"

    def test_get_prompt_not_found(self, monkeypatch):
        sync_svc, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/prompt-templates/pt_missing?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 404
        assert payload["code"] == "not_found"
        assert sync_svc.calls[0] == ("get", "pt_missing")

    def test_update(self, monkeypatch):
        sync_svc, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    f"/admin/prompt-templates/pt_unknown?account_id={uuid4()}",
                    json={"content": "new", "enabled": True},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["prompt_key"] == "pt_unknown"
        assert sync_svc.calls[0] == ("update", "pt_unknown", "new", None, True)

    def test_update_system_prompt(self, monkeypatch):
        _, library_svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    f"/admin/prompt-templates/pt_optimizer?account_id={uuid4()}",
                    json={"content": "new"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert library_svc.calls[1][0] == "managed_update"
        assert library_svc.calls[1][1] == "pt_optimizer"
        assert library_svc.calls[1][2] == "new"

    def test_reset(self, monkeypatch):
        _, library_svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/prompt-templates/pt_optimizer/reset?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["prompt_key"] == "pt_optimizer"
        assert library_svc.calls[1][0] == "managed_reset"

    def test_delete_system_prompt(self, monkeypatch):
        _, library_svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(
                    f"/admin/prompt-templates/pt_optimizer?account_id={uuid4()}",
                    json={"retention_days": 30},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["prompt_key"] == "pt_optimizer"
        assert library_svc.calls[1][0] == "managed_delete"
        assert library_svc.calls[1][3] == 30

    def test_delete_non_system_prompt(self, monkeypatch):
        _, library_svc = self._setup(monkeypatch)
        monkeypatch.setattr(library_svc.__class__, "load_yaml_prompts", lambda self: {})

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.delete(f"/admin/prompt-templates/pt_optimizer?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"


class TestAdminBuiltinTool:
    def _setup(self, monkeypatch):
        from internal.service import BuiltinToolService

        svc = _FakeBuiltinToolService()
        _setup(monkeypatch, {BuiltinToolService: svc})
        return svc

    def test_list(self, monkeypatch):
        svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/builtin-tools?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert len(payload["data"]) == 1
        assert svc.calls[0] == ("tools",)

    def test_categories(self, monkeypatch):
        svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/builtin-tools/categories?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"][0]["name"] == "general"
        assert svc.calls[0] == ("categories",)

    def test_get_tool(self, monkeypatch):
        self._setup(monkeypatch)
        tool_id = uuid4()
        monkeypatch.setattr(admin_routes_8, "_builtin_tool_detail", lambda tid: _builtin_tool_dict(tid))

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/builtin-tools/{tool_id}?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["name"] == "web_search"

    def test_update_tool(self, monkeypatch):
        self._setup(monkeypatch)
        tool_id = uuid4()
        monkeypatch.setattr(admin_routes_8, "_builtin_tool_update", lambda tid, data: _builtin_tool_dict(tid))

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    f"/admin/builtin-tools/{tool_id}?account_id={uuid4()}",
                    json={"label": "New Label"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["id"] == str(tool_id)


class TestAdminPublicAIFeature:
    def _setup(self, monkeypatch):
        from internal.service.public_ai_feature_service import PublicAIFeatureService

        svc = _FakePublicAIFeatureService()
        _setup(monkeypatch, {PublicAIFeatureService: svc})
        return svc

    def test_list(self, monkeypatch):
        svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/public-ai-features?account_id={uuid4()}&enabled=true&category=routing"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["total"] == 2
        assert payload["data"]["items"][0]["feature_key"] == "feature_routing"
        assert svc.calls[0] == ("list",)

    def test_models(self, monkeypatch):
        self._setup(monkeypatch)
        monkeypatch.setattr(
            admin_routes_8,
            "_list_available_models",
            lambda model_type: [{"id": str(uuid4()), "label": "llm / gpt", "model_type": model_type}],
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/public-ai-features/models?account_id={uuid4()}&model_type=llm"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert len(payload["data"]["items"]) == 1

    def test_get_feature(self, monkeypatch):
        svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/public-ai-features/feature_routing?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["feature_key"] == "feature_routing"
        assert svc.calls[0] == ("get", "feature_routing")

    def test_get_feature_not_found(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/public-ai-features/feature_missing?account_id={uuid4()}"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 404
        assert payload["code"] == "not_found"

    def test_update_feature(self, monkeypatch):
        self._setup(monkeypatch)
        monkeypatch.setattr(
            admin_routes_8,
            "_update_public_ai_feature",
            lambda key, payload: _feature_record(key),
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.patch(
                    f"/admin/public-ai-features/feature_routing?account_id={uuid4()}",
                    json={"enabled": False, "billable": True},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["feature_key"] == "feature_routing"


class TestAdminAppAssignment:
    def _setup(self, monkeypatch):
        from internal.service.admin_app_assignment_service import AdminAppAssignmentService

        svc = _FakeAdminAppAssignmentService()
        _setup(monkeypatch, {AdminAppAssignmentService: svc})
        return svc

    def test_list(self, monkeypatch):
        svc = self._setup(monkeypatch)
        account_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/users/{account_id}/app-assignments?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert len(payload["data"]["list"]) == 1
        assert svc.calls[0][0] == "list"
        assert svc.calls[0][1] == account_id

    def test_assign(self, monkeypatch):
        svc = self._setup(monkeypatch)
        account_id = uuid4()
        app_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/users/{account_id}/app-assignments?account_id={uuid4()}",
                    json={"app_ids": [str(app_id)]},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["assigned"] == 1
        assert svc.calls[0][0] == "assign"
        assert svc.calls[0][2] == [app_id]

    def test_assign_empty(self, monkeypatch):
        self._setup(monkeypatch)
        account_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/users/{account_id}/app-assignments?account_id={uuid4()}",
                    json={"app_ids": []},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_revoke(self, monkeypatch):
        svc = self._setup(monkeypatch)
        account_id = uuid4()
        assignment_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/users/{account_id}/app-assignments/{assignment_id}/revoke?account_id={uuid4()}",
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert svc.calls[0][0] == "revoke"
        assert svc.calls[0][2] == assignment_id


class TestAdminRoutingLog:
    def _setup(self, monkeypatch):
        from internal.service import RoutingLogService
        from internal.service.routing_log_retention_service import RoutingLogRetentionService

        log_svc = _FakeRoutingLogService()
        retention_svc = _FakeRoutingLogRetentionService()
        _setup(
            monkeypatch,
            {RoutingLogService: log_svc, RoutingLogRetentionService: retention_svc},
        )
        return log_svc, retention_svc

    def test_list(self, monkeypatch):
        log_svc, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/routing-logs?account_id={uuid4()}&status=success&current_page=2&page_size=10"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert len(payload["data"]["list"]) == 1
        assert log_svc.calls[0][1]["status"] == "success"
        assert log_svc.calls[0][1]["page"] == 2
        assert log_svc.calls[0][1]["page_size"] == 10

    def test_get_retention(self, monkeypatch):
        _, retention_svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/routing-logs/retention?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["retention_days"] == 7
        assert retention_svc.calls[0] == ("describe",)

    def test_set_retention(self, monkeypatch):
        _, retention_svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/routing-logs/retention?account_id={uuid4()}",
                    json={"retention_days": 30},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["retention_days"] == 30
        assert retention_svc.calls[0][0] == "set"
        assert retention_svc.calls[0][1] == 30

    def test_set_retention_invalid(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/routing-logs/retention?account_id={uuid4()}",
                    json={"retention_days": "abc"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"


class TestAdminResourceEntry:
    def _setup(self, monkeypatch):
        from internal.service.admin_tool_governance_service import AdminToolGovernanceService
        from internal.service import McpService, SkillService

        gov_svc = _FakeAdminToolGovernanceService()
        mcp_svc = _FakeMcpService()
        skill_svc = _FakeSkillService()
        _setup(
            monkeypatch,
            {
                AdminToolGovernanceService: gov_svc,
                McpService: mcp_svc,
                SkillService: skill_svc,
            },
        )
        return gov_svc, mcp_svc, skill_svc

    def test_tools(self, monkeypatch):
        gov_svc, _, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/tools?account_id={uuid4()}&keyword=search&page_size=10")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert len(payload["data"]["list"]) == 1
        assert gov_svc.calls[0][0] == "policies"
        assert gov_svc.calls[0][1] == "api_tool"
        assert gov_svc.calls[0][4] == "search"

    def test_mcp(self, monkeypatch):
        _, mcp_svc, _ = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/mcp?account_id={uuid4()}&search_word=fake")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert len(payload["data"]["list"]) == 1
        assert payload["data"]["paginator"]["current_page"] == 1
        assert mcp_svc.calls[0][0] == "mcp"
        assert mcp_svc.calls[0][3] == "fake"

    def test_skills(self, monkeypatch):
        _, _, skill_svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/skills?account_id={uuid4()}&category=general")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert len(payload["data"]["list"]) == 1
        assert skill_svc.calls[0][0] == "skills"


class TestAdminRecycleBin:
    def _setup(self, monkeypatch):
        from internal.service.recycle_bin_service import RecycleBinService

        svc = _FakeRecycleBinService()
        _setup(monkeypatch, {RecycleBinService: svc})
        return svc

    def test_list(self, monkeypatch):
        svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/recycle-bin?account_id={uuid4()}&resource_type=knowledge_base&status=pending"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["total"] == 1
        assert svc.calls[0][1]["status"] == "pending"
        assert svc.calls[0][1]["resource_type"] == "knowledge_base"

    def test_get(self, monkeypatch):
        svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/recycle-bin/1?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["resource_type"] == "knowledge_base"
        assert svc.calls[0] == ("get", 1)

    def test_restore(self, monkeypatch):
        svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/recycle-bin/1/restore?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert svc.calls[0][0] == "restore"
        assert svc.calls[0][1] == 1


class TestAdminCostStats:
    def _setup(self, monkeypatch):
        from internal.service.cost_stats_service import CostStatsService

        svc = _FakeCostStatsService()
        _setup(monkeypatch, {CostStatsService: svc})
        return svc

    def test_overview(self, monkeypatch):
        svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/cost-stats/overview?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["total_credits"] == 100
        assert svc.calls[0][0] == "overview"

    def test_overview_with_admin_token_uses_injector_service(self, monkeypatch):
        from internal.service.admin_user_service import AdminUserService
        from internal.service.cost_stats_service import CostStatsService

        svc = _FakeCostStatsService()
        account_id = uuid4()
        fake_admin_service = SimpleNamespace(
            get_current_admin_from_token=lambda token: {
                "id": str(uuid4()),
                "account_id": str(account_id),
            }
        )
        monkeypatch.setattr(support, "_load_account", lambda _aid: SimpleNamespace(id=account_id))
        monkeypatch.setattr(
            support,
            "_get_service",
            lambda cls: {CostStatsService: svc, AdminUserService: fake_admin_service}.get(cls),
        )

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    "/admin/cost-stats/overview",
                    headers={"Authorization": "Bearer admin-token"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["total_credits"] == 100
        assert svc.calls[0][0] == "overview"

    def test_by_dimension(self, monkeypatch):
        svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/cost-stats/by-dimension?account_id={uuid4()}&dimension=model&limit=5"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["dimension"] == "model"
        assert svc.calls[0][1] == "model"
        assert svc.calls[0][4] == 5

    def test_timeseries(self, monkeypatch):
        svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/cost-stats/timeseries?account_id={uuid4()}&granularity=hour"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["granularity"] == "hour"
        assert svc.calls[0][1] == "hour"


class TestAdminOrchestrationFlag:
    def _setup(self, monkeypatch):
        from internal.service.orchestration_feature_flag_service import (
            OrchestrationFeatureFlagService,
        )

        svc = _FakeOrchestrationFeatureFlagService()
        _setup(monkeypatch, {OrchestrationFeatureFlagService: svc})
        return svc

    def test_list(self, monkeypatch):
        svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/orchestration-flags?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"][0]["code"] == "flag_enable_xxx"
        assert svc.calls[0] == ("list",)

    def test_update(self, monkeypatch):
        svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/orchestration-flags/flag_enable_xxx?account_id={uuid4()}",
                    json={"enabled": True},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["enabled"] is True
        assert svc.calls[0][0] == "update"
        assert svc.calls[0][1] == "flag_enable_xxx"

    def test_update_requires_orchestration_flag_update_permission(self, monkeypatch):
        self._setup(monkeypatch)

        async def _denied(permission_code):
            return None, support._err("forbidden", "无权限执行该操作", 403)

        monkeypatch.setattr(support, "_resolve_admin_permission", _denied)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/orchestration-flags/flag_enable_xxx?account_id={uuid4()}",
                    json={"enabled": True},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 403
        assert payload["code"] == "forbidden"


class TestAdminAuditLog:
    def _setup(self, monkeypatch):
        from internal.service.audit_log_service import AuditLogService

        svc = _FakeAuditLogService()
        _setup(monkeypatch, {AuditLogService: svc})
        return svc

    def test_list(self, monkeypatch):
        svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    f"/admin/audit-logs?account_id={uuid4()}&action=update_app&current_page=1"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert len(payload["data"]["list"]) == 1
        assert svc.calls[0][1]["action"] == "update_app"


class TestAdminOrchestrationRelease:
    def _setup(self, monkeypatch):
        from internal.service.orchestration_release_check_service import (
            OrchestrationReleaseCheckService,
        )

        svc = _FakeOrchestrationReleaseCheckService()
        _setup(monkeypatch, {OrchestrationReleaseCheckService: svc})
        return svc

    def test_get_report(self, monkeypatch):
        svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/admin/orchestration-release-check?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["test_status"] == {"passed": True}
        assert svc.calls[0] == ("build",)


class TestAdminUploadFile:
    def _setup(self, monkeypatch):
        from internal.service import CosService

        svc = _FakeCosService()
        _setup(monkeypatch, {CosService: svc})
        return svc

    def test_upload_image(self, monkeypatch):
        svc = self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/admin/upload-files/image?account_id={uuid4()}",
                    files={
                        "file": FileStorage(stream=io.BytesIO(b"img"), filename="a.png")
                    },
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["image_url"] == "https://cdn.example/key.png"
        assert svc.calls[0][0] == "upload"
        assert svc.calls[0][1] == "a.png"

    def test_upload_image_empty(self, monkeypatch):
        self._setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(f"/admin/upload-files/image?account_id={uuid4()}")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"
