#!/usr/bin/env python
"""记忆系统「键值互补」一致性对账/清理脚本（第 4 步）。

不变式（收敛目标）：
    每个可召回记忆实体应有「一条 Neo4j Episode/MemoryNode 节点」与
    「一条 PG user_memory 投影行（embedding_node_id == Neo4j node_id）」。

本脚本只做「投影侧清理」，删除 PG 侧悬空/孤儿行：
- A 类：user_memory.embedding_node_id 非空，但 Neo4j 无该 node_id（投影指向不存在键）
- C 类：user_memory.embedding_node_id 为空，且 Neo4j 也无 user_memory.id 同名节点（纯 DB 孤儿）

不处理（留给后续写入契约步骤）：
- B 类：Neo4j 有节点但 PG 无投影行 → 需补向量，非删除
- agent_curated 缺向量分表行 → 需补写，非删除

用法：
    python internal/migration/memory_reconcile.py            # dry-run，只列出
    python internal/migration/memory_reconcile.py --apply    # 执行删除
"""

import argparse
import logging
import os
import sys

from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _env_database_uri() -> str:
    return os.getenv(
        "SQLALCHEMY_DATABASE_URI",
        "postgresql://yuxin_ai:yuxin_ai@localhost:5432/yuxin_ai",
    )


def _neo4j_params() -> dict:
    return {
        "uri": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        "user": os.getenv("NEO4J_USER", "neo4j"),
        "password": os.getenv("NEO4J_PASSWORD", "openagent123"),
    }


def _load_pg_rows(engine):
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, embedding_node_id FROM user_memory "
                "ORDER BY created_at"
            )
        ).all()
        return [
            {
                "id": str(r[0]),
                "embedding_node_id": (str(r[1]) if r[1] else "").strip(),
            }
            for r in rows
        ]


def _load_neo4j_node_ids(params) -> set[str]:
    try:
        from neo4j import GraphDatabase
    except ImportError:
        logger.error("neo4j driver 不可用，请安装 neo4j python 包")
        sys.exit(2)
    driver = GraphDatabase.driver(params["uri"], auth=(params["user"], params["password"]))
    node_ids: set[str] = set()
    try:
        with driver.session() as session:
            result = session.run(
                "MATCH (n) WHERE (n:Episode OR n:MemoryNode) AND n.node_id IS NOT NULL "
                "RETURN n.node_id AS node_id"
            )
            for record in result:
                value = record.get("node_id")
                if value:
                    node_ids.add(str(value))
    finally:
        driver.close()
    return node_ids


def main() -> int:
    parser = argparse.ArgumentParser(description="记忆投影一致性对账/清理")
    parser.add_argument("--apply", action="store_true", help="执行删除（默认仅 dry-run）")
    args = parser.parse_args()

    engine = create_engine(_env_database_uri())
    pg_rows = _load_pg_rows(engine)
    neo4j_ids = _load_neo4j_node_ids(_neo4j_params())

    logger.info("PG user_memory 行数: %d", len(pg_rows))
    logger.info("Neo4j Episode/MemoryNode node_id 数: %d", len(neo4j_ids))

    class_a: list[dict] = []  # embedding_node_id 指向不存在的图节点
    class_c: list[dict] = []  # 无 embedding_node_id 且图无同名节点
    for row in pg_rows:
        node_ref = row["embedding_node_id"]
        if node_ref:
            if node_ref not in neo4j_ids:
                class_a.append(row)
        else:
            # 回退：检查 Neo4j 是否有 user_memory.id 同名节点（agent_curated 半条）
            if row["id"] not in neo4j_ids:
                class_c.append(row)

    logger.info("A 类（投影悬空，DB 行指向不存在的图节点）: %d", len(class_a))
    for row in class_a[:50]:
        logger.info("  A id=%s embedding_node_id=%s", row["id"], row["embedding_node_id"])
    if len(class_a) > 50:
        logger.info("  ... 其余 %d 条略", len(class_a) - 50)

    logger.info("C 类（纯 DB 孤儿行，图无同名节点）: %d", len(class_c))
    for row in class_c[:50]:
        logger.info("  C id=%s", row["id"])
    if len(class_c) > 50:
        logger.info("  ... 其余 %d 条略", len(class_c) - 50)

    if not args.apply:
        logger.info("DRY-RUN：未删除任何数据。加 --apply 执行清理。")
        return 0

    doomed = class_a + class_c
    if not doomed:
        logger.info("无孤儿数据，无需清理。")
        return 0

    ids = [row["id"] for row in doomed]
    with engine.begin() as conn:
        # 向量分表靠 ON DELETE CASCADE 联动删除
        result = conn.execute(
            text(
                "DELETE FROM user_memory "
                "WHERE id IN (SELECT x::uuid FROM unnest(:ids) AS x)"
            ),
            {"ids": ids},
        )
        logger.info("已删除 user_memory 行: %d", result.rowcount)
    logger.info("清理完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
