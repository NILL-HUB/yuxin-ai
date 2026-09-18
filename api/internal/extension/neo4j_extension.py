"""Neo4j 图数据库驱动初始化。

参照 redis_extension.py 模式：模块级单例 driver + init_app(app) 配置。
记忆系统 TKG（时序知识图谱）通过此驱动读写 Episode/Entity/Community 节点与边。
"""

import logging
from typing import Optional

from neo4j import GraphDatabase, Driver
from neo4j.exceptions import ServiceUnavailable

from internal.config.memory_settings import settings as memory_settings

logger = logging.getLogger(__name__)

# Neo4j 驱动（模块级单例，延迟初始化）
neo4j_driver: Optional[Driver] = None


def init_app(app) -> None:
    """初始化 Neo4j 驱动，挂载到 app.extensions。"""
    global neo4j_driver

    neo4j_config = memory_settings.neo4j
    try:
        neo4j_driver = GraphDatabase.driver(
            neo4j_config.uri,
            auth=(neo4j_config.user, neo4j_config.password),
        )
        # 连接验证
        neo4j_driver.verify_connectivity()
        logger.info("Neo4j 驱动初始化成功: %s", neo4j_config.uri)
    except ServiceUnavailable as e:
        logger.warning("Neo4j 连接失败，记忆系统图存储降级: %s", e)
        neo4j_driver = None
    except Exception as e:
        logger.warning("Neo4j 驱动初始化异常，记忆系统图存储降级: %s", e)
        neo4j_driver = None

    app.extensions["neo4j"] = neo4j_driver

    # 创建全文索引和约束（幂等，已存在则跳过）
    if neo4j_driver is not None:
        _ensure_constraints_and_indexes(neo4j_driver)


def _ensure_constraints_and_indexes(driver: Driver) -> None:
    """创建记忆系统所需的 Neo4j 约束与全文索引（幂等）。"""
    statements = [
        # node_id 唯一约束（Episode）
        "CREATE CONSTRAINT episode_node_id IF NOT EXISTS FOR (n:Episode) REQUIRE n.node_id IS UNIQUE",
        # node_id 唯一约束（Entity）
        "CREATE CONSTRAINT entity_node_id IF NOT EXISTS FOR (n:Entity) REQUIRE (n.name, n.user_id) IS UNIQUE",
        # 全文索引：覆盖 Episode/Entity/SemanticMemory 的 content 字段
        "CREATE FULLTEXT INDEX memoryFullText IF NOT EXISTS FOR (n:Episode) ON EACH [n.content, n.summary]",
        # ── admin 主体：属性级分离（用户端用 user_id，admin 端用 admin_user_id + agent_id）──
        # 唯一约束对「属性缺失」天然豁免，故加这些约束不影响存量 user 节点。
        "CREATE CONSTRAINT entity_name_admin_unique IF NOT EXISTS "
        "FOR (n:Entity) REQUIRE (n.name, n.admin_user_id, n.agent_id) IS UNIQUE",
        "CREATE CONSTRAINT community_key_admin_unique IF NOT EXISTS "
        "FOR (n:Community) REQUIRE (n.key, n.admin_user_id, n.agent_id) IS UNIQUE",
        "CREATE INDEX episode_admin_user_id_idx IF NOT EXISTS FOR (n:Episode) ON (n.admin_user_id)",
        "CREATE INDEX entity_admin_user_id_idx IF NOT EXISTS FOR (n:Entity) ON (n.admin_user_id)",
        "CREATE INDEX memorynode_admin_user_id_idx IF NOT EXISTS FOR (n:MemoryNode) ON (n.admin_user_id)",
        "CREATE INDEX community_admin_user_id_idx IF NOT EXISTS FOR (n:Community) ON (n.admin_user_id)",
    ]
    for stmt in statements:
        try:
            with driver.session() as session:
                session.run(stmt).consume()
            logger.info("Neo4j 索引/约束创建成功: %s", stmt[:60])
        except Exception as e:
            logger.warning("Neo4j 索引/约束创建失败（可能已存在）: %s", e)


def get_driver() -> Optional[Driver]:
    """获取 Neo4j 驱动单例（可能为 None，调用方需处理降级）。"""
    return neo4j_driver
