"""外部数据源路由响应脱敏测试：密钥不得以明文回传。"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
from app.http import knowledge_mcp_routes, support
from app.http.knowledge_mcp_routes import register_routes

register_routes(asgi_app.quart_app)


def _flat_strings(payload):
    """收集 JSON 中所有字符串值，用于断言不含明文密钥。"""
    found = []

    def _walk(node):
        if isinstance(node, dict):
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for value in node:
                _walk(value)
        elif isinstance(node, str):
            found.append(node)

    _walk(payload)
    return found


def test_list_masks_sensitive_config(monkeypatch):
    from internal.service.external_data_source_credentials import encrypt_config

    account = SimpleNamespace(id=uuid4())
    row = SimpleNamespace(
        id=uuid4(),
        knowledge_base_id=uuid4(),
        source_type="lark",
        source_name="Lark KB",
        authorization_status="granted",
        sync_status="idle",
        sync_cursor="",
        last_synced_at=None,
        last_error="",
        config=encrypt_config({"app_id": "cli_x", "app_secret": "super-secret"}),
        created_at=None,
        updated_at=None,
    )

    class _Service:
        def list_data_sources(self, account, status=""):
            return [row]

    async def _fake_resolve_account(account_id_override=None):
        return account, None

    monkeypatch.setattr(knowledge_mcp_routes, "_resolve_account", _fake_resolve_account)
    monkeypatch.setattr(support, "_get_service", lambda cls: _Service())

    async def _run():
        async with asgi_app.quart_app.test_client() as client:
            resp = await client.get("/external-data-sources")
            return resp, await resp.json

    resp, payload = asyncio.run(_run())
    assert resp.status_code == 200

    values = _flat_strings(payload)
    assert "super-secret" not in values
    # 加密落库后响应若直接回传 config，泄露的是可逆密文（gAAAAA 前缀），必须一并拦截
    assert not any(value.startswith("gAAAAA") for value in values)
    items = payload["data"]["items"]
    assert items[0]["config"]["app_id"] == "cli_x"
    assert items[0]["config"]["app_secret"] != "super-secret"
    assert "*" in items[0]["config"]["app_secret"]
