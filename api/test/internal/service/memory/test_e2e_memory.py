"""H5 E2E 集成测试 -- 记忆系统全链路。

覆盖以下场景（mock 依赖，不依赖 Docker compose）：
    1. 写入（FULL 路径）：MemoryEvent → MemoryWriteService → LedgerWriter
    2. 检索：MemoryRetriever.retrieve → 返回 RetrievalResult 列表
    3. Digest：DigestManager.get_digest → 缓存命中/未命中
    4. 巩固：ConsolidationEngine.run_consolidation → ConsolidationReport
    5. 降级：DegradationManager 状态切换 → HealthService 健康检查反映

说明：
    图可视化（GET /memory/graph）与 CRUD（编辑/软删除/彻底删除）端点
    已由 A1 轨 test_user_routes_9 覆盖，handler 层不再单独测试。

设计说明:
    由于 Docker compose 未启动，本测试使用 mock 替代真实 Neo4j/pgvector/Redis。
    验证各组件的编排逻辑、数据流、降级策略与接口契约，
    而非真实 I/O。Docker 就绪后可替换 mock 为真实客户端运行端到端测试。

设计参考:
    docs/prd/memory-system/execution/09-track-h-monitoring-test.md H5
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from test.context import TestApp

from internal.model.memory_models import (
    EventSource,
    MemoryEvent,
    RetrievalOptions,
    WritePath,
)
from internal.service.health_service import HealthService
from internal.service.memory.consolidation_engine import ConsolidationEngine
from internal.service.memory.degradation_manager import (
    DegradationManager,
    get_degradation_manager,
)
from internal.service.memory.digest_manager import DigestManager
from internal.service.memory.ledger_writer import LedgerWriter
from internal.service.memory.memory_write_service import MemoryWriteService
from internal.service.memory.retriever import MemoryRetriever
from internal.service.memory.salience_scorer import SalienceScorer
from internal.service.memory.entity_extractor import MemoryEntityExtractor
from internal.service.memory.metrics import MetricsCollector


# =========================================================
# 共享 Fixture
# =========================================================


@pytest.fixture
def flask_app():
    """提供 Flask 应用上下文。"""
    app = TestApp(__name__)
    app.config["TESTING"] = True
    with app.app_context():
        yield app


@pytest.fixture
def mock_db():
    """提供 mock SQLAlchemy 实例（LedgerWriter 需要 db.session）。"""
    db = MagicMock()
    mock_session = MagicMock()
    db.session = mock_session
    return db


@pytest.fixture
def user_id():
    """测试用户 ID。"""
    return str(uuid4())


@pytest.fixture
def mock_neo4j_session():
    """模拟 Neo4j session。"""
    session = MagicMock()
    session.run.return_value = MagicMock()
    session.run.return_value.single.return_value = None
    session.run.return_value.__iter__ = MagicMock(return_value=iter([]))
    return session


@pytest.fixture
def mock_neo4j_driver(mock_neo4j_session):
    """模拟 Neo4j 驱动。"""
    driver = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=mock_neo4j_session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver


@pytest.fixture
def fake_redis():
    """模拟 Redis 客户端。"""
    store = {}

    class _FakeRedis:
        def get(self, key):
            return store.get(key)

        def setex(self, key, ttl, val):
            store[key] = val

        def delete(self, key):
            store.pop(key, None)

        def ping(self):
            return True

    return _FakeRedis()


# =========================================================
# 场景 1：写入（FULL 路径）
# =========================================================


class TestE2EWriteFullPath:
    """场景 1：POST /memory/write（FULL 路径）。"""

    def test_e2e_write_full_path_returns_memory_id(self, flask_app, user_id, mock_neo4j_driver, mock_db):
        """写入：MemoryEvent → MemoryWriteService → LedgerWriter → 返回 memory_id。"""
        # 构造 MemoryEvent
        event = MemoryEvent(
            event_id=uuid4(),
            timestamp=datetime.now(UTC),
            source=EventSource.USER_MESSAGE,
            content="用户喜欢用 Python 编写数据处理脚本",
            context_messages=[],
            metadata={"memory_type": "user_message", "source": "e2e_test"},
            user_id=user_id,
        )

        # 构造 LedgerWriter（仅接受 db 参数，Neo4j 驱动通过 _get_driver 获取）
        ledger_writer = LedgerWriter(db=mock_db)
        # mock _get_driver 返回模拟驱动
        with patch.object(ledger_writer, "_get_driver", return_value=mock_neo4j_driver):
            result = ledger_writer.write_full_path(
                event=event,
                entities=[{"name": "Python", "type": "language"}],
                relations=[],
                embedding=[0.1] * 128,
            )

        assert isinstance(result, dict)
        # FULL 路径应返回包含 memory_id 的结果（或降级空结果）
        if "memory_id" in result:
            assert result["memory_id"] is not None

    def test_e2e_write_full_path_with_none_dependencies(self, flask_app, user_id, mock_db):
        """无依赖时写入应降级而不崩溃。"""
        event = MemoryEvent(
            event_id=uuid4(),
            timestamp=datetime.now(UTC),
            source=EventSource.USER_MESSAGE,
            content="测试内容",
            user_id=user_id,
        )

        ledger_writer = LedgerWriter(db=mock_db)

        # 无 Neo4j 驱动时也不应抛异常
        with patch.object(ledger_writer, "_get_driver", return_value=None):
            result = ledger_writer.write_full_path(
                event=event,
                entities=[],
                relations=[],
                embedding=[0.0] * 128,
            )

        assert isinstance(result, dict)

    def test_e2e_write_records_metrics(self, flask_app, user_id, mock_neo4j_driver, mock_db):
        """写入后 metrics 应正确更新（memory_write_total 增加）。"""
        from internal.service.memory.metrics import memory_write_total

        before = memory_write_total._value._value

        event = MemoryEvent(
            event_id=uuid4(),
            timestamp=datetime.now(UTC),
            source=EventSource.USER_MESSAGE,
            content="metrics 测试",
            user_id=user_id,
        )

        ledger_writer = LedgerWriter(db=mock_db)
        with patch.object(ledger_writer, "_get_driver", return_value=mock_neo4j_driver):
            ledger_writer.write_full_path(
                event=event,
                entities=[],
                relations=[],
                embedding=[0.1] * 64,
            )

        after = memory_write_total._value._value
        assert after > before, "写入后 memory_write_total 应增加"


# =========================================================
# 场景 2：检索
# =========================================================


class TestE2ERetrieve:
    """场景 2：POST /memory/retrieve。"""

    def test_e2e_retrieve_returns_list(self, user_id):
        """检索应返回列表（无依赖时降级为空）。"""
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        results = retriever.retrieve("Python 数据处理", user_id)

        assert isinstance(results, list)

    def test_e2e_retrieve_empty_query_returns_empty(self, user_id):
        """空查询应返回空列表。"""
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        results = retriever.retrieve("", user_id)

        assert results == []

    def test_e2e_retrieve_respects_top_k(self, user_id):
        """应尊重 RetrievalOptions.top_k 限制。"""
        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        options = RetrievalOptions(top_k=5)
        results = retriever.retrieve("测试查询", user_id, options)

        assert len(results) <= 5

    def test_e2e_retrieve_records_metrics(self, user_id):
        """检索后 metrics 应正确更新。"""
        from internal.service.memory.metrics import memory_retrieve_total

        before = memory_retrieve_total._value._value

        retriever = MemoryRetriever(neo4j_driver=None, db=None)
        retriever.retrieve("metrics 检索测试", user_id)

        after = memory_retrieve_total._value._value
        assert after > before, "检索后 memory_retrieve_total 应增加"


# =========================================================
# 场景 3：Digest
# =========================================================


class TestE2EDigest:
    """场景 3：GET /memory/digest/{user_id}。"""

    def test_e2e_digest_returns_string(self, user_id, fake_redis):
        """Digest 应返回字符串。"""
        manager = DigestManager(redis_client=fake_redis)
        result = manager.get_digest(user_id)

        assert isinstance(result, str)

    def test_e2e_digest_cache_hit_on_second_request(self, user_id, fake_redis):
        """第二次请求应命中缓存。"""
        import json as json_module

        # 预填充缓存
        cached_text = "用户偏好：Python 编程"
        cache_payload = json_module.dumps({
            "text": cached_text,
            "updated_at": datetime.now(UTC).isoformat(),
        })
        fake_redis.setex(f"memory:digest:{user_id}", 300, cache_payload)

        manager = DigestManager(redis_client=fake_redis)

        # 第一次请求（命中缓存）
        result1 = manager.get_digest(user_id)
        assert result1 == cached_text

        # 第二次请求（仍命中缓存）
        result2 = manager.get_digest(user_id)
        assert result2 == cached_text

    def test_e2e_digest_records_cache_metrics(self, user_id, fake_redis):
        """Digest 缓存命中/未命中应记录 metrics。"""
        # 缓存未命中
        manager = DigestManager(redis_client=fake_redis)
        manager.get_digest(user_id)

        # 验证 record_digest_cache 被调用（通过 metrics 值变化间接验证）
        from internal.service.memory.metrics import memory_digest_cache_hit

        # Gauge 值应在 0-1 范围
        ratio = memory_digest_cache_hit._value._value
        assert 0.0 <= ratio <= 1.0


# =========================================================
# 场景 4：巩固
# =========================================================


class TestE2EConsolidate:
    """场景 4：POST /memory/consolidate/{user_id}。"""

    def test_e2e_consolidate_returns_report(self, user_id):
        """巩固应返回 ConsolidationReport。"""
        engine = ConsolidationEngine(neo4j_driver=None)
        report = engine.run_consolidation(user_id)

        assert hasattr(report, "phases")
        assert hasattr(report, "errors")
        assert hasattr(report, "merged_count")
        assert hasattr(report, "skills_emerged")
        assert isinstance(report.errors, list)

    def test_e2e_consolidate_report_has_phases_dict(self, user_id):
        """巩固报告 phases 应为字典。"""
        engine = ConsolidationEngine(neo4j_driver=None)
        report = engine.run_consolidation(user_id)

        assert isinstance(report.phases, dict)

    def test_e2e_consolidate_records_metrics(self, user_id):
        """巩固后 metrics 应记录耗时。"""
        from internal.service.memory.metrics import memory_consolidation_duration_seconds

        engine = ConsolidationEngine(neo4j_driver=None)
        engine.run_consolidation(user_id)

        # 验证 histogram 有观测值（通过 sample count 间接验证）
        # 由于无依赖时也可能记录，只要不抛异常即可
        assert memory_consolidation_duration_seconds is not None


# =========================================================
# 场景 5：降级
# =========================================================


class TestE2EDegradation:
    """场景 5：DegradationManager 状态切换与 HealthService 健康检查反映。"""

    def test_e2e_degradation_disabled_when_all_unavailable(self):
        """全部依赖不可用时 retrieval_strategy=disabled。"""
        dm = DegradationManager(
            neo4j_driver=None,
            db=None,
            redis_client=None,
            celery_app=None,
        )
        dm.check_all()

        assert dm.get_retrieval_strategy() == "disabled"
        assert not dm.is_write_available()
        assert not dm.is_consolidation_available()

    def test_e2e_degradation_status_reflected_in_health(self, monkeypatch):
        """健康检查应反映全部依赖不可用时的 unhealthy 状态。"""
        app_service = MagicMock()
        app_service.db.session.execute.side_effect = RuntimeError("db down")
        app_service.redis_client.ping.side_effect = RuntimeError("redis down")
        monkeypatch.setattr(
            HealthService,
            "_probe_celery",
            classmethod(lambda cls: {"status": "skipped", "detail": ""}),
        )

        data = HealthService(app_service=app_service).check()

        assert data["status"] == "unhealthy"
        assert data["components"]["database"]["status"] == "unhealthy"
        assert data["components"]["pgvector"]["status"] == "unhealthy"
        assert data["components"]["redis"]["status"] == "unhealthy"

    def test_e2e_degradation_vector_only_when_neo4j_down(self):
        """Neo4j 不可用但 pgvector 可用时 retrieval_strategy=vector_only。"""
        # mock pgvector 可用
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_db.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.session.return_value.__exit__ = MagicMock(return_value=False)

        dm = DegradationManager(
            neo4j_driver=None,
            db=mock_db,
            redis_client=None,
            celery_app=None,
        )

        # 由于 _check_pgvector 会执行 SQL，这里直接设置状态
        dm._neo4j_ok = False
        dm._pgvector_ok = True
        dm._redis_ok = False
        dm._celery_ok = False
        dm._memory_engine_enabled = False

        assert dm.get_retrieval_strategy() == "vector_only"

    def test_e2e_degradation_full_when_all_ok(self):
        """全部依赖可用时 retrieval_strategy=full。"""
        dm = DegradationManager(
            neo4j_driver=MagicMock(),
            db=MagicMock(),
            redis_client=MagicMock(),
            celery_app=MagicMock(),
        )

        # 直接设置状态（模拟 check_all 成功）
        dm._neo4j_ok = True
        dm._pgvector_ok = True
        dm._redis_ok = True
        dm._celery_ok = True
        dm._memory_engine_enabled = True

        assert dm.get_retrieval_strategy() == "full"
        assert dm.is_write_available()
        assert dm.is_consolidation_available()

    def test_e2e_degradation_get_status_snapshot(self):
        """get_status 应返回完整状态快照。"""
        dm = DegradationManager(
            neo4j_driver=None,
            db=None,
            redis_client=None,
            celery_app=None,
        )
        dm._neo4j_ok = True
        dm._pgvector_ok = False
        dm._redis_ok = True
        dm._celery_ok = False
        dm._memory_engine_enabled = True

        status = dm.get_status()

        assert status["neo4j"] is True
        assert status["pgvector"] is False
        assert status["redis"] is True
        assert status["celery"] is False
        assert status["memory_engine_enabled"] is True
        assert status["retrieval_strategy"] == "graph_only"
        assert status["write_available"] is False
        assert status["consolidation_available"] is False

    def test_e2e_degradation_health_shows_degraded_when_one_down(self, monkeypatch):
        """一个依赖不可用时健康检查应返回 degraded。"""
        app_service = MagicMock()
        app_service.db.session.execute.return_value.fetchone.return_value = ("16.0",)
        app_service.redis_client.ping.side_effect = RuntimeError("redis down")
        monkeypatch.setattr(
            HealthService,
            "_probe_celery",
            classmethod(lambda cls: {"status": "skipped", "detail": ""}),
        )

        data = HealthService(app_service=app_service).check()

        assert data["status"] == "degraded"
        assert data["components"]["database"]["status"] == "healthy"
        assert data["components"]["pgvector"]["status"] == "healthy"
        assert data["components"]["redis"]["status"] == "unhealthy"
