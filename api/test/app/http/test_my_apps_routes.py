"""GET /my/apps 路由测试：验证普通用户可访问且响应含 can_edit。"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
from app.http import apps_routes, support

apps_routes.register_routes(asgi_app.quart_app)


class _FakeMyAppService:
    def __init__(self):
        self.calls = []

    def list_my_apps(self, account_id):
        self.calls.append(str(account_id))
        return {
            "list": [
                {
                    "id": "app-1",
                    "assignment_id": "asg-1",
                    "name": "Contract AI",
                    "icon": "",
                    "description": "desc",
                    "assigned_at": 1893456000,
                    "source": "assigned",
                    "status": "published",
                    "can_edit": False,
                }
            ]
        }


def test_list_my_apps_returns_can_edit(monkeypatch):
    account = SimpleNamespace(id=uuid4())
    service = _FakeMyAppService()

    async def _fake_resolve_account(account_id_override=None):
        return account, None

    # apps_routes 以「按值导入」方式持有 _resolve_account，必须在其模块命名空间打桩
    monkeypatch.setattr(apps_routes, "_resolve_account", _fake_resolve_account)
    monkeypatch.setattr(support, "_get_service", lambda cls: service)

    async def _run():
        async with asgi_app.quart_app.test_client() as client:
            resp = await client.get("/my/apps")
            return resp, await resp.json

    resp, payload = asyncio.run(_run())
    assert resp.status_code == 200
    assert payload["code"] == "success"
    items = payload["data"]["list"]
    assert len(items) == 1
    assert items[0]["can_edit"] is False
    assert service.calls == [str(account.id)]
