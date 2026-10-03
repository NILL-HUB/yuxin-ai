"""批次 4 CLI 路由覆盖：`/admin/cli` CRUD。

CLI 是与 builtin/api_tool/mcp/skill 并列的独立工具来源（source_type=cli），
admin 入口对齐 `/admin/mcp` 的鉴权/审计/响应形态。
"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
import app.http.admin_routes_4 as admin_routes_4  # noqa: F401  导入即触发路由注册
from app.http import support
from app.http.admin_routes_4 import register_routes

register_routes(asgi_app.quart_app)

from internal.service.cli_service import CliService  # noqa: E402


class _FakeCliService:
    """内存替身：记录调用并返回可控结果（不连真库）。"""

    def __init__(self):
        self.created: dict | None = None
        self.updated: tuple | None = None
        self.deleted: list = []

    def list_providers(self, account_id):
        return [{"id": "p1", "name": "vc", "tool_count": 2}]

    # 复用真实序列化器，避免测试里复制实现
    to_dict = staticmethod(CliService.to_dict)

    def create_provider(self, **kwargs):
        self.created = kwargs
        return SimpleNamespace(id=uuid4())

    def get_provider(self, provider_id):
        return SimpleNamespace(
            id=provider_id,
            name="vc",
            label="VideoCaptioner",
            description="字幕一条龙",
            category="video",
            command="cli-anything-vc",
            args=["--json"],
            tool_schema={"caption": {"description": "一站式", "parameters": {}}},
            task_keywords=["字幕"],
            timeout_seconds=30,
            enabled=True,
            is_public=False,
            tools=[object(), object()],
        )

    def update_provider(self, provider_id, **fields):
        self.updated = (provider_id, fields)
        return SimpleNamespace(id=provider_id)

    def delete_provider(self, provider_id):
        self.deleted.append(provider_id)
        return True


def _setup(monkeypatch, svc):
    """模拟 admin 已登录（含 cli:* 权限）+ DI 返回 fake CliService。

    注意：`asgi_app` 的 `_resolve_admin_operator` / `_resolve_admin_permission`
    委托到 `support` 模块属性，且全局 RBAC 门禁（before_request）也走
    `support._resolve_admin_permission`，故 mock 必须打在 `support` 上。
    """
    admin = {
        "id": str(uuid4()),
        "permissions": ["cli:read", "cli:create", "cli:update", "cli:delete"],
    }

    async def _fake_resolve_admin_permission(_permission_code=None):
        return admin, None

    monkeypatch.setattr(support, "_resolve_admin_permission", _fake_resolve_admin_permission)
    monkeypatch.setattr(support, "_get_service", lambda cls: svc if cls is CliService else None)
    return admin


def test_list_cli_providers(monkeypatch):
    svc = _FakeCliService()
    _setup(monkeypatch, svc)

    client = asgi_app.quart_app.test_client()
    resp = asyncio.run(client.get("/admin/cli"))

    assert resp.status_code == 200
    body = asyncio.run(resp.get_json())
    assert body["data"]["items"][0]["name"] == "vc"


def test_create_cli_provider_requires_name(monkeypatch):
    svc = _FakeCliService()
    _setup(monkeypatch, svc)

    client = asgi_app.quart_app.test_client()
    resp = asyncio.run(client.post("/admin/cli", json={"command": "cli-anything-vc", "tool_schema": {"a": {}}}))

    assert resp.status_code == 400
    body = asyncio.run(resp.get_json())
    assert body["code"] == "validate_error"
    assert "name" in body["data"]


def test_create_cli_provider_requires_command(monkeypatch):
    svc = _FakeCliService()
    _setup(monkeypatch, svc)

    client = asgi_app.quart_app.test_client()
    resp = asyncio.run(client.post("/admin/cli", json={"name": "vc", "tool_schema": {"a": {}}}))

    assert resp.status_code == 400
    body = asyncio.run(resp.get_json())
    assert "command" in body["data"]


def test_create_cli_provider_requires_tool_schema(monkeypatch):
    """纯 CLI 无自描述能力：不声明能力说明书即不可用（服务端强校验）。"""
    svc = _FakeCliService()
    _setup(monkeypatch, svc)

    client = asgi_app.quart_app.test_client()
    resp = asyncio.run(client.post("/admin/cli", json={"name": "vc", "command": "cli-anything-vc"}))

    assert resp.status_code == 400
    body = asyncio.run(resp.get_json())
    assert "tool_schema" in body["data"]


def test_create_cli_provider_success(monkeypatch):
    svc = _FakeCliService()
    _setup(monkeypatch, svc)

    payload = {
        "name": "vc",
        "command": "cli-anything-vc",
        "tool_schema": {"caption": {"description": "一站式生成字幕并烧录", "parameters": {"type": "object"}}},
        "task_keywords": ["字幕"],
        "timeout_seconds": 45,
    }
    client = asgi_app.quart_app.test_client()
    resp = asyncio.run(client.post("/admin/cli", json=payload))

    assert resp.status_code == 200
    assert svc.created["name"] == "vc"
    assert svc.created["command"] == "cli-anything-vc"
    assert svc.created["timeout_seconds"] == 45
    assert svc.created["task_keywords"] == ["字幕"]
    assert "caption" in svc.created["tool_schema"]


def test_get_cli_provider_not_found(monkeypatch):
    svc = _FakeCliService()
    svc.get_provider = lambda _pid: None
    _setup(monkeypatch, svc)

    client = asgi_app.quart_app.test_client()
    resp = asyncio.run(client.get(f"/admin/cli/{uuid4()}"))

    assert resp.status_code == 404


def test_get_cli_provider_success(monkeypatch):
    svc = _FakeCliService()
    _setup(monkeypatch, svc)

    provider_id = uuid4()
    client = asgi_app.quart_app.test_client()
    resp = asyncio.run(client.get(f"/admin/cli/{provider_id}"))

    assert resp.status_code == 200
    body = asyncio.run(resp.get_json())
    assert body["data"]["name"] == "vc"
    assert body["data"]["tool_count"] == 2


def test_update_cli_provider_forwards_fields(monkeypatch):
    svc = _FakeCliService()
    _setup(monkeypatch, svc)

    provider_id = uuid4()
    client = asgi_app.quart_app.test_client()
    resp = asyncio.run(
        client.put(
            f"/admin/cli/{provider_id}",
            json={"label": "NewLabel", "tool_schema": {"caption": {"description": "d", "parameters": {}}}},
        )
    )

    assert resp.status_code == 200
    _, fields = svc.updated
    assert fields["label"] == "NewLabel"
    assert "caption" in fields["tool_schema"]


def test_update_cli_provider_rejects_empty_tool_schema(monkeypatch):
    svc = _FakeCliService()
    _setup(monkeypatch, svc)

    client = asgi_app.quart_app.test_client()
    resp = asyncio.run(client.put(f"/admin/cli/{uuid4()}", json={"tool_schema": {}}))

    assert resp.status_code == 400


def test_delete_cli_provider_success(monkeypatch):
    svc = _FakeCliService()
    _setup(monkeypatch, svc)

    provider_id = uuid4()
    client = asgi_app.quart_app.test_client()
    resp = asyncio.run(client.delete(f"/admin/cli/{provider_id}"))

    assert resp.status_code == 200
    assert svc.deleted == [provider_id]


def test_delete_cli_provider_not_found(monkeypatch):
    svc = _FakeCliService()
    svc.delete_provider = lambda _pid: False
    _setup(monkeypatch, svc)

    client = asgi_app.quart_app.test_client()
    resp = asyncio.run(client.delete(f"/admin/cli/{uuid4()}"))

    assert resp.status_code == 404
