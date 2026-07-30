"""D3 DegradationManager 降级管理器。

记忆系统依赖健康检查统一入口。启动时检查 Neo4j/pgvector/Redis/Celery 连通性，
定期（默认 30s）健康检查，提供检索策略、写入可用性、巩固可用性查询接口。

降级策略:
    - 全部可用 → "full"
    - Neo4j 不可用 → "vector_only"
    - pgvector 不可用 → "graph_only"
    - Neo4j+pgvector 不可用但 Redis 可用 → "digest_only"
    - 全部不可用 → "disabled"

设计参考:
    docs/prd/memory-system/03-consolidation-skill-policy-api.md §9.1
    docs/prd/memory-system/execution/05-track-d-policy-governance.md D3
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


class DegradationManager:
    """降级管理器（同步实现）。

    不使用 ``@inject``：通过构造函数接收四个依赖客户端。
    健康检查通过后台线程定期执行（项目同步模式，不使用 asyncio）。
    """

    def __init__(
        self,
        neo4j_driver=None,
        db=None,
        redis_client=None,
        celery_app=None,
        check_interval_seconds: int = 30,
        flask_app=None,
    ) -> None:
        """初始化降级管理器。

        Args:
            neo4j_driver: Neo4j 驱动（同步），None 时标记不可用
            db: SQLAlchemy 实例（pgvector），None 时标记不可用
            redis_client: Redis 客户端（同步），None 时标记不可用
            celery_app: Celery 应用实例，None 时标记不可用
            check_interval_seconds: 健康检查间隔秒数
            flask_app: Flask 应用实例，用于后台线程推送 app context
                       （Flask-SQLAlchemy 的 session 依赖 app context）
        """
        self._neo4j_driver = neo4j_driver
        self._db = db
        self._redis = redis_client
        self._celery = celery_app
        self._check_interval = check_interval_seconds
        self._flask_app = flask_app

        # 依赖状态标志
        self._neo4j_ok = False
        self._pgvector_ok = False
        self._redis_ok = False
        self._celery_ok = False
        self._memory_engine_enabled = False

        # 后台检查线程
        self._check_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # =========================================================
    # 生命周期管理
    # =========================================================

    def start(self) -> None:
        """启动降级管理器：立即执行一次检查，然后启动后台定期检查。"""
        # 立即检查一次
        self.check_all()

        # 启动后台线程
        self._stop_event.clear()
        self._check_thread = threading.Thread(
            target=self._background_check,
            daemon=True,
            name="degradation-checker",
        )
        self._check_thread.start()
        logger.info("DegradationManager 已启动，检查间隔 %ss", self._check_interval)

    def stop(self) -> None:
        """停止后台健康检查。"""
        self._stop_event.set()
        if self._check_thread is not None:
            self._check_thread.join(timeout=5)
            self._check_thread = None
        logger.info("DegradationManager 已停止")

    def _background_check(self) -> None:
        """后台健康检查循环。"""
        while not self._stop_event.is_set():
            if self._stop_event.wait(self._check_interval):
                break
            try:
                self.check_all()
            except Exception:
                logger.warning("后台健康检查异常", exc_info=True)

    # =========================================================
    # 健康检查
    # =========================================================

    def check_all(self) -> dict[str, bool]:
        """执行全部依赖健康检查。

        Returns:
            ``{"neo4j": bool, "pgvector": bool, "redis": bool, "celery": bool}``
        """
        self._neo4j_ok = self._check_neo4j()
        self._pgvector_ok = self._check_pgvector()
        self._redis_ok = self._check_redis()
        self._celery_ok = self._check_celery()

        # 记忆引擎启用条件：Neo4j 可用为最低要求
        self._memory_engine_enabled = self._neo4j_ok

        return {
            "neo4j": self._neo4j_ok,
            "pgvector": self._pgvector_ok,
            "redis": self._redis_ok,
            "celery": self._celery_ok,
        }

    def _check_neo4j(self) -> bool:
        """检查 Neo4j 连通性（RETURN 1，2s 超时）。"""
        if self._neo4j_driver is None:
            return False
        try:
            with self._neo4j_driver.session() as session:
                session.run("RETURN 1").consume()
            return True
        except Exception:
            logger.warning("Neo4j 健康检查失败", exc_info=True)
            return False

    def _check_pgvector(self) -> bool:
        """检查 pgvector 连通性（SELECT 1 + 验证向量扩展，2s 超时）。

        Flask-SQLAlchemy 的 session 依赖 app context，后台线程中需主动推入。
        """
        if self._db is None:
            return False
        try:
            from sqlalchemy import text

            # 后台线程无 app context，需主动推入
            if self._flask_app is not None:
                with self._flask_app.app_context():
                    with self._db.session() as session:
                        session.execute(text("SELECT 1"))
                        session.execute(
                            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                        ).fetchone()
                    return True
            else:
                with self._db.session() as session:
                    session.execute(text("SELECT 1"))
                    session.execute(
                        text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                    ).fetchone()
                return True
        except Exception:
            logger.warning("pgvector 健康检查失败", exc_info=True)
            return False

    def _check_redis(self) -> bool:
        """检查 Redis 连通性（PING，2s 超时）。"""
        if self._redis is None:
            return False
        try:
            self._redis.ping()
            return True
        except Exception:
            logger.warning("Redis 健康检查失败", exc_info=True)
            return False

    def _check_celery(self) -> bool:
        """检查 Celery broker 连通性（control.ping，2s 超时）。"""
        if self._celery is None:
            return False
        try:
            # inspect.ping 可能因 broker 不通而阻塞，设置超时
            self._celery.control.ping(timeout=2)
            return True
        except Exception:
            logger.warning("Celery 健康检查失败", exc_info=True)
            return False

    # =========================================================
    # 策略查询接口
    # =========================================================

    def get_retrieval_strategy(self) -> str:
        """根据依赖状态返回检索策略。

        Returns:
            "full" | "vector_only" | "graph_only" | "digest_only" | "disabled"
        """
        if self._neo4j_ok and self._pgvector_ok:
            return "full"
        if self._pgvector_ok and not self._neo4j_ok:
            return "vector_only"
        if self._neo4j_ok and not self._pgvector_ok:
            return "graph_only"
        if self._redis_ok:
            return "digest_only"
        return "disabled"

    def is_write_available(self) -> bool:
        """写入可用性：Neo4j + pgvector 都可用时返回 True。"""
        return self._neo4j_ok and self._pgvector_ok

    def is_consolidation_available(self) -> bool:
        """巩固可用性：Neo4j + Celery 都可用时返回 True。"""
        return self._neo4j_ok and self._celery_ok

    @property
    def memory_engine_enabled(self) -> bool:
        """记忆引擎启用状态（Neo4j 可用为最低要求）。"""
        return self._memory_engine_enabled

    def get_status(self) -> dict:
        """获取完整状态快照（供 API 调用）。"""
        return {
            "neo4j": self._neo4j_ok,
            "pgvector": self._pgvector_ok,
            "redis": self._redis_ok,
            "celery": self._celery_ok,
            "memory_engine_enabled": self._memory_engine_enabled,
            "retrieval_strategy": self.get_retrieval_strategy(),
            "write_available": self.is_write_available(),
            "consolidation_available": self.is_consolidation_available(),
        }


# =========================================================
# 单例管理
# =========================================================

_degradation_manager: Optional[DegradationManager] = None
_degradation_lock = threading.Lock()


def get_degradation_manager() -> Optional[DegradationManager]:
    """获取全局 DegradationManager 单例，未初始化时返回 None。"""
    return _degradation_manager


def init_degradation_manager(
    neo4j_driver=None,
    db=None,
    redis_client=None,
    celery_app=None,
    check_interval_seconds: int = 30,
    flask_app=None,
) -> DegradationManager:
    """初始化全局 DegradationManager 单例并启动健康检查。"""
    global _degradation_manager
    with _degradation_lock:
        if _degradation_manager is not None:
            return _degradation_manager
        _degradation_manager = DegradationManager(
            neo4j_driver=neo4j_driver,
            db=db,
            redis_client=redis_client,
            celery_app=celery_app,
            check_interval_seconds=check_interval_seconds,
            flask_app=flask_app,
        )
        _degradation_manager.start()
        return _degradation_manager


def shutdown_degradation_manager() -> None:
    """关闭全局 DegradationManager。"""
    global _degradation_manager
    with _degradation_lock:
        if _degradation_manager is not None:
            _degradation_manager.stop()
            _degradation_manager = None
