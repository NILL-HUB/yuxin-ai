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
from datetime import UTC, datetime
from typing import Callable, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from internal.config.memory_settings import settings

logger = logging.getLogger(__name__)


class AuditEntry(BaseModel):
    """审计日志条目。"""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
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

    def soft_delete_memory(
        self,
        memory_id: str,
        owner_key: str,
        *,
        retention_days: int | None = None,
        agent_id=None,
    ) -> bool:
        """软删除记忆：设置 is_active=false，保留节点可恢复。

        软删前先进入平台回收站（快照完整数据，用户可在回收站恢复/到期销毁）；
        回收站入站失败不影响软删主流程（记忆仍可正常删除）。

        Args:
            memory_id: 记忆节点 ID
            owner_key: 记忆主体键（用户主体为裸 UUID，见 ``MemoryOwnerKey``）
            retention_days: 回收站留存天数（用户指定，默认 30 天）
            agent_id: agent 代理删除时的 agent 应用 ID

        Returns:
            True 成功，False 失败（权限校验失败或异常）
        """
        driver = self._get_driver()
        if driver is None:
            logger.warning("soft_delete_memory: Neo4j 不可用")
            return False

        try:
            # 权限校验
            if not self._verify_owner(memory_id, owner_key, driver):
                logger.warning("soft_delete_memory: 权限校验失败 memory=%s owner=%s", memory_id, owner_key)
                # _log_audit 的第二个形参是「审计操作者」语义，与记忆归属键 owner_key 不同域；
                # 用户主体下二者取值相同，按位置传入即可。
                self._log_audit("SOFT_DELETE_MEMORY", owner_key, memory_id=memory_id, success=False, reason="permission_denied")
                return False

            # 进入平台回收站（快照先于物理删除捕获）
            self._enter_recycle_bin(memory_id, owner_key, retention_days=retention_days, agent_id=agent_id)

            # Neo4j 软删除
            with driver.session() as session:
                session.run(
                    """
                    MATCH (n) WHERE (n:MemoryNode OR n:Episode OR n:Entity OR n:Community) AND (n.node_id = $memory_id OR n.id = $memory_id)
                    SET n.is_active = false,
                        n.deleted_at = datetime()
                    """,
                    memory_id=memory_id,
                ).consume()

            # pgvector 删除对应向量行
            self._delete_pgvector_row(memory_id)

            # Redis 清理缓存
            self._clear_user_cache(owner_key)

            self._log_audit("SOFT_DELETE_MEMORY", owner_key, memory_id=memory_id, success=True)
            return True
        except Exception:
            logger.error("soft_delete_memory: 执行失败 memory=%s", memory_id, exc_info=True)
            self._log_audit("SOFT_DELETE_MEMORY", owner_key, memory_id=memory_id, success=False, reason="exception")
            return False

    def _enter_recycle_bin(
        self,
        memory_id: str,
        owner_key: str,
        *,
        retention_days: int | None = None,
        agent_id=None,
    ) -> None:
        """把记忆软删记录写入平台回收站（best-effort，失败仅告警）。

        resource_name 取记忆内容前 50 字，便于回收站列表展示。
        """
        try:
            from internal.model.knowledge import UserMemory
            from internal.service.recycle_bin_service import RecycleBinService

            db = self._get_db()
            row = None
            if db is not None:
                # id 为 UUID 而 memory_id 可能为 Neo4j 节点 ID，分开查询避免类型比较异常
                row = (
                    db.session.query(UserMemory)
                    .filter(UserMemory.embedding_node_id == str(memory_id))
                    .one_or_none()
                )
                if row is None:
                    row = (
                        db.session.query(UserMemory)
                        .filter(UserMemory.id == memory_id)
                        .one_or_none()
                    )
            content = (row.content if row is not None and row.content else "") or ""
            resource_name = content[:50] if content else f"记忆 {memory_id}"

            RecycleBinService().delete_resource(
                resource_type="memory",
                resource_id=memory_id,
                resource_key=str(memory_id),
                resource_name=resource_name,
                deleted_by=str(owner_key),
                deleted_by_type="user",
                retention_days=retention_days,
                agent_id=agent_id,
            )
        except Exception:
            logger.warning(
                "记忆入回收站失败 memory=%s owner=%s（不影响软删）", memory_id, owner_key, exc_info=True,
            )

    # =========================================================
    # 彻底删除
    # =========================================================

    def hard_delete_memory(self, memory_id: str, owner_key: str) -> bool:
        """彻底删除记忆：DETACH DELETE 物理删除，不可恢复。

        Args:
            memory_id: 记忆节点 ID
            owner_key: 记忆主体键（用户主体为裸 UUID，见 ``MemoryOwnerKey``）

        Returns:
            True 成功，False 失败
        """
        driver = self._get_driver()
        if driver is None:
            logger.warning("hard_delete_memory: Neo4j 不可用")
            return False

        try:
            # 权限校验
            if not self._verify_owner(memory_id, owner_key, driver):
                logger.warning("hard_delete_memory: 权限校验失败 memory=%s owner=%s", memory_id, owner_key)
                self._log_audit("HARD_DELETE_MEMORY", owner_key, memory_id=memory_id, success=False, reason="permission_denied")
                return False

            # Neo4j 物理删除
            with driver.session() as session:
                session.run(
                    """
                    MATCH (n) WHERE (n:MemoryNode OR n:Episode OR n:Entity OR n:Community) AND (n.node_id = $memory_id OR n.id = $memory_id)
                    DETACH DELETE n
                    """,
                    memory_id=memory_id,
                ).consume()

            # pgvector 删除对应向量行
            self._delete_pgvector_row(memory_id)

            # Redis 清理缓存
            self._clear_user_cache(owner_key)

            self._log_audit("HARD_DELETE_MEMORY", owner_key, memory_id=memory_id, success=True)
            return True
        except Exception:
            logger.error("hard_delete_memory: 执行失败 memory=%s", memory_id, exc_info=True)
            self._log_audit("HARD_DELETE_MEMORY", owner_key, memory_id=memory_id, success=False, reason="exception")
            return False

    # =========================================================
    # 编辑（创建新节点 + 旧节点失效）
    # =========================================================

    def edit_memory(self, memory_id: str, owner_key: str, new_content: str) -> Optional[str]:
        """编辑记忆：创建新节点，旧节点失效并建立 SUPERSEDED_BY 关系。

        Args:
            memory_id: 旧记忆节点 ID
            owner_key: 记忆主体键（用户主体为裸 UUID，见 ``MemoryOwnerKey``）
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
            if not self._verify_owner(memory_id, owner_key, driver):
                logger.warning("edit_memory: 权限校验失败 memory=%s owner=%s", memory_id, owner_key)
                self._log_audit("EDIT_MEMORY", owner_key, memory_id=memory_id, success=False, reason="permission_denied")
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

            # pgvector 联动：删除旧投影行（向量分表 CASCADE），
            # 新投影行由写入方（MemoryWriteService）按 embedding_node_id 补写
            self._delete_pgvector_row(memory_id)

            # Redis 清理缓存
            self._clear_user_cache(owner_key)

            self._log_audit("EDIT_MEMORY", owner_key, memory_id=memory_id, success=True, details={"new_id": new_id})
            return new_id
        except Exception:
            logger.error("edit_memory: 执行失败 memory=%s", memory_id, exc_info=True)
            self._log_audit("EDIT_MEMORY", owner_key, memory_id=memory_id, success=False, reason="exception")
            return None

    # =========================================================
    # GDPR 级联删除
    # =========================================================

    def gdpr_delete(self, owner_key: str) -> dict:
        """GDPR 级联删除：Neo4j + pgvector + Redis 三处清理。

        冷存储归档对象（L3 Frozen 层）经统一存储后端落盘，由存储后端自身
        的生命周期管理，不在本方法的清理范围内。

        ADMIN-P3c-2：Neo4j 侧改走 ``MemoryOwnerKey`` 访问器产出的归属谓词，
        用户态与 admin / Agent 主体**均**被覆盖（管理员级 agent_id 为哨兵，
        由 ``neo4j_props()`` 统一产出）。

        Args:
            owner_key: 记忆主体键（见 ``MemoryOwnerKey``）

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

        # Neo4j 删除（按主体谓词匹配归属节点，含 admin）
        if driver is not None:
            try:
                from internal.entity.memory_owner_entity import MemoryOwnerKey

                owner = MemoryOwnerKey.parse(owner_key)
                where = owner.neo4j_filter_condition("n")
                with driver.session() as session:
                    result = session.run(
                        f"""
                        MATCH (n) WHERE {where}
                        OPTIONAL MATCH (n)-[r]-(m)
                        WITH collect(DISTINCT n) AS nodes, collect(DISTINCT r) AS rels
                        FOREACH (x IN nodes | DETACH DELETE x)
                        RETURN size(nodes) AS node_count, size(rels) AS edge_count
                        """,
                        {"owner_key": owner_key, **owner.neo4j_props()},
                    ).single()
                    if result:
                        stats["neo4j_nodes"] = result.get("node_count", 0)
                        stats["neo4j_edges"] = result.get("edge_count", 0)
            except Exception:
                logger.error("gdpr_delete: Neo4j 删除失败 owner=%s", owner_key, exc_info=True)

        # pgvector 删除
        try:
            stats["pgvector_rows"] = self._delete_all_pgvector_rows(owner_key)
        except Exception:
            logger.warning("gdpr_delete: pgvector 删除失败", exc_info=True)

        # Redis 清理
        try:
            stats["redis_keys"] = self._clear_all_user_cache(owner_key)
        except Exception:
            logger.warning("gdpr_delete: Redis 清理失败", exc_info=True)

        self._log_audit("GDPR_DELETE", owner_key, success=True, details=stats)
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

    def _verify_owner(self, memory_id: str, owner_key: str, driver) -> bool:
        """验证记忆节点 owner 是否为指定主体（按主体类型取对应归属属性）。

        ADMIN-P3c-2：用户态取 ``n.user_id``；admin 态取 ``n.admin_user_id``
        （+ ``agent_id`` 哨兵/真实 UUID）。谓词由 ``MemoryOwnerKey`` 访问器产出，
        与写入侧同源（P3b 属性级分离），不再对 admin 恒返回 False。
        主体键非法时 fail-closed（不查库，直接 False）。
        """
        from internal.entity.memory_owner_entity import MemoryOwnerKey

        try:
            owner = MemoryOwnerKey.parse(owner_key)
        except Exception:
            logger.warning("_verify_owner: 主体键非法 owner=%s", owner_key)
            return False

        try:
            where = owner.neo4j_filter_condition("n")
            with driver.session() as session:
                result = session.run(
                    f"""
                    MATCH (n) WHERE (n:MemoryNode OR n:Episode OR n:Entity OR n:Community)
                      AND (n.node_id = $memory_id OR n.id = $memory_id)
                      AND {where}
                    RETURN count(n) AS c
                    """,
                    {"memory_id": memory_id, **owner.neo4j_props()},
                ).single()
                return bool(result and result.get("c"))
        except Exception:
            logger.warning("_verify_owner: 查询失败", exc_info=True)
            return False

    def _delete_pgvector_row(self, memory_id: str) -> None:
        """删除与记忆节点对应的 user_memory 投影行与向量分表行。

        键值互补联动：治理层收到的 memory_id 是「图节点 id」（Neo4j 键）。
        系统路径投影行的 user_memory.id 是独立 uuid、embedding_node_id 才是
        图节点 id；agent_curated 路径两者相同。因此按 embedding_node_id 匹配
        优先，回退按 id 匹配，确保图删则投影行删（向量分表 CASCADE 联动）。

        Args:
            memory_id: 图节点 id（= user_memory.embedding_node_id）
        """
        db = self._get_db()
        if db is None:
            return
        try:
            from internal.model.knowledge import UserMemory

            # 优先按 embedding_node_id 匹配（图节点 id），回退按主键 id 匹配
            target = (
                db.session.query(UserMemory)
                .filter(UserMemory.embedding_node_id == str(memory_id))
                .first()
            )
            if target is None:
                target = (
                    db.session.query(UserMemory)
                    .filter(UserMemory.id == memory_id)
                    .first()
                )
            if target is not None:
                db.session.delete(target)
                db.session.commit()
        except Exception:
            logger.warning(
                "_delete_pgvector_row: 删除失败 memory=%s", memory_id, exc_info=True
            )
            db.session.rollback()

    def _delete_all_pgvector_rows(self, owner_key: str) -> int:
        """删除主体全部 pgvector 向量行，返回删除行数。

        ADMIN-P3c-2：改用 ``MemoryOwnerKey.pg_filter_conditions`` 产出的主体谓词
        （含 ``owner_type``）。此前只比 ``owner_account_id``——admin 主体该列为
        NULL，会**漏删 admin 记忆**（缺口二修复后 admin 行可落库，该漏删已从
        「无害 fail-safe」升级为「admin 记忆无法被 GDPR 删除」）。
        """
        from internal.entity.memory_owner_entity import MemoryOwnerKey
        from internal.model.knowledge import UserMemory

        db = self._get_db()
        if db is None:
            return 0
        try:
            owner = MemoryOwnerKey.parse(owner_key)
            conditions = owner.pg_filter_conditions(UserMemory)
            count = db.session.query(UserMemory).filter(*conditions).delete()
            db.session.commit()
            return count
        except Exception:
            logger.warning(
                "_delete_all_pgvector_rows: 删除失败 owner=%s", owner_key, exc_info=True
            )
            return 0

    def _clear_user_cache(self, owner_key: str) -> None:
        """清理主体相关 Redis 缓存。

        键必须与实际写入方同源（否则删不掉）：
        - ``memory:digest:{owner_key}`` ← ``DigestManager._cache_key``
          （前缀统一取 ``settings.digest.cache_key_prefix``，勿再硬编码）
        - ``skill:pool:{owner_key}``    ← ``DigestManager._fetch_skills``
        - ``skill:stats:{owner_key}``   ← ``SkillEmergence``（技能使用统计）
        注：``profile:`` 无写入方（画像走 Neo4j），已从白名单移除。
        """
        redis_client = self._get_redis()
        if redis_client is None:
            return
        try:
            keys = [
                f"{settings.digest.cache_key_prefix}{owner_key}",
                f"skill:pool:{owner_key}",
                f"skill:stats:{owner_key}",
            ]
            for key in keys:
                redis_client.delete(key)
        except Exception:
            logger.warning("_clear_user_cache: 清理失败 owner=%s", owner_key, exc_info=True)

    def _clear_all_user_cache(self, owner_key: str) -> int:
        """清理主体全部 Redis 缓存键，返回删除数量。

        ⚠️ 约定（P3c-3 缺口十）：新增含主体键的 Redis 键时，主体键**必须**以
        ``:`` 与前后缀分隔（如 ``prefix:{owner}`` / ``prefix:{owner}:suffix``），
        否则不会被本方法的两个通配模式命中，GDPR 清理将静默漏删。
        把主体混入哈希/摘要的键（如 ``schedule_suggestion:{md5}``）天然无法命中，
        需各自实现清理。
        """
        redis_client = self._get_redis()
        if redis_client is None:
            return 0
        try:
            keys = []
            patterns = [
                f"*:{owner_key}",       # 尾部为主体键（digest / skill:pool / skill:stats / nudge:prompt …）
                f"*:{owner_key}:*",     # 主体键在中间（nudge:stats:{owner}:{conv} / seed:{owner}:{name}）
                f"{settings.digest.cache_key_prefix}{owner_key}",
            ]
            for pattern in patterns:
                keys.extend(redis_client.keys(pattern))
            # 同一键可能被多个模式命中（如 digest 键同时匹配 *:{owner} 与精确前缀）；
            # delete 幂等，但 len() 会重复计数使 stats 偏大（缺口十一）——按序去重。
            keys = list(dict.fromkeys(keys))
            if keys:
                redis_client.delete(*keys)
            return len(keys)
        except Exception:
            logger.warning("_clear_all_user_cache: 清理失败 owner=%s", owner_key, exc_info=True)
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
