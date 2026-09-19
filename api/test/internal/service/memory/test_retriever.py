"""B3 MemoryRetriever 单元测试。"""

from uuid import uuid4

import pytest

from internal.model.memory_models import RetrievalOptions
from internal.service.memory.retriever import MemoryRetriever


class TestMemoryRetriever:
    def test_retrieve_should_return_empty_without_dependencies(self):
        """无 Neo4j 和数据库时应降级返回空列表。"""
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        result = retriever.retrieve("测试查询", str(uuid4()))

        assert isinstance(result, list)
        # 无依赖时应返回空或降级结果，不抛异常

    def test_retrieve_should_accept_empty_query(self):
        """空查询应降级处理。"""
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        result = retriever.retrieve("", str(uuid4()))

        assert isinstance(result, list)

    def test_retrieve_should_respect_top_k_option(self):
        """应支持 RetrievalOptions 的 top_k 参数。"""
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        options = RetrievalOptions(top_k=5)
        result = retriever.retrieve("测试", str(uuid4()), options)

        assert isinstance(result, list)
        assert len(result) <= 5

    def test_retrieve_should_fallback_to_system2_without_digest_manager(self):
        """无 DigestManager 时应走 System 2 深度路径（降级为空）。"""
        retriever = MemoryRetriever(neo4j_driver=None, db=None, digest_manager=None)
        result = retriever.retrieve("任意查询", str(uuid4()))

        assert isinstance(result, list)


class _RecordingCypherResult:
    def __init__(self, record=None, records=None):
        self._record = record
        self._records = list(records or [])

    def single(self):
        return self._record

    def __iter__(self):
        return iter(self._records)


class _RecordingSession:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, parameters=None, **binds):
        params = dict(parameters or {})
        params.update(binds)
        self.calls.append((cypher, params))
        return self._result


class _RecordingDriver:
    def __init__(self, result=None, records=None):
        self._result = _RecordingCypherResult(record=result, records=records)
        self.session_obj = None

    def session(self):
        self.session_obj = _RecordingSession(self._result)
        return self.session_obj


class TestGetNodeDataOwnerScope:
    """缺口一（ADMIN-P3c-4）：节点详情查询按主体谓词约束。"""

    def test_get_node_data_omits_owner_without_owner_key(self):
        retriever = MemoryRetriever(neo4j_driver=_RecordingDriver(records=[{
            "content": "x", "summary": "", "created_at": None, "user_id": None,
        }]), db=None)
        retriever._get_node_data(str(uuid4()))

        cypher, params = retriever._driver.session_obj.calls[0]
        assert "WHERE true" in cypher
        assert "$user_id" not in cypher
        assert "user_id" not in params

    def test_get_node_data_binds_user_owner(self):
        retriever = MemoryRetriever(neo4j_driver=_RecordingDriver(records=[{
            "content": "x", "summary": "", "created_at": None, "user_id": None,
        }]), db=None)
        uid = str(uuid4())
        retriever._get_node_data(str(uuid4()), owner_key=uid)

        cypher, params = retriever._driver.session_obj.calls[0]
        assert "n.user_id = $user_id" in cypher
        assert params["user_id"] == uid

    def test_get_node_data_binds_admin_owner(self):
        retriever = MemoryRetriever(neo4j_driver=_RecordingDriver(records=[{
            "content": "x", "summary": "", "created_at": None, "user_id": None,
        }]), db=None)
        admin_id = str(uuid4())
        retriever._get_node_data(str(uuid4()), owner_key=f"admin:{admin_id}")

        cypher, params = retriever._driver.session_obj.calls[0]
        assert "n.admin_user_id = $admin_user_id" in cypher
        assert params["admin_user_id"] == admin_id
        assert params["agent_id"] == "__admin_level__"


class TestGraphSpreadOwnerScope:
    """缺口一（ADMIN-P3c-4）：图扩展把 owner_key 透传给 SpreadActivation。"""

    def test_graph_spread_passes_owner_to_activate(self, monkeypatch):
        from internal.service.memory.spread_activation import SpreadActivation

        captured = {}

        def _fake_activate(self, start_nodes, top_k=20, owner_key=""):
            captured["owner_key"] = owner_key
            captured["start_nodes"] = start_nodes
            return []

        monkeypatch.setattr(SpreadActivation, "activate", _fake_activate)
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        uid = str(uuid4())

        retriever._graph_spread(["n1", "n2"], top_k=10, owner_key=uid)

        assert captured["owner_key"] == uid
        assert captured["start_nodes"] == ["n1", "n2"]
