"""图扩散激活（SpreadActivation）。

从起始节点沿边扩展发现间接关联，每跳衰减激活值。灵感来自认知科学扩散激活
理论（Collins & Loftus, 1975）。

提供 Cypher 多跳遍历与迭代回退两种实现，保证 APOC 不可用时仍可工作。

降级策略:
    - Neo4j 不可用时返回空列表
    - Cypher 多跳遍历失败时回退到迭代遍历

设计参考:
    docs/prd/memory-system/02-storage-and-retrieval.md §6.3
    docs/prd/memory-system/execution/03-track-b-storage-retrieval.md B4
"""

from __future__ import annotations

import logging
from typing import Optional

from internal.config.memory_settings import settings
from internal.model.memory_models import SpreadConfig

logger = logging.getLogger(__name__)


class SpreadActivation:
    """图扩散激活器。

    不使用 ``@inject``：无注入依赖，配置从 ``settings.spread`` 读取，
    Neo4j 驱动在 ``activate`` 时由调用方传入或从 current_app 获取。
    """

    def __init__(self, neo4j_driver=None, config: Optional[SpreadConfig] = None) -> None:
        """初始化扩散激活器。

        Args:
            neo4j_driver: Neo4j 驱动，None 时在 activate 时从 current_app 获取
            config: SpreadConfig 实例，None 时使用 settings.spread
        """
        self._driver = neo4j_driver
        self._config = config or settings.spread

    def activate(
        self,
        start_nodes: list[str],
        top_k: int = 20,
        owner_key: str = "",
    ) -> list[tuple[str, float]]:
        """从起始节点沿边扩展，返回激活值排序的 (node_id, activation) 列表。

        多跳遍历：从 start_nodes 出发，沿边扩展，每跳衰减 activation_decay。
        Cypher 失败时回退到迭代遍历。

        Args:
            start_nodes: 起始节点 ID 列表
            top_k: 返回最大数量
            owner_key: 记忆主体键（用户主体为裸 UUID，admin 为 ``admin:{uuid}``）；
                传空串时不加主体谓词（历史行为）。

        Returns:
            ``[(node_id, activation), ...]`` 按 activation 降序排列
        """
        if not start_nodes:
            return []

        top_k = min(top_k, self._config.top_k)
        driver = self._driver or self._get_driver()

        if driver is None:
            logger.warning("SpreadActivation.activate: Neo4j 不可用，返回空列表")
            return []

        try:
            return self._cypher_multi_hop(driver, start_nodes, top_k, owner_key=owner_key)
        except Exception:
            logger.warning(
                "SpreadActivation.activate: Cypher 多跳遍历失败，回退到迭代遍历",
                exc_info=True,
            )
            return self._fallback_iterative(driver, start_nodes, top_k, owner_key=owner_key)

    # =========================================================
    # Cypher 多跳遍历
    # =========================================================

    def _cypher_multi_hop(
        self,
        driver,
        start_nodes: list[str],
        top_k: int,
        owner_key: str = "",
    ) -> list[tuple[str, float]]:
        """使用 Cypher 多跳遍历实现扩散激活。

        为每跳生成独立 MATCH-WITH 阶段，每跳衰减因子 decay = activation_decay ** hop。
        用 UNION ALL 合并各跳结果。

        ADMIN-P3c-4（缺口一）：传 ``owner_key`` 时，起点与扩展节点均按主体谓词
        约束（不跨主体扩散）；缺省为空串时与历史行为逐字节等价（无谓词）。
        """
        owner_predicate = self._owner_predicate(owner_key)
        owner_binds = self._owner_binds(owner_key)
        max_hops = self._config.max_hops
        decay = self._config.activation_decay
        min_activation = self._config.min_activation

        # 构建每跳的 Cypher 片段
        hop_queries = []
        for hop in range(1, max_hops + 1):
            hop_decay = decay ** hop
            # 第 1 跳从 start_nodes 出发
            if hop == 1:
                query = f"""
                UNWIND $start_nodes AS start_id
                MATCH (s {{node_id: start_id}})-[r]->(t)
                WHERE t.node_id <> start_id
                  AND {owner_predicate.format(node="s")}
                  AND {owner_predicate.format(node="t")}
                WITH t.node_id AS node_id, {hop_decay} * coalesce(r.weight, 1.0) AS activation
                WHERE activation >= {min_activation}
                RETURN node_id, activation
                """
            else:
                # 后续跳从前一跳结果出发（用 APOC 或迭代实现）
                # 由于 Cypher 不易做递归，这里用变长路径替代
                query = f"""
                UNWIND $start_nodes AS start_id
                MATCH (s {{node_id: start_id}})-[r*{hop}]-(t)
                WHERE t.node_id <> start_id
                  AND {owner_predicate.format(node="s")}
                  AND {owner_predicate.format(node="t")}
                WITH t.node_id AS node_id,
                     {hop_decay} * reduce(w = 1.0, rel IN r | w * coalesce(rel.weight, 1.0)) AS activation
                WHERE activation >= {min_activation}
                RETURN node_id, activation
                """
            hop_queries.append(query)

        # UNION ALL 合并 + 用 CALL () {} 子查询包裹以支持后续聚合
        # Neo4j 5.x+ 推荐使用 CALL () { ... } 语法（CALL {} 已废弃）
        union_body = "\n UNION ALL \n".join(hop_queries)
        full_query = f"""
        CALL () {{
            {union_body}
        }}
        WITH node_id, max(activation) AS total_activation
        WHERE total_activation >= {min_activation}
        RETURN node_id, total_activation AS activation
        ORDER BY activation DESC
        LIMIT {top_k}
        """

        with driver.session() as session:
            result = session.run(full_query, {"start_nodes": start_nodes, **owner_binds})
            return [(record["node_id"], record["activation"]) for record in result]

    # =========================================================
    # 迭代回退遍历
    # =========================================================

    def _fallback_iterative(
        self,
        driver,
        start_nodes: list[str],
        top_k: int,
        owner_key: str = "",
    ) -> list[tuple[str, float]]:
        """Neo4j APOC/Cypher 多跳不可用时，用迭代遍历替代。

        逐跳循环，每跳查询出边，计算衰减后的激活值。

        ADMIN-P3c-4（缺口一）：``owner_key`` 透传给 ``_query_neighbors`` 做主体约束。
        """
        owner_binds = self._owner_binds(owner_key)
        max_hops = self._config.max_hops
        decay = self._config.activation_decay
        min_activation = self._config.min_activation

        # 初始化：起始节点激活值为 1.0
        current_frontier: list[tuple[str, float]] = [
            (nid, 1.0) for nid in start_nodes
        ]
        visited: set[str] = set(start_nodes)
        # 累积激活值（取最大值）
        activations: dict[str, float] = {nid: 1.0 for nid in start_nodes}

        for hop in range(1, max_hops + 1):
            if not current_frontier:
                break

            hop_decay = decay ** hop
            next_frontier: list[tuple[str, float]] = []

            for node_id, base_activation in current_frontier:
                try:
                    # 查询出边
                    neighbors = self._query_neighbors(driver, node_id, visited, owner_key=owner_key)
                    for neighbor_id, edge_weight in neighbors:
                        act = base_activation * float(edge_weight) * hop_decay
                        if act < min_activation:
                            continue
                        # 多路径激活取最大值
                        if neighbor_id not in activations or act > activations[neighbor_id]:
                            activations[neighbor_id] = act
                        if neighbor_id not in visited:
                            next_frontier.append((neighbor_id, act))
                            visited.add(neighbor_id)
                except Exception:
                    logger.warning(
                        "_fallback_iterative: 查询邻居失败 node_id=%s",
                        node_id,
                        exc_info=True,
                    )

            current_frontier = next_frontier

        # 移除起始节点本身，按 activation 降序排序
        result = [
            (nid, act)
            for nid, act in activations.items()
            if nid not in start_nodes and act >= min_activation
        ]
        result.sort(key=lambda x: x[1], reverse=True)
        return result[:top_k]

    def _query_neighbors(
        self,
        driver,
        node_id: str,
        visited: set[str],
        owner_key: str = "",
    ) -> list[tuple[str, float]]:
        """查询单个节点的出边邻居（同步 Neo4j session）。

        ADMIN-P3c-4（缺口一）：传 ``owner_key`` 时邻居按主体谓词约束。
        """
        owner_predicate = self._owner_predicate(owner_key)
        owner_binds = self._owner_binds(owner_key)
        cypher = f"""
        MATCH (s {{node_id: $node_id}})-[r]->(t)
        WHERE t.node_id IS NOT NULL AND t.node_id <> $node_id
          AND {owner_predicate.format(node="t")}
        RETURN t.node_id AS neighbor_id, coalesce(r.weight, 1.0) AS weight
        """
        with driver.session() as session:
            result = session.run(cypher, {"node_id": node_id, **owner_binds})
            neighbors = []
            for record in result:
                neighbor_id = record["neighbor_id"]
                if neighbor_id not in visited:
                    neighbors.append((neighbor_id, record["weight"]))
            return neighbors

    # =========================================================
    # 辅助
    # =========================================================

    def _owner_predicate(self, owner_key: str) -> str:
        """主体谓词模板（`{node}` 为占位符），缺省空串返回恒真条件。

        ADMIN-P3c-4（缺口一）：传 ``owner_key`` 时按主体约束，防止跨主体扩散；
        空串时返回 ``true``（不约束，与历史行为等价）。
        """
        if not owner_key:
            return "true"
        try:
            from internal.entity.memory_owner_entity import MemoryOwnerKey

            owner = MemoryOwnerKey.parse(owner_key)
            # 访问器以别名参数产出谓词；此处把别名替换为 `{node}` 占位符
            return owner.neo4j_filter_condition("{node}")
        except Exception:
            logger.warning("_owner_predicate: 主体键非法 owner=%s", owner_key, exc_info=True)
            return "true"

    def _owner_binds(self, owner_key: str) -> dict:
        """主体属性绑定，缺省空串返回空 dict。"""
        if not owner_key:
            return {}
        try:
            from internal.entity.memory_owner_entity import MemoryOwnerKey

            return dict(MemoryOwnerKey.parse(owner_key).neo4j_props())
        except Exception:
            logger.warning("_owner_binds: 主体键非法 owner=%s", owner_key, exc_info=True)
            return {}

    def _get_driver(self):
        """获取 Neo4j 驱动，不可用时返回 None。"""
        try:
            from internal.context import current_app

            driver = current_app.extensions.get("neo4j")
            if driver is not None:
                return driver
        except RuntimeError:
            pass
        try:
            from internal.extension.neo4j_extension import get_driver

            return get_driver()
        except Exception:
            logger.warning("_get_driver: 获取 Neo4j 驱动失败", exc_info=True)
            return None
