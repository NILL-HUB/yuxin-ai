import asyncio
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from app.http import support
import app.http.asgi_app as asgi_app


def _recycle_item(item_id):
    return SimpleNamespace(
        id=item_id,
        resource_type="knowledge_base",
        resource_id=str(uuid4()),
        resource_key="kb-key",
        resource_name="用户知识库",
        deleted_by=str(uuid4()),
        deleted_by_name="用户",
        deleted_by_type="user",
        deleted_at=datetime(2026, 8, 8, 8, 0, 0),
        retention_days=30,
        expire_at=datetime(2026, 9, 7, 8, 0, 0),
        status="pending",
        remark="",
        snapshot={},
    )


class _FakeUserRecycleBinService:
    def __init__(self):
        self.calls = []

    def list_user_items(self, **kwargs):
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

    def _check_user_owned(self, item, account_id):
        self.calls.append(("check", item.id, account_id))

    def restore_user_item(
        self,
        item_id,
        account_id,
        *,
        target_path="",
        confirm_device_mismatch=False,
    ):
        self.calls.append(
            ("restore", item_id, account_id, target_path, confirm_device_mismatch)
        )
        return _recycle_item(item_id)


def _setup(monkeypatch):
    from internal.service.recycle_bin_service import RecycleBinService

    account = SimpleNamespace(id=uuid4())
    svc = _FakeUserRecycleBinService()

    async def _fake_resolve_account(account_id_override=None):
        return account, None

    monkeypatch.setattr(support, "_resolve_account", _fake_resolve_account)
    monkeypatch.setattr(support, "_get_service", lambda cls: svc if cls is RecycleBinService else None)
    return account, svc


class TestUserRecycleBinRoutes:
    def test_routes_registered(self):
        rules = [r.rule for r in asgi_app.quart_app.url_map.iter_rules()]
        assert "/space/recycle-bin" in rules
        assert "/space/recycle-bin/<int:item_id>" in rules
        assert "/space/recycle-bin/<int:item_id>/restore" in rules

    def test_list(self, monkeypatch):
        _, svc = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(
                    "/space/recycle-bin?page=1&page_size=20&status=pending"
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["total"] == 1
        assert svc.calls[0][0] == "list"
        assert svc.calls[0][1]["status"] == "pending"

    def test_get(self, monkeypatch):
        _, svc = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get("/space/recycle-bin/1")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["resource_type"] == "knowledge_base"
        assert svc.calls[0] == ("get", 1)
        assert svc.calls[1][0] == "check"

    def test_restore(self, monkeypatch):
        _, svc = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/space/recycle-bin/1/restore",
                    json={"target_path": "C:/tmp/restore", "confirm_device_mismatch": True},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"]["resource_type"] == "knowledge_base"
        assert svc.calls[0][0] == "restore"
        assert svc.calls[0][1] == 1
        assert svc.calls[0][3] == "C:/tmp/restore"
        assert svc.calls[0][4] is True


def test_user_jwt_blocked_from_admin_recycle_bin():
    assert support._is_user_api_blocked("/admin/recycle-bin", "GET") is True
    assert support._is_user_api_blocked("/admin/recycle-bin/1/restore", "POST") is True
