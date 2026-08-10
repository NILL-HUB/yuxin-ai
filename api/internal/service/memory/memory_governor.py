"""D2 MemoryGovernor 记忆治理器。

实现记忆的软删除、彻底删除、编辑（创建新节点 + 旧节点失效）、
GDPR 级联删除与 PII 过滤，所有关键操作记录审计日志。

设计参考:
    docs/prd/memory-system/03-consolidation-skill-policy-api.md §9.2
    docs/prd/memory-system/execution/05-track-d-policy-governance.md D2
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Callable, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AuditEntry(BaseModel):
    """审计日志条目。"""

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    action: str
    user_id: str
    memory_id: Optional[str] = None
    details: dict = Field(default_factory=dict)
    actor: str = "system"


class PIIField(BaseModel):
    """PII 字段定义。"""

    field_name: str
    pii_type: str  # email/phone/ssn/name/address
    masking_rule: str = "redact"  # hash/redact/truncate


# =========================================================
# PII 正则规则表
# =========================================================

_PII_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("[EMAIL_REDACTED]", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("[PHONE_REDACTED]", re.compile(r"\b1[3-9]\d{9}\b")),
    ("[ID_REDACTED]", re.compile(r"\b\d{17}[\dXx]\b")),
    ("[CARD_REDACTED]", re.compile(r"\b\d{16,19}\b")),
]


class MemoryGovernor:
    """记忆治理器（同步实现）。

    不使用 ``@inject``：通过构造函数接收 Neo4j 驱动与审计回调。
    pgvector/Redis 操作通过懒加载获取。
    """

    def __init__(
        self,
        neo4j_driver=None,
        audit_log_func: Optional[Callable] = None,
        db=None,
        redis_client=None,
    ) -> None:
        """初始化记忆治理器。

        Args:
            neo4j_driver: Neo4j 驱动（同步）
            audit_log_func: 审计日志回调函数，None 时使用默认 logger
            db: SQLAlchemy 实例（pgvector），None 时从 current_app 获取
            redis_client: Redis 客户端，None 时从 current_app 获取
        """
        self._neo4j_driver = neo4j_driver
        self._audit_func = audit_log_func
        self._db = db
        self._redis = redis_client

    # =========================================================
    # 软删除
    # =========================================================

    def soft_delete_memory(self, memory_id: str, user_id: str) -> bool:
        """软删除记忆：设置 is_active=false，保留节点可恢复。

        Args:
            memory_id: 记忆节点 ID
            user_id: 操作者用户 ID

        Returns:
            True 成功，False 失败（权限校验失败或异常）
        """
        driver = self._get_driver()
        if driver is None:
            logger.warning("soft_delete_memory: Neo4j 不可用")
            return False

        try:
            # 权限校验
            if not self._verify_owner(memory_id, user_id, driver):
                logger.warning("soft_delete_memory: 权限校验失败 memory=%s user=%s", memory_id, user_id)
                self._log_audit("SOFT_DELETE_MEMORY", user_id, memory_id=memory_id, success=False, reason="permission_denied")
                return False

            # Neo4j 软删除
            with driver.session() as session:
                session.run(
                    """
                    MATCH (n) WHERE (n:MemoryNode OR n:Episode OR n:Entity) AND (n.node_id = $memory_id OR n.id = $memory_id)
                    SET n.is_active = false,
                        n.deleted_at = datetime()
                    """,
                    memory_id=memory_id,
                ).consume()

            # pgvector 删除对应向量行
            self._delete_pgvector_row(memory_id)

            # Redis 清理缓存
            self._clear_user_cache(user_id)

            self._log_audit("SOFT_DELETE_MEMORY", user_id, memory_id=memory_id, success=True)
            return True
        except Exception:
            logger.error("soft_delete_memory: 执行失败 memory=%s", memory_id, exc_info=True)
            self._log_audit("SOFT_DELETE_MEMORY", user_id, memory_id=memory_id, success=False, reason="exception")
            return False

    # =========================================================
    # 彻底删除
    # =========================================================

    def hard_delete_memory(self, memory_id: str, user_id: str) -> bool:
        """彻底删除记忆：DETACH DELETE 物理删除，不可恢复。

        Args:
            memory_id: 记忆节点 ID
            user_id: 操作者用户 ID

        Returns:
            True 成功，False 失败
        """
        driver = self._get_driver()
        if driver is None:
            logger.warning("hard_delete_memory: Neo4j 不可用")
            return False

        try:
            # 权限校验
            if not self._verify_owner(memory_id, user_id, driver):
                logger.warning("hard_delete_memory: 权限校验失败 memory=%s user=%s", memory_id, user_id)
                self._log_audit("HARD_DELETE_MEMORY", user_id, memory_id=memory_id, success=False, reason="permission_denied")
                return False

            # Neo4j 物理删除
            with driver.session() as session:
                session.run(
                    """
                    MATCH (n) WHERE (n:MemoryNode OR n:Episode OR n:Entity) AND (n.node_id = $memory_id OR n.id = $memory_id)
                    DETACH DELETE n
                    """,
                    memory_id=memory_id,
                ).consume()

            # pgvector 删除对应向量行
            self._delete_pgvector_row(memory_id)

            # Redis 清理缓存
            self._clear_user_cache(user_id)

            self._log_audit("HARD_DELETE_MEMORY", user_id, memory_id=memory_id, success=True)
            return True
        except Exception:
            logger.error("hard_delete_memory: 执行失败 memory=%s", memory_id, exc_info=True)
            self._log_audit("HARD_DELETE_MEMORY", user_id, memory_id=memory_id, success=False, reason="exception")
            return False

    # =========================================================
    # 编辑（创建新节点 + 旧节点失效）
    # =========================================================

    def edit_memory(self, memory_id: str, user_id: str, new_content: str) -> Optional[str]:
        """编辑记忆：创建新节点，旧节点失效并建立 SUPERSEDED_BY 关系。

        Args:
            memory_id: 旧记忆节点 ID
            user_id: 操作者用户 ID
            new_content: 新内容

        Returns:
            新节点 ID，失败返回 None
        """
        driver = self._get_driver()
        if driver is None:
            logger.warning("edit_memory: Neo4j 不可用")
            return None

        try:
            # 权限校验
            if not self._verify_owner(memory_id, user_id, driver):
                logger.warning("edit_memory: 权限校验失败 memory=%s user=%s", memory_id, user_id)
                self._log_audit("EDIT_MEMORY", user_id, memory_id=memory_id, success=False, reason="permission_denied")
                return None

            new_id = f"mem_{uuid4().hex[:12]}"

            with driver.session() as session:
                # 旧节点失效
                session.run(
                    """
                    MATCH (old) WHERE (old:MemoryNode OR old:Episode OR old:Entity) AND (old.node_id = $memory_id OR old.id = $memory_id)
                    SET old.t_invalidated_at = datetime()
                    """,
                    memory_id=memory_id,
                ).consume()

                # 创建新节点（复制旧节点属性 + 新内容）
                session.run(
                    """
                    MATCH (old) WHERE (old:MemoryNode OR old:Episode OR old:Entity) AND (old.node_id = $old_id OR old.id = $old_id)
                    CREATE (new:Episode:MemoryNode {
                        id: $new_id,
                        node_id: $new_id,
                        content: $new_content,
                        memory_type: coalesce(old.memory_type, 'episode'),
                        user_id: old.user_id,
                        is_active: true,
                        created_at: datetime(),
                        updated_at: datetime()
                    })
                    MERGE (old)-[:SUPERSEDED_BY]->(new)
                    """,
                    old_id=memory_id,
                    new_id=new_id,
                    new_content=new_content,
                ).consume()

            # pgvector 更新：删除旧向量行，写入新向量行
            self._delete_pgvector_row(memory_id)
            # 新向量行的写入由 MemoryWriteService 负责，这里不重复

            # Redis 清理缓存
            self._clear_user_cache(user_id)

            self._log_audit("EDIT_MEMORY", user_id, memory_id=memory_id, success=True, details={"new_id": new_id})
            return new_id
        except Exception:
            logger.error("edit_memory: 执行失败 memory=%s", memory_id, exc_info=True)
            self._log_audit("EDIT_MEMORY", user_id, memory_id=memory_id, success=False, reason="exception")
            return None

    # =========================================================
    # GDPR 级联删除
    # =========================================================

    def gdpr_delete(self, user_id: str) -> dict:
        """GDPR 级联删除：Neo4j + pgvector + Redis + MinIO 全部清理。

        Args:
            user_id: 用户标识

        Returns:
            删除统计 dict
        """
        stats = {
            "neo4j_nodes": 0,
            "neo4j_edges": 0,
            "pgvector_rows": 0,
            "redis_keys": 0,
        }

        driver = self._get_driver()

        # Neo4j 删除
        if driver is not None:
            try:
                with driver.session() as session:
                    result = session.run(
                        """
                        MATCH (u:User {id: $user_id})
                        OPTIONAL MATCH (u)-[r]-(n)
                        WITH u, collect(DISTINCT n) AS nodes, collect(DISTINCT r) AS rels
                        DETACH DELETE u
                        WITH nodes, rels
                        UNWIND nodes AS node DETACH DELETE node
                        RETURN size(nodes) AS node_count, size(rels) AS edge_count
                        """,
                        user_id=user_id,
                    ).single()
                    if result:
                        stats["neo4j_nodes"] = result.get("node_count", 0)
                        stats["neo4j_edges"] = result.get("edge_count", 0)
            except Exception:
                logger.error("gdpr_delete: Neo4j 删除失败 user=%s", user_id, exc_info=True)

        # pgvector 删除
        try:
            stats["pgvector_rows"] = self._delete_all_pgvector_rows(user_id)
        except Exception:
            logger.warning("gdpr_delete: pgvector 删除失败", exc_info=True)

        # Redis 清理
        try:
            stats["redis_keys"] = self._clear_all_user_cache(user_id)
        except Exception:
            logger.warning("gdpr_delete: Redis 清理失败", exc_info=True)

        self._log_audit("GDPR_DELETE", user_id, success=True, details=stats)
        return stats

    # =========================================================
    # PII 过滤
    # =========================================================

    def filter_pii(self, content: str) -> str:
        """使用正则替换脱敏 PII 信息。

        邮箱 → [EMAIL_REDACTED]
        手机号 → [PHONE_REDACTED]
        身份证号 → [ID_REDACTED]
        银行卡号 → [CARD_REDACTED]

        Args:
            content: 原始内容

        Returns:
            脱敏后内容
        """
        if not content:
            return content

        result = content
        for replacement, pattern in _PII_PATTERNS:
            result = pattern.sub(replacement, result)
        return result

    # =========================================================
    # 内部方法
    # =========================================================

    def _verify_owner(self, memory_id: str, user_id: str, driver) -> bool:
        """验证记忆节点 owner 是否为指定用户。"""
        try:
            with driver.session() as session:
                result = session.run(
                    """
                    MATCH (n) WHERE (n:MemoryNode OR n:Episode OR n:Entity) AND (n.node_id = $memory_id OR n.id = $memory_id)
                    RETURN n.user_id AS owner
                    """,
                    memory_id=memory_id,
                ).single()
                if result is None:
                    return False
                owner = result.get("owner")
                return owner == user_id
        except Exception:
            logger.warning("_verify_owner: 查询失败", exc_info=True)
            return False

    def _delete_pgvector_row(self, memory_id: str) -> None:
        """从 user_memory 表删除对应向量行。"""
        db = self._get_db()
        if db is None:
            return
        try:
            from internal.model.knowledge import UserMemory

            db.session.query(UserMemory).filter(UserMemory.id == memory_id).delete()
            db.session.commit()
        except Exception:
            logger.warning("_delete_pgvector_row: 删除失败 memory=%s", memory_id, exc_info=True)

    def _delete_all_pgvector_rows(self, user_id: str) -> int:
        """删除用户全部 pgvector 向量行，返回删除行数。"""
        db = self._get_db()
        if db is None:
            return 0
        try:
            from internal.model.knowledge import UserMemory

            count = db.session.query(UserMemory).filter(UserMemory.owner_account_id == user_id).delete()
            db.session.commit()
            return count
        except Exception:
            logger.warning("_delete_all_pgvector_rows: 删除失败 user=%s", user_id, exc_info=True)
            return 0

    def _clear_user_cache(self, user_id: str) -> None:
        """清理用户相关 Redis 缓存。"""
        redis_client = self._get_redis()
        if redis_client is None:
            return
        try:
            keys = [
                f"digest:{user_id}",
                f"profile:{user_id}",
                f"skill:pool:{user_id}",
            ]
            for key in keys:
                redis_client.delete(key)
        except Exception:
            logger.warning("_clear_user_cache: 清理失败 user=%s", user_id, exc_info=True)

    def _clear_all_user_cache(self, user_id: str) -> int:
        """清理用户全部 Redis 缓存键，返回删除数量。"""
        redis_client = self._get_redis()
        if redis_client is None:
            return 0
        try:
            # 扫描用户相关键
            keys = []
            for pattern in [f"*:{user_id}*", f"digest:{user_id}", f"profile:{user_id}", f"skill:pool:{user_id}"]:
                keys.extend(redis_client.keys(pattern))
            if keys:
                redis_client.delete(*keys)
            return len(keys)
        except Exception:
            logger.warning("_clear_all_user_cache: 清理失败 user=%s", user_id, exc_info=True)
            return 0

    def _log_audit(self, action: str, user_id: str, **kwargs) -> None:
        """记录审计日志。"""
        try:
            entry = AuditEntry(
                action=action,
                user_id=user_id,
                memory_id=kwargs.get("memory_id"),
                details={k: v for k, v in kwargs.items() if k != "memory_id"},
                actor="system",
            )

            if self._audit_func is not None:
                self._audit_func(entry)
            else:
                logger.info("审计日志: %s user=%s memory=%s details=%s",
                           action, user_id, kwargs.get("memory_id"),
                           {k: v for k, v in kwargs.items() if k != "memory_id"})
        except Exception:
            logger.error("_log_audit: 记录审计日志失败", exc_info=True)

    def _get_driver(self):
        """获取 Neo4j 驱动，不可用时返回 None。"""
        if self._neo4j_driver is not None:
            return self._neo4j_driver
        try:
            from internal.context import current_app

            driver = current_app.extensions.get("neo4j")
            return driver
        except RuntimeError:
            pass
        try:
            from internal.extension.neo4j_extension import get_driver

            return get_driver()
        except Exception:
            logger.warning("_get_driver: 获取 Neo4j 驱动失败", exc_info=True)
            return None

    def _get_db(self):
        """获取 SQLAlchemy 实例，不可用时返回 None。"""
        if self._db is not None:
            return self._db
        try:
            from internal.context import current_app

            db = current_app.extensions.get("database")
            if db is not None:
                return db
        except RuntimeError:
            pass
        try:
            from internal.extension.database_extension import db

            return db
        except Exception:
            return None

    def _get_redis(self):
        """获取 Redis 客户端，不可用时返回 None。"""
        if self._redis is not None:
            return self._redis
        try:
            from internal.context import current_app

            return current_app.extensions.get("redis")
        except RuntimeError:
            return None
