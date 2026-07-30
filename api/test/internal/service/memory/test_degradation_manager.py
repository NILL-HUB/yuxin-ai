"""D3 DegradationManager 单元测试。"""

from types import SimpleNamespace

import pytest

from internal.service.memory.degradation_manager import (
    DegradationManager,
    get_degradation_manager,
)


class TestDegradationManager:
    def test_disabled_when_all_unavailable(self):
        dm = DegradationManager(
            neo4j_driver=None, db=None, redis_client=None, celery_app=None
        )
        dm.check_all()
        assert dm.get_retrieval_strategy() == "disabled"
        assert dm.is_write_available() is False
        assert dm.is_consolidation_available() is False
        assert dm.memory_engine_enabled is False

    def test_full_when_neo4j_and_pgvector_ok(self, monkeypatch):
        dm = DegradationManager()
        # 模拟 Neo4j 和 pgvector 可用
        dm._neo4j_ok = True
        dm._pgvector_ok = True
        dm._redis_ok = True
        dm._celery_ok = True
        dm._memory_engine_enabled = True

        assert dm.get_retrieval_strategy() == "full"
        assert dm.is_write_available() is True
        assert dm.is_consolidation_available() is True

    def test_vector_only_when_neo4j_down(self):
        dm = DegradationManager()
        dm._neo4j_ok = False
        dm._pgvector_ok = True
        dm._redis_ok = True
        dm._celery_ok = True

        assert dm.get_retrieval_strategy() == "vector_only"

    def test_graph_only_when_pgvector_down(self):
        dm = DegradationManager()
        dm._neo4j_ok = True
        dm._pgvector_ok = False
        dm._redis_ok = True
        dm._celery_ok = True

        assert dm.get_retrieval_strategy() == "graph_only"

    def test_digest_only_when_neo4j_and_pgvector_down(self):
        dm = DegradationManager()
        dm._neo4j_ok = False
        dm._pgvector_ok = False
        dm._redis_ok = True
        dm._celery_ok = False

        assert dm.get_retrieval_strategy() == "digest_only"

    def test_get_status(self):
        dm = DegradationManager()
        dm._neo4j_ok = True
        dm._pgvector_ok = True
        dm._memory_engine_enabled = True

        status = dm.get_status()
        assert status["neo4j"] is True
        assert status["memory_engine_enabled"] is True
        assert status["retrieval_strategy"] == "full"

    def test_get_degradation_manager_returns_none_when_not_initialized(self):
        # 清理单例（测试隔离）
        import internal.service.memory.degradation_manager as mod
        old = mod._degradation_manager
        mod._degradation_manager = None
        try:
            assert get_degradation_manager() is None
        finally:
            mod._degradation_manager = old
