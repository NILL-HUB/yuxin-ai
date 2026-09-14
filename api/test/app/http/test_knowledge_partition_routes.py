"""知识库分区路由测试：列出 / 创建 / 删除分区的参数校验与服务调用。"""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import app.http.asgi_app as asgi_app
from app.http import knowledge_mcp_routes, support
from internal.service.knowledge_base_service import KnowledgeBaseService
from internal.service.knowledge_partition_service import KnowledgePartitionService

knowledge_mcp_routes.register_routes(asgi_app.quart_app)


class _FakeKnowledgeBaseService:
    """只提供路由用到的归属校验，避免越权读分区。"""

    def get_accessible_base(self, knowledge_base_id, account):
        return SimpleNamespace(id=knowledge_base_id)


class _FakePartitionService:
    def __init__(self):
        self.calls = []
        self.last_create_kwargs = {}

    def list_partitions(self, knowledge_base_id):
        self.calls.append(("list", knowledge_base_id))
        return [
            SimpleNamespace(
                id=uuid4(), name="产品A", partition_key="product-a",
                parent_id=None, description="", sort_order=1,
            )
        ]

    def create_partition(self, *, knowledge_base_id, name, partition_key,
                         parent_id=None, description="", sort_order=0):
        self.calls.append(("create", knowledge_base_id, name, partition_key, parent_id))
        self.last_create_kwargs = {
            "knowledge_base_id": knowledge_base_id,
            "name": name,
            "partition_key": partition_key,
            "parent_id": parent_id,
            "description": description,
            "sort_order": sort_order,
        }
        return SimpleNamespace(id=uuid4(), name=name, partition_key=partition_key)

    def delete_partition(self, knowledge_base_id, partition_id):
        self.calls.append(("delete", knowledge_base_id, partition_id))


def _setup(monkeypatch):
    account = SimpleNamespace(id=uuid4())
    svc = _FakePartitionService()
    kb_svc = _FakeKnowledgeBaseService()

    async def _fake_resolve_account(account_id_override=None):
        return account, None

    def _fake_get_service(cls):
        if cls is KnowledgePartitionService:
            return svc
        if cls is KnowledgeBaseService:
            return kb_svc
        return None

    monkeypatch.setattr(knowledge_mcp_routes, "_resolve_account", _fake_resolve_account)
    monkeypatch.setattr(support, "_get_service", _fake_get_service)
    return account, svc


class TestKnowledgePartitionRoutes:
    def test_routes_registered(self):
        rules = [r.rule for r in asgi_app.quart_app.url_map.iter_rules()]
        assert "/space/knowledge-bases/<uuid:knowledge_base_id>/partitions" in rules
        assert (
            "/space/knowledge-bases/<uuid:knowledge_base_id>/partitions/<uuid:partition_id>/delete"
            in rules
        )

    def test_list_partitions(self, monkeypatch):
        _, svc = _setup(monkeypatch)
        kb_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.get(f"/space/knowledge-bases/{kb_id}/partitions")
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        assert payload["data"][0]["name"] == "产品A"
        assert svc.calls[0][0] == "list"

    def test_create_partition_requires_name(self, monkeypatch):
        _setup(monkeypatch)
        kb_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{kb_id}/partitions", json={}
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 400
        assert payload["code"] == "validate_error"

    def test_create_partition_derives_key_from_name_when_absent(self, monkeypatch):
        """未显式传 partition_key 时由名称派生，保证唯一键必填约束不阻塞用户。"""
        _, svc = _setup(monkeypatch)
        kb_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{kb_id}/partitions", json={"name": "产品A"}
                )
                return resp, await resp.json

        resp, _payload = asyncio.run(_run())
        assert resp.status_code == 200
        create_call = [c for c in svc.calls if c[0] == "create"][0]
        assert create_call[1] == kb_id
        assert create_call[2] == "产品A"
        assert create_call[3]

    def test_create_partition_rejects_level_three(self, monkeypatch):
        """三级分区必须被服务层拒绝，路由应把异常转成错误响应而非 500。"""
        _setup(monkeypatch)
        kb_id = uuid4()
        parent_id = uuid4()

        def _reject(**kwargs):
            from internal.exception import ValidateErrorException

            raise ValidateErrorException("分区最多支持 2 级，不能在子分区下继续创建")

        svc = support._get_service(KnowledgePartitionService)
        monkeypatch.setattr(svc, "create_partition", _reject)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{kb_id}/partitions",
                    json={"name": "三级", "parent_id": str(parent_id)},
                )
                return resp, await resp.json

        resp, _payload = asyncio.run(_run())
        assert resp.status_code != 500

    def test_create_partition_passes_sort_order_from_json_body(self, monkeypatch):
        """sort_order 在 JSON body 里，不能被只读 query 参数的解析器吞掉。"""
        _, svc = _setup(monkeypatch)
        kb_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{kb_id}/partitions",
                    json={"name": "产品A", "sort_order": 7},
                )
                return resp, await resp.json

        resp, _payload = asyncio.run(_run())
        assert resp.status_code == 200
        create_call = [c for c in svc.calls if c[0] == "create"][0]
        assert create_call[4] is None, "未传 parent_id 时应为 None"

        # 直接把 create_partition 的 kwargs 也断言一遍，避免只测到位置参数
        assert svc.last_create_kwargs["sort_order"] == 7

    def test_delete_partition(self, monkeypatch):
        _, svc = _setup(monkeypatch)
        kb_id = uuid4()
        partition_id = uuid4()

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{kb_id}/partitions/{partition_id}/delete"
                )
                return resp, await resp.json

        resp, _payload = asyncio.run(_run())
        assert resp.status_code == 200
