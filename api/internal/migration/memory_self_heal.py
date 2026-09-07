#!/usr/bin/env python
"""记忆系统「自愈式对账」脚本（B 类自动重建 + 幽灵用户清理）。

不变式（键值互补收敛目标）：
    每个可召回记忆实体 = 一条 Neo4j Episode 节点 + 一条 PG user_memory
    投影行（embedding_node_id == node_id），同生同灭。

本脚本在既有 memory_reconcile.py（清理 A/C 类孤儿）之上，补齐：
- B 类重建：Neo4j 有 active Episode 节点（带 content）且 user 仍存在，
  但 PG 无对应投影行 → 从图节点属性重建投影行 + 重算向量
- 幽灵用户清理：图节点归属的 account 已从 PG 删除（user_id 不存在）
  → 该用户记忆既无法建投影（外键）也无恢复意义，直接 DETACH DELETE，
  并把清理事件写入 audit_log 供 Admin 后台观测

重建策略（显式）：
    只重建「可召回记忆」：is_active<>false 且 status 非 superseded/deprecated
    且 t_invalidated_at 为空 且 content 非空 的 Episode 节点。
    Entity（无正文）、SemanticMemory（content 截断）不在此范围；
    inactive/失效节点不重建。

用法：
    python internal/migration/memory_self_heal.py              # dry-run 盘点
    python internal/migration/memory_self_heal.py --repair     # 执行 B 类重建
    python internal/migration/memory_self_heal.py --purge-ghosts  # 清理幽灵用户图节点
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from uuid import UUID

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


# =========================================================
# 只读盘点（无需 app context）
# =========================================================


def _load_pg_node_ids(engine) -> set[str]:
    """PG 侧所有非空 embedding_node_id。"""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT embedding_node_id FROM user_memory "
                "WHERE embedding_node_id IS NOT NULL AND embedding_node_id <> ''"
            )
        ).all()
        return {str(r[0]) for r in rows}


def _load_repairable_episodes(params: dict) -> list[dict]:
    """从 Neo4j 加载可重建的 Episode 节点（active + 有 content）。"""
    try:
        from neo4j import GraphDatabase
    except ImportError:
        logger.error("neo4j driver 不可用，请安装 neo4j python 包")
        sys.exit(2)

    driver = GraphDatabase.driver(
        params["uri"], auth=(params["user"], params["password"])
    )
    episodes: list[dict] = []
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (n:Episode)
                WHERE n.node_id IS NOT NULL
                  AND (n.is_active IS NULL OR n.is_active <> false)
                  AND (n.status IS NULL OR NOT (n.status IN ['superseded', 'deprecated']))
                  AND n.t_invalidated_at IS NULL
                  AND n.content IS NOT NULL
                  AND n.content <> ''
                  AND n.user_id IS NOT NULL
                  AND n.user_id <> ''
                RETURN n.node_id AS node_id,
                       n.user_id AS user_id,
                       n.content AS content,
                       n.summary AS summary,
                       n.memory_type AS memory_type,
                       n.source AS source,
                       n.created_at AS created_at,
                       n.session_id AS session_id
                """
            )
            for rec in result:
                episodes.append(
                    {
                        "node_id": str(rec["node_id"]),
                        "user_id": str(rec["user_id"] or ""),
                        "content": rec["content"] or "",
                        "summary": rec["summary"] or "",
                        "memory_type": rec["memory_type"] or "episode",
                        "source": rec["source"] or "",
                        "session_id": rec["session_id"] or "",
                    }
                )
    finally:
        driver.close()
    return episodes


def _load_valid_account_ids(engine) -> set[str]:
    """PG account 表存在的用户 id（幽灵用户节点无法建投影）。"""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id FROM account")).all()
        return {str(r[0]) for r in rows}


def _load_ghost_nodes(params: dict, valid_account_ids: set[str]) -> list[dict]:
    """加载幽灵用户的记忆类图节点（user_id 已不在 account 表）。

    覆盖所有带 user_id 的记忆节点标签：Episode / Entity / SemanticMemory
    （均含 :MemoryNode）与 Skill（仅 :Skill，可能被多账号 MERGE 共享，
    清理前校验该 skill 是否只归属这一个幽灵账号）。

    Returns:
        每项 {uid, labels: str, count: int}
    """
    try:
        from neo4j import GraphDatabase
    except ImportError:
        logger.error("neo4j driver 不可用，请安装 neo4j python 包")
        sys.exit(2)

    driver = GraphDatabase.driver(
        params["uri"], auth=(params["user"], params["password"])
    )
    ghosts: list[dict] = []
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (n)
                WHERE n.user_id IS NOT NULL AND n.user_id <> ''
                  AND (n:MemoryNode OR n:Episode OR n:Entity
                       OR n:SemanticMemory OR n:Skill)
                  AND NONE(x IN $valid WHERE x = n.user_id)
                RETURN n.user_id AS uid, labels(n) AS labels, count(*) AS cnt
                ORDER BY cnt DESC
                """,
                valid=list(valid_account_ids),
            )
            for rec in result:
                ghosts.append(
                    {
                        "uid": str(rec["uid"]),
                        "labels": sorted(str(x) for x in (rec["labels"] or [])),
                        "count": int(rec["cnt"]),
                    }
                )
    finally:
        driver.close()
    return ghosts


def _purge_ghost_nodes(
    params: dict,
    valid_account_ids: set[str],
) -> dict:
    """删除幽灵用户的记忆类图节点，返回统计。

    - Episode / Entity / SemanticMemory：这些标签都带 :MemoryNode 且为
      「用户私有」记忆（按 user_id 归属、用户消亡即无意义），直接按
      user_id DETACH DELETE。
    - Skill：不带 :MemoryNode，且按全局 skill_id MERGE 可能被多账号共享，
      不做自动删除（当前环境盘点无 Skill 残留；未来出现需专项评估）。

    Returns:
        {deleted_nodes, ghost_users}
    """
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        params["uri"], auth=(params["user"], params["password"])
    )
    stats = {"deleted_nodes": 0, "ghost_users": 0}
    ghost_users = _load_ghost_nodes(params, valid_account_ids)
    user_ids = sorted({g["uid"] for g in ghost_users})
    stats["ghost_users"] = len(user_ids)
    try:
        with driver.session() as session:
            for uid in user_ids:
                result = session.run(
                    """
                    MATCH (n)
                    WHERE n.user_id = $uid
                      AND (n:MemoryNode OR n:Episode OR n:Entity OR n:SemanticMemory)
                    DETACH DELETE n
                    RETURN count(*) AS cnt
                    """,
                    uid=uid,
                ).single()
                deleted = int(result["cnt"]) if result else 0
                stats["deleted_nodes"] += deleted
                logger.info(
                    "幽灵用户 %s：清理记忆节点 %d 个",
                    uid, deleted,
                )
    finally:
        driver.close()
    return stats


def _write_ghost_cleanup_audit(engine, stats: dict) -> None:
    """把幽灵清理事件写入 audit_log 表供 Admin 观测。

    独立脚本环境没有 Flask app context，直接用传入的 engine 直连写表。
    admin_user_id 传 NULL（系统定时清理，非管理员操作），
    action/resource_type 沿用记忆治理风格（audit_log:read 在 admin 可见）。
    """
    try:
        import json as _json

        after = {
            "deleted_nodes": stats["deleted_nodes"],
            "ghost_users": stats["ghost_users"],
            "trigger": "memory_self_heal",
        }
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO audit_log "
                    "(admin_user_id, account_id, action, resource_type, resource_id, "
                    " ip, user_agent, before_data, after_data, created_at) "
                    "VALUES (NULL, NULL, 'ghost_memory_cleanup', 'memory', '', "
                    " '', '', '{}'::jsonb, CAST(:after AS jsonb), CURRENT_TIMESTAMP(0))"
                ),
                {"after": _json.dumps(after, ensure_ascii=False)},
            )
        logger.info("幽灵清理审计已写入 audit_log")
    except Exception:
        logger.warning("幽灵清理审计写入失败（不影响清理结果）", exc_info=True)


def _is_valid_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, TypeError):
        return False


# =========================================================
# 重建执行（需要 Flask app context 取 db/embeddings）
# =========================================================


def _build_payload(node: dict) -> dict:
    """把图节点属性映射为 _upsert_vector 的 payload。"""
    source = node.get("source") or ""
    memory_type = node.get("memory_type") or "episode"
    # created_from：agent_curated 来源标记为 agent_curated，其余走 memory_system
    created_from = "agent_curated" if source == "agent_curated" else "memory_system"

    return {
        "content": node["content"],
        "event_type": memory_type,
        "memory_type": memory_type,
        "timestamp": "",  # 重建时以图 created_at 为准，但 _upsert_vector 不消费
        "user_id": node.get("user_id") or "",
        "node_id": node["node_id"],
        "session_id": node.get("session_id") or "",
        "source": source,
        "created_from": created_from,
        "rebuilt_by": "memory_self_heal",
    }


def _run_repair(nodes: list[dict]) -> dict:
    """进入 Flask app context 执行重建。返回统计。"""
    # 延迟 import：仅在 --repair 时加载应用
    from app.http.app import app as flask_app
    from internal.service.memory.ledger_writer import LedgerWriter

    stats = {"repaired": 0, "failed": 0, "skipped": []}
    with flask_app.app_context():
        from app.http.app import injector

        ledger_writer = injector.get(LedgerWriter)
        from internal.service.embeddings_service import EmbeddingsService

        embeddings_service = injector.get(EmbeddingsService)
        for node in nodes:
            content = node["content"]
            try:
                embedding = embeddings_service.embeddings.embed_query(content)
            except Exception:
                logger.warning(
                    "重建向量生成失败 node=%s", node["node_id"], exc_info=True
                )
                stats["failed"] += 1
                continue
            if not embedding:
                logger.warning("重建向量为空 node=%s", node["node_id"])
                stats["failed"] += 1
                continue

            payload = _build_payload(node)
            forced = None
            if payload["created_from"] == "agent_curated" and _is_valid_uuid(
                node["node_id"]
            ):
                forced = node["node_id"]

            mid = ledger_writer._upsert_vector(
                point_id=node["node_id"],
                vector=embedding,
                payload=payload,
                forced_memory_id=forced,
            )
            if mid:
                stats["repaired"] += 1
            else:
                stats["failed"] += 1
    return stats


# =========================================================
# 主入口
# =========================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="记忆系统自愈式对账：B 类自动重建 + 幽灵用户清理"
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="执行 B 类重建（图有 DB 无且 user 仍存在）",
    )
    parser.add_argument(
        "--purge-ghosts",
        action="store_true",
        help="清理幽灵用户的图节点（user_id 已不在 account 表）并写审计",
    )
    args = parser.parse_args()

    params = _neo4j_params()
    engine = create_engine(_env_database_uri())
    account_ids = _load_valid_account_ids(engine)

    # ===== 幽灵用户清理（独立动作，不依赖重建） =====
    ghost_nodes = _load_ghost_nodes(params, account_ids)
    ghost_uids = sorted({g["uid"] for g in ghost_nodes})
    ghost_total = sum(g["count"] for g in ghost_nodes)
    logger.info(
        "幽灵用户记忆节点：%d 个幽灵账号，共 %d 个节点（user_id 不在 account）",
        len(ghost_uids),
        ghost_total,
    )
    for uid in ghost_uids:
        uid_rows = [g for g in ghost_nodes if g["uid"] == uid]
        total = sum(g["count"] for g in uid_rows)
        logger.info("  ghost uid=%s cnt=%d", uid, total)

    if args.purge_ghosts:
        if not ghost_uids:
            logger.info("无幽灵节点，无需清理。")
        else:
            stats = _purge_ghost_nodes(params, account_ids)
            logger.info(
                "幽灵清理完成：用户 %d 个，删除节点 %d 个",
                stats["ghost_users"],
                stats["deleted_nodes"],
            )
            # 落审计（admin_user_id=NULL，供 Admin 观测）
            _write_ghost_cleanup_audit(engine, stats)
            # 清理后复盘点确认
            remain = _load_ghost_nodes(params, account_ids)
            logger.info("清理后剩余幽灵节点: %d", sum(g["count"] for g in remain))
        return 0

    # ===== B 类重建 =====
    pg_node_ids = _load_pg_node_ids(engine)
    episodes = _load_repairable_episodes(params)

    logger.info("PG 投影行(有 embedding_node_id): %d", len(pg_node_ids))
    logger.info("PG account 总数: %d", len(account_ids))
    logger.info("Neo4j active Episode(有 content): %d", len(episodes))

    missing = [
        node for node in episodes if node["node_id"] not in pg_node_ids
    ]
    # 幽灵用户：user 已不存在 → 无法建投影（外键），交由 --purge-ghosts 处理
    repairable = [
        node for node in missing if node["user_id"] in account_ids
    ]
    ghost_ep = [
        node for node in missing if node["user_id"] not in account_ids
    ]
    logger.info("B 类候选（active Episode 缺投影行）: %d", len(missing))
    logger.info("  可重建（user_id 存在于 account）: %d", len(repairable))
    logger.info(
        "  幽灵（user_id 不在 account，请用 --purge-ghosts 清理）: %d",
        len(ghost_ep),
    )
    for node in repairable[:50]:
        logger.info(
            "  B node=%s type=%s src=%s user=%s content=%r",
            node["node_id"],
            node["memory_type"],
            node["source"],
            (node["user_id"] or "")[:8],
            node["content"][:40],
        )
    if len(repairable) > 50:
        logger.info("  ... 其余 %d 条略", len(repairable) - 50)

    if not repairable:
        logger.info("无可重建 B 类节点。")
        return 0

    if not args.repair:
        logger.info(
            "DRY-RUN：未重建任何数据。加 --repair 执行 B 类自愈重建；"
            "加 --purge-ghosts 清理幽灵节点。"
        )
        return 0

    stats = _run_repair(repairable)
    logger.info(
        "重建完成：成功 %d，失败 %d。",
        stats["repaired"],
        stats["failed"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
