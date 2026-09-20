"""管理端记忆 GDPR 删除路由测试（ADMIN-P4 Task 1）。

被测逻辑：``POST /admin/memory/gdpr-delete`` 的路由接线——
- 必须映射到 ``agent_pool:manage``（fail-closed 登记）；
- body 的主体分解字段必须被服务端翻译成 ``MemoryOwnerKey`` 字符串（不信任客户端裸 key）；
- 非法 subject_type / 缺失 agent_id → 400；
- 无权限 → 403。
"""
import asyncio
from uuid import UUID, uuid4

import app.http.asgi_app as asgi_app
import internal.service.memory.memory_governor as memory_governor_module
from app.http import support
from app.http.admin_routes_7 import register_routes

register_routes(asgi_app.quart_app)


def _admin_ctx(admin_id, permissions):
    async def _fake(permission_code=None):
        # 模拟真实 _resolve_admin_permission 的权限校验语义
        if permission_code and permission_code not in permissions:
            return None, support._err("forbidden", "无权限执行该操作", 403)
        return {
            "id": str(admin_id),
            "roles": ["operator"],
            "permissions": list(permissions),
        }, None

    return _fake


class _Recorder:
    def __init__(self):
        self.calls = []

    def gdpr_delete(self, owner_key):
        self.calls.append(owner_key)
        return {
            "neo4j_nodes": 1,
            "neo4j_edges": 2,
            "pgvector_rows": 3,
            "redis_keys": 4,
        }


def _wire(monkeypatch, admin_id, permissions, recorder):
    monkeypatch.setattr(
        support, "_resolve_admin_permission", _admin_ctx(admin_id, permissions)
    )
    monkeypatch.setattr(
        memory_governor_module.MemoryGovernor, "gdpr_delete", recorder.gdpr_delete
    )
    return recorder


def _post(path, json_body):
    async def _run():
        client = asgi_app.quart_app.test_client()
        return await client.post(path, json=json_body)

    return asyncio.run(_run())


class TestPermissionMapping:
    def test_gdpr_delete_requires_agent_pool_manage(self):
        """GDPR 删除是破坏性操作，必须映射到 agent_pool:manage（不能落到 read/未登记）。"""
        assert (
            support._admin_route_permission("POST", "/admin/memory/gdpr-delete")
            == "agent_pool:manage"
        )


class TestGdprDeleteEndpoint:
    def test_user_subject_translates_to_bare_uuid(self, monkeypatch):
        """user 主体 → 裸 UUID owner_key（与用户态历史语义逐字节一致）。"""
        admin_id = uuid4()
        recorder = _Recorder()
        _wire(monkeypatch, admin_id, ["agent_pool:manage"], recorder)
        subject_id = uuid4()
        resp = _post(
            "/admin/memory/gdpr-delete",
            {"subject_type": "user", "subject_id": str(subject_id)},
        )
        assert resp.status_code == 200
        assert recorder.calls == [str(subject_id)]

    def test_admin_subject_translates_to_admin_prefix(self, monkeypatch):
        admin_id = uuid4()
        recorder = _Recorder()
        _wire(monkeypatch, admin_id, ["agent_pool:manage"], recorder)
        subject_id = uuid4()
        resp = _post(
            "/admin/memory/gdpr-delete",
            {"subject_type": "admin", "subject_id": str(subject_id)},
        )
        assert resp.status_code == 200
        assert recorder.calls == [f"admin:{subject_id}"]

    def test_agent_subject_translates_to_admin_agent_two_level(self, monkeypatch):
        admin_id = uuid4()
        recorder = _Recorder()
        _wire(monkeypatch, admin_id, ["agent_pool:manage"], recorder)
        admin_uuid = uuid4()
        agent_uuid = uuid4()
        resp = _post(
            "/admin/memory/gdpr-delete",
            {
                "subject_type": "agent",
                "subject_id": str(admin_uuid),
                "agent_id": str(agent_uuid),
            },
        )
        assert resp.status_code == 200
        assert recorder.calls == [f"admin:{admin_uuid}:{agent_uuid}"]

    def test_agent_subject_requires_agent_id(self, monkeypatch):
        admin_id = uuid4()
        recorder = _Recorder()
        _wire(monkeypatch, admin_id, ["agent_pool:manage"], recorder)
        resp = _post(
            "/admin/memory/gdpr-delete",
            {"subject_type": "agent", "subject_id": str(uuid4())},
        )
        assert resp.status_code == 400
        assert recorder.calls == []

    def test_invalid_subject_type_rejected(self, monkeypatch):
        admin_id = uuid4()
        recorder = _Recorder()
        _wire(monkeypatch, admin_id, ["agent_pool:manage"], recorder)
        resp = _post(
            "/admin/memory/gdpr-delete",
            {"subject_type": "space", "subject_id": str(uuid4())},
        )
        assert resp.status_code == 400
        assert recorder.calls == []

    def test_invalid_uuid_rejected(self, monkeypatch):
        admin_id = uuid4()
        recorder = _Recorder()
        _wire(monkeypatch, admin_id, ["agent_pool:manage"], recorder)
        resp = _post(
            "/admin/memory/gdpr-delete",
            {"subject_type": "user", "subject_id": "not-a-uuid"},
        )
        assert resp.status_code == 400
        assert recorder.calls == []

    def test_forbidden_without_permission(self, monkeypatch):
        admin_id = uuid4()
        recorder = _Recorder()
        _wire(monkeypatch, admin_id, [], recorder)
        resp = _post(
            "/admin/memory/gdpr-delete",
            {"subject_type": "user", "subject_id": str(uuid4())},
        )
        assert resp.status_code == 403
        assert recorder.calls == []
