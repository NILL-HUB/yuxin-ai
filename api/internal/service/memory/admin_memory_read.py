"""管理端 Agent 记忆读服务（ADMIN-P4 T4）。

管理页需要「这个 Agent 记得什么」的只读视图：节点规模统计 + 最近片段 +
分页记忆列表。与 ``admin_memory_recall`` 一样，主体键一律走
``MemoryOwnerKey.for_admin(admin_user_id, agent_id=...)``——admin 没有
account，绝不能伪造 ``for_user``。

设计约束：
- 只读 + fail-open：Neo4j 不可用 / 查询异常一律返回空结构（页面上显示空态），
  绝不让管理页因记忆引擎故障而 500。
- 归属谓词由 ``MemoryOwnerKey.neo4j_filter_condition`` 产出（用户/admin 属性
  分离，互相不命中），参数由 ``neo4j_props()`` 绑定。
- 不提供任何写能力（写路径已在 P3c 记忆写入 / MemoryGovernor）。
"""
from __future__ import annotations

import logging
from uuid import UUID

logger = logging.getLogger(__name__)


class AdminMemoryReadService:
    """admin 记忆只读查询。

    Args:
        neo4j_driver: 显式注入的驱动（测试接缝）；缺省按
            ``current_app.extensions['neo4j']`` → ``neo4j_extension.get_driver()``
            懒加载。
    """

    def __init__(self, neo4j_driver=None) -> None:
        self._driver = neo4j_driver

    # ------------------------------------------------------------------
    # 驱动
    # ------------------------------------------------------------------

    def _get_driver(self):
        if self._driver is not None:
            return self._driver
        try:
            from internal.context import current_app

            driver = current_app.extensions.get("neo4j")
            if driver is not None:
                return driver
        except Exception:
            pass
        try:
            from internal.extension.neo4j_extension import get_driver

            return get_driver()
        except Exception:
            logger.warning("AdminMemoryReadService: 获取 Neo4j 驱动失败", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def memory_stats(
        self,
        *,
        admin_user_id: UUID,
        agent_id: UUID | None = None,
    ) -> dict:
        """返回该主体的记忆规模统计 + 最近片段抽样。

        Returns:
            ``{"total_nodes", "episodes", "skills", "recent_memories"}``；
            引擎不可用 / 异常时各项回落为零值。
        """
        result = {
            "total_nodes": 0,
            "episodes": 0,
            "skills": 0,
            "recent_memories": [],
        }
        driver = self._get_driver()
        if driver is None:
            return result

        from internal.entity.memory_owner_entity import MemoryOwnerKey

        owner = MemoryOwnerKey.for_admin(admin_user_id, agent_id=agent_id)
        where = owner.neo4j_filter_condition("n")
        props = owner.neo4j_props()
        try:
            with driver.session() as session:
                result["total_nodes"] = self._count(
                    session, f"MATCH (n) WHERE {where} RETURN count(n) AS total", props
                )
                result["episodes"] = self._count(
                    session,
                    f"MATCH (n:Episode) WHERE {where} RETURN count(n) AS total",
                    props,
                )
                result["skills"] = self._count(
                    session,
                    f"MATCH (n:Skill) WHERE {where} RETURN count(n) AS total",
                    props,
                )
                recent = session.run(
                    f"""
                    MATCH (n:Episode) WHERE {where}
                    RETURN n.node_id AS id, n.content AS content, n.created_at AS created_at
                    ORDER BY n.updated_at DESC
                    LIMIT 5
                    """,
                    **props,
                ).data()
                result["recent_memories"] = [
                    {
                        "id": rec.get("id", ""),
                        "content": rec.get("content", ""),
                        "created_at": rec.get("created_at"),
                    }
                    for rec in recent
                ]
        except Exception:
            logger.warning("memory_stats: 查询失败，返回空结构", exc_info=True)
        return result

    def list_memories(
        self,
        *,
        admin_user_id: UUID,
        agent_id: UUID | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """分页返回该主体的 Episode 记忆节点。

        Returns:
            ``{"items": [{id, title, content, updated_at}], "total": int}``；
            title 取节点 ``summary``（写入时为原文前 200 字符）。
        """
        page = max(int(page or 1), 1)
        page_size = max(int(page_size or 20), 1)
        skip = (page - 1) * page_size

        driver = self._get_driver()
        if driver is None:
            return {"items": [], "total": 0}

        from internal.entity.memory_owner_entity import MemoryOwnerKey

        owner = MemoryOwnerKey.for_admin(admin_user_id, agent_id=agent_id)
        where = owner.neo4j_filter_condition("n")
        props = owner.neo4j_props()
        try:
            with driver.session() as session:
                total = self._count(
                    session, f"MATCH (n:Episode) WHERE {where} RETURN count(n) AS total", props
                )
                records = session.run(
                    f"""
                    MATCH (n:Episode) WHERE {where}
                    RETURN n.node_id AS id, n.summary AS title, n.content AS content,
                           n.updated_at AS updated_at
                    ORDER BY n.updated_at DESC
                    SKIP $skip
                    LIMIT $limit
                    """,
                    **props,
                    skip=skip,
                    limit=page_size,
                ).data()
            items = [
                {
                    "id": rec.get("id", ""),
                    "title": rec.get("title", "") or "",
                    "content": rec.get("content", "") or "",
                    "updated_at": rec.get("updated_at"),
                }
                for rec in records
            ]
            return {"items": items, "total": total}
        except Exception:
            logger.warning("list_memories: 查询失败，返回空结构", exc_info=True)
            return {"items": [], "total": 0}

    @staticmethod
    def _count(session, cypher: str, props: dict) -> int:
        record = session.run(cypher, **props).single()
        if record is None:
            return 0
        return int(record.get("total", 0) or 0)
