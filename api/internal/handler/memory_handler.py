"""记忆系统 API 端点 Handler。

提供以下端点：
    - ``POST /memory/write``         写入一条记忆（A4）
    - ``POST /memory/retrieve``      混合检索记忆（B7）
    - ``GET  /memory/digest/<uid>``  获取记忆摘要（B7）
    - ``POST /memory/consolidate/<uid>``  手动触发巩固（C5）

内部委托对应服务完成实际逻辑。
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from flask import request
from flask_login import current_user, login_required
from injector import inject

from internal.model.memory_models import RetrievalOptions
from internal.schema.memory_schema import (
    ConsolidationResp,
    MemoryDigestResp,
    MemoryRetrieveReq,
    MemoryRetrieveResp,
    MemoryWriteReq,
    MemoryWriteResp,
    EditMemoryReq,
    DecayReq,
    GraphResp,
    ClusterSubgraphResp,
    MemoryDetailResp,
    SkillListResp,
)
from internal.service.memory.consolidation_engine import ConsolidationEngine
from internal.service.memory.degradation_manager import get_degradation_manager
from internal.service.memory.digest_manager import DigestManager
from internal.service.memory.funnel_compressor import FunnelCompressor
from internal.service.memory.memory_write_service import MemoryWriteService
from internal.service.memory.retriever import MemoryRetriever
from pkg.response import success_json, validate_error_json

logger = logging.getLogger(__name__)

# 记忆系统版本号与服务启动时间（供 /memory/health 使用）
MEMORY_SYSTEM_VERSION = "1.0.0"
_SERVICE_START_TIME = time.time()


def _neo4j_to_json_safe(value):
    """将 Neo4j 返回的值递归转为 JSON 可序列化的 Python 原生类型。

    Neo4j Node/Relationship 含有 DateTime 等自定义类型，直接 jsonify 会抛
    TypeError 导致 500。此函数做防御性转换，确保所有值可被 Flask jsonify 序列化。
    """
    # Neo4j Node / Relationship：有 items() 方法的对象转为 dict
    if hasattr(value, "items") and callable(value.items):
        return {k: _neo4j_to_json_safe(v) for k, v in value.items()}
    # Neo4j DateTime / Python datetime：有 isoformat 方法
    if hasattr(value, "isoformat") and callable(value.isoformat):
        return value.isoformat()
    # 列表/元组
    if isinstance(value, (list, tuple)):
        return [_neo4j_to_json_safe(v) for v in value]
    # dict
    if isinstance(value, dict):
        return {k: _neo4j_to_json_safe(v) for k, v in value.items()}
    return value


@inject
@dataclass
class MemoryHandler:
    """记忆系统 API Handler。"""

    memory_write_service: MemoryWriteService
    digest_manager: DigestManager

    # =========================================================
    # A4: 记忆写入
    # =========================================================

    @login_required
    def write(self):
        """POST /memory/write -- 写入一条记忆。

        请求体: ``{"content": str, "memory_type": str}``
        响应: ``{"status", "memory_id", "created_at", "score", ...}``
        """
        req = MemoryWriteReq()
        if not req.validate():
            return validate_error_json(req.errors)

        # 构建 MemoryEvent
        from internal.model.memory_models import EventSource, MemoryEvent

        event = MemoryEvent(
            event_id=uuid4(),
            timestamp=datetime.utcnow(),
            source=EventSource.USER_MESSAGE,
            content=req.content.data,
            context_messages=[],
            metadata={
                "memory_type": req.memory_type.data or "user_message",
                "source": "api",
            },
            user_id=str(current_user.id),
        )

        result = self.memory_write_service.write_from_event(event)
        if result is None:
            return success_json({
                "status": "skipped",
                "memory_id": None,
                "created_at": datetime.utcnow().isoformat(),
                "score": 0.0,
            })

        return success_json(MemoryWriteResp().dump(result))

    # =========================================================
    # B7: 检索 API + Digest API
    # =========================================================

    @login_required
    def retrieve(self):
        """POST /memory/retrieve -- 混合检索记忆。

        请求体: ``{"query": str, "top_k"?, "time_range_days"?, "budget_tokens"?}``
        响应: ``{"results", "summary", "intent", "retrieval_path", "latency_ms"}``

        内部调用 ``MemoryRetriever.retrieve``，并可选调用 ``FunnelCompressor.compress``。
        """
        req = MemoryRetrieveReq()
        if not req.validate():
            return validate_error_json(req.errors)

        query = req.query.data
        top_k = req.top_k.data or 20
        time_range_days = req.time_range_days.data
        budget_tokens = req.budget_tokens.data or 2000

        user_id = str(current_user.id)

        start = time.monotonic()

        # 构造检索选项
        options = RetrievalOptions(
            top_k=top_k,
            time_range_days=time_range_days,
            budget_tokens=budget_tokens,
        )

        # 懒初始化 MemoryRetriever（注入 DigestManager 供 System 1 快速路径使用）
        retriever = MemoryRetriever(digest_manager=self.digest_manager)
        results = retriever.retrieve(query, user_id, options)

        # 可选：漏斗压缩
        summary = None
        retrieval_path = "system2"
        if results and budget_tokens > 0:
            # 判断是否走 System 1（Digest 缓存命中时只有一条 source=digest_cache 的结果）
            if len(results) == 1 and results[0].source == "digest_cache":
                retrieval_path = "system1"
                summary = results[0].content
            else:
                try:
                    compressor = FunnelCompressor()
                    summary = compressor.compress(results, budget_tokens)
                except Exception:
                    logger.warning("retrieve: 漏斗压缩失败，跳过", exc_info=True)
                    summary = None

        latency_ms = (time.monotonic() - start) * 1000

        resp_data = MemoryRetrieveResp().dump({
            "results": [r.model_dump() if hasattr(r, "model_dump") else r.dict() for r in results],
            "summary": summary,
            "intent": "",
            "retrieval_path": retrieval_path,
            "latency_ms": round(latency_ms, 2),
        })

        return success_json(resp_data)

    @login_required
    def get_digest(self, user_id: str):
        """GET /memory/digest/<user_id> -- 获取用户记忆摘要。

        查询参数: ``refresh=true`` 时强制重建 Digest。

        响应: ``{"user_id", "digest", "cached"}``
        """
        # 强制使用当前登录用户 ID，忽略 URL 中的 user_id
        # （安全 + 与 MemoryRetriever._system1_fast_path 的 cache key 一致性）
        user_id = str(current_user.id)
        refresh = request.args.get("refresh", "false").lower() in ("true", "1", "yes")

        if refresh:
            digest_text = self.digest_manager.update_digest(user_id)
            cached = False
        else:
            # get_digest 内部会先查缓存，miss 时自动重建
            digest_text = self.digest_manager.get_digest(user_id)
            # 有内容则可能是缓存命中，无内容说明重建也失败了
            cached = bool(digest_text)

        resp_data = MemoryDigestResp().dump({
            "user_id": user_id,
            "digest": digest_text or "",
            "cached": cached,
        })

        return success_json(resp_data)

    # =========================================================
    # C5: 巩固 API
    # =========================================================

    @login_required
    def consolidate(self, user_id: str):
        """POST /memory/consolidate/<user_id> -- 手动触发记忆巩固。

        查询参数: ``async_mode=true`` 时异步执行（返回 task_id）。

        响应: ``{"user_id", "success", "total_items", "phase_results", "errors", "task_id"?}``
        """
        # 强制使用当前登录用户 ID，忽略 URL 中的 user_id（安全 + cache key 一致性）
        user_id = str(current_user.id)
        async_mode = request.args.get("async_mode", "false").lower() in ("true", "1", "yes")

        if async_mode:
            # 异步模式：提交 Celery 任务
            try:
                from internal.task.consolidation_tasks import run_daily_consolidation

                task = run_daily_consolidation.delay([user_id])
                resp_data = ConsolidationResp().dump({
                    "user_id": user_id,
                    "success": True,
                    "total_items": 0,
                    "phase_results": {"task_id": task.id},
                    "errors": [],
                    "task_id": task.id,
                })
                return success_json(resp_data)
            except Exception as exc:
                logger.error("consolidate: 提交异步巩固任务失败 user=%s", user_id, exc_info=True)
                resp_data = ConsolidationResp().dump({
                    "user_id": user_id,
                    "success": False,
                    "total_items": 0,
                    "phase_results": {},
                    "errors": [f"提交异步任务失败: {exc}"],
                    "task_id": None,
                })
                return success_json(resp_data)

        # 同步模式：直接执行巩固
        try:
            engine = ConsolidationEngine()
            report = engine.run_consolidation(user_id)

            resp_data = ConsolidationResp().dump({
                "user_id": user_id,
                "success": report.is_success,
                "total_items": report.total_items_processed,
                "phase_results": report.phases,
                "errors": report.errors,
                "task_id": None,
            })
        except Exception as exc:
            logger.error("consolidate: 同步巩固执行失败 user=%s", user_id, exc_info=True)
            resp_data = ConsolidationResp().dump({
                "user_id": user_id,
                "success": False,
                "total_items": 0,
                "phase_results": {},
                "errors": [f"巩固执行失败: {exc}"],
                "task_id": None,
            })

        return success_json(resp_data)

    # =========================================================
    # D4: 图谱 API + 记忆 CRUD API
    # =========================================================

    @login_required
    def get_memory_graph(self, user_id: str):
        """GET /memory/graph/<user_id> -- 记忆图谱聚类视图。

        返回 6 个 memory_type 区块的节点数与最近更新时间。
        """
        # 强制使用当前登录用户 ID，忽略 URL 中的 user_id（安全 + cache key 一致性）
        user_id = str(current_user.id)
        from internal.service.memory.degradation_manager import get_degradation_manager

        # 降级检查：Neo4j 不可用时返回 503
        dm = get_degradation_manager()
        if dm is not None and not dm.memory_engine_enabled:
            return success_json({"error": "memory_engine_unavailable", "code": 503})

        driver = self._get_neo4j_driver()
        if driver is None:
            return success_json(GraphResp().dump({
                "user_id": user_id,
                "clusters": [],
                "total_nodes": 0,
            }))

        try:
            cypher = """
            MATCH (n:MemoryNode)
            WHERE n.user_id = $user_id AND n.is_active = true
            RETURN coalesce(n.memory_type, labels(n)[0]) AS memory_type,
                   count(n) AS node_count,
                   max(coalesce(n.last_accessed, n.created_at)) AS last_updated_at
            ORDER BY memory_type
            """
            with driver.session() as session:
                result = session.run(cypher, user_id=user_id)
                records = list(result)

            clusters = []
            total_nodes = 0
            for record in records:
                count = record.get("node_count", 0)
                total_nodes += count
                clusters.append({
                    "memory_type": record.get("memory_type", ""),
                    "node_count": count,
                    "last_updated_at": str(record.get("last_updated_at", "")),
                })

            resp_data = GraphResp().dump({
                "user_id": user_id,
                "clusters": clusters,
                "total_nodes": total_nodes,
            })
            return success_json(resp_data)
        except Exception as exc:
            logger.error("get_memory_graph: 查询失败 user=%s", user_id, exc_info=True)
            return success_json(GraphResp().dump({
                "user_id": user_id,
                "clusters": [],
                "total_nodes": 0,
            }))

    @login_required
    def get_cluster_subgraph(self, user_id: str, cluster_type: str):
        """GET /memory/graph/<user_id>/cluster/<type> -- 聚类子图查询。

        限制 ≤ 200 节点，超出按 weight 降序截断。
        """
        # 强制使用当前登录用户 ID，忽略 URL 中的 user_id（安全 + cache key 一致性）
        user_id = str(current_user.id)
        driver = self._get_neo4j_driver()
        if driver is None:
            return success_json(ClusterSubgraphResp().dump({
                "nodes": [], "edges": [], "truncated": False,
            }))

        try:
            cypher = """
            MATCH (n:MemoryNode)
            WHERE n.user_id = $user_id AND n.is_active = true
              AND ($cluster_type IN labels(n) OR n.memory_type = $cluster_type)
            WITH n ORDER BY coalesce(n.access_count, 0) DESC LIMIT 200
            OPTIONAL MATCH (n)-[r]-(m:MemoryNode)
            WHERE m.user_id = $user_id AND m.is_active = true
            WITH n, r, startNode(r) AS sn, endNode(r) AS en
            RETURN collect(DISTINCT n) AS nodes,
                   collect(DISTINCT {
                     source: sn.id, target: en.id,
                     type: type(r), weight: coalesce(r.weight, 0.5),
                     edge_id: coalesce(r.edge_id, elementId(r))
                   }) AS edges,
                   count(DISTINCT n) AS node_count
            """
            with driver.session() as session:
                result = session.run(
                    cypher,
                    user_id=user_id,
                    cluster_type=cluster_type,
                )
                record = result.single()

            if record is None:
                return success_json(ClusterSubgraphResp().dump({
                    "nodes": [], "edges": [], "truncated": False,
                }))

            # 使用 _neo4j_to_json_safe 递归转换 Neo4j 类型，避免 jsonify 序列化失败
            nodes = [_neo4j_to_json_safe(n) for n in (record.get("nodes") or [])]
            edges = [_neo4j_to_json_safe(r) for r in (record.get("edges") or [])
                     if r.get("source") and r.get("target")]
            node_count = record.get("node_count", 0)

            resp_data = ClusterSubgraphResp().dump({
                "nodes": nodes,
                "edges": edges,
                "truncated": node_count >= 200,
            })
            return success_json(resp_data)
        except Exception as exc:
            logger.error("get_cluster_subgraph: 查询失败", exc_info=True)
            return success_json(ClusterSubgraphResp().dump({
                "nodes": [], "edges": [], "truncated": False,
            }))

    @login_required
    def get_memory_detail(self, memory_id: str):
        """GET /memory/<memory_id> -- 单条记忆详情。"""
        driver = self._get_neo4j_driver()
        if driver is None:
            return success_json({})

        user_id = str(current_user.id)

        try:
            cypher = """
            MATCH (n {node_id: $memory_id})
            WHERE n.user_id = $user_id OR n.user_id IS NULL
            OPTIONAL MATCH (n)-[r]-(m)
            RETURN n, collect({node: m, weight: r.weight, relation: type(r)}) AS related
            """
            with driver.session() as session:
                record = session.run(
                    cypher,
                    memory_id=memory_id,
                    user_id=user_id,
                ).single()

            if record is None:
                return success_json({})

            node = _neo4j_to_json_safe(record.get("n", {}))
            related = [
                {"node_id": str(r.get("node", {}).get("id", "")),
                 "weight": _neo4j_to_json_safe(r.get("weight", 0.0)),
                 "relation": r.get("relation", "")}
                for r in (record.get("related") or [])
                if r.get("node") is not None
            ]

            resp_data = MemoryDetailResp().dump({
                "memory_id": node.get("id", ""),
                "content": node.get("content", ""),
                "memory_type": node.get("memory_type"),
                "confidence": node.get("confidence"),
                "source_conversation_id": node.get("source_conversation_id"),
                "created_at": node.get("created_at", ""),
                "last_accessed_at": node.get("last_accessed_at", ""),
                "related": related,
            })
            return success_json(resp_data)
        except Exception as exc:
            logger.error("get_memory_detail: 查询失败 memory=%s", memory_id, exc_info=True)
            return success_json(MemoryDetailResp().dump({
                "memory_id": memory_id, "content": "", "related": [],
            }))

    @login_required
    def edit_memory(self, memory_id: str):
        """PUT /memory/<memory_id> -- 编辑记忆（创建新节点 + 旧节点失效）。"""
        req = EditMemoryReq()
        if not req.validate():
            return validate_error_json(req.errors)

        from internal.service.memory.memory_governor import MemoryGovernor

        governor = MemoryGovernor()
        new_id = governor.edit_memory(memory_id, str(current_user.id), req.new_content.data)

        if new_id is None:
            return success_json({"success": False, "error": "编辑失败（权限或依赖问题）"})

        return success_json({"success": True, "new_memory_id": new_id})

    @login_required
    def soft_delete_memory(self, memory_id: str):
        """DELETE /memory/<memory_id> -- 软删除记忆。"""
        from internal.service.memory.memory_governor import MemoryGovernor

        governor = MemoryGovernor()
        deleted = governor.soft_delete_memory(memory_id, str(current_user.id))

        return success_json({"deleted": deleted})

    @login_required
    def hard_delete_memory(self, memory_id: str):
        """DELETE /memory/<memory_id>/hard -- 彻底删除记忆。"""
        from internal.service.memory.memory_governor import MemoryGovernor

        governor = MemoryGovernor()
        deleted = governor.hard_delete_memory(memory_id, str(current_user.id))

        return success_json({"deleted": deleted})

    @login_required
    def decay_memory(self, memory_id: str):
        """POST /memory/<memory_id>/decay -- 手动降权。"""
        req = DecayReq()
        if not req.validate():
            return validate_error_json(req.errors)

        try:
            decay_factor = float(req.decay_factor.data or "0.5")
            decay_factor = max(0.0, min(1.0, decay_factor))
        except (ValueError, TypeError):
            decay_factor = 0.5

        from internal.service.memory.hebbian_decay import HebbianDecay

        decay = HebbianDecay()
        new_weight = decay.manual_decay(memory_id, decay_factor)

        return success_json({"memory_id": memory_id, "new_weight": new_weight})

    # =========================================================
    # E2: 技能列表 API
    # =========================================================

    @login_required
    def list_skills(self, user_id: str):
        """GET /memory/skills/<user_id> -- 用户技能列表。

        优先从 Redis 缓存读取，DEPRECATED 状态不返回。
        """
        # 强制使用当前登录用户 ID，忽略 URL 中的 user_id（安全 + cache key 一致性）
        user_id = str(current_user.id)

        # 优先从 Redis 缓存读取
        redis_client = None
        try:
            from flask import current_app
            redis_client = current_app.extensions.get("redis")
        except RuntimeError:
            pass

        if redis_client is not None:
            try:
                cached = redis_client.get(f"skill:pool:{user_id}")
                if cached:
                    cached_text = cached.decode("utf-8") if isinstance(cached, bytes) else cached
                    if cached_text:
                        skills = [{"name": line.strip("- ").strip(), "cached": True}
                                  for line in cached_text.split("\n") if line.strip()]
                        return success_json(SkillListResp().dump({
                            "user_id": user_id,
                            "skills": skills,
                            "total": len(skills),
                        }))
            except Exception:
                pass

        # 缓存未命中，查询 Neo4j
        driver = self._get_neo4j_driver()
        if driver is None:
            return success_json(SkillListResp().dump({
                "user_id": user_id, "skills": [], "total": 0,
            }))

        try:
            cypher = """
            MATCH (s:Skill {user_id: $user_id})
            WHERE s.status <> 'deprecated'
            RETURN s
            ORDER BY
                CASE s.status
                    WHEN 'active' THEN 0
                    WHEN 'emerging' THEN 1
                    WHEN 'candidate' THEN 2
                    WHEN 'stale' THEN 3
                END,
                s.maturity DESC
            """
            with driver.session() as session:
                result = session.run(cypher, user_id=user_id)
                records = list(result)

            skills = []
            for record in records:
                node = _neo4j_to_json_safe(record.get("s", {}))
                skills.append({
                    "skill_id": node.get("id", ""),
                    "name": node.get("name", ""),
                    "description": node.get("description", ""),
                    "status": node.get("status", ""),
                    "maturity": node.get("maturity", 0.0),
                    "use_count": node.get("use_count", 0),
                })

            # 写回 Redis 缓存（TTL 5min）
            if redis_client is not None:
                try:
                    cache_text = "\n".join(f"- {s['name']}" for s in skills)
                    redis_client.setex(f"skill:pool:{user_id}", 300, cache_text)
                except Exception:
                    pass

            resp_data = SkillListResp().dump({
                "user_id": user_id,
                "skills": skills,
                "total": len(skills),
            })
            return success_json(resp_data)
        except Exception as exc:
            logger.error("list_skills: 查询失败 user=%s", user_id, exc_info=True)
            return success_json(SkillListResp().dump({
                "user_id": user_id, "skills": [], "total": 0,
            }))

    # =========================================================
    # H4: 健康检查 API
    # =========================================================

    def health(self):
        """GET /memory/health -- 记忆系统健康检查。

        返回各依赖（Neo4j/pgvector/Redis）连接状态、整体状态、版本号与运行时长。
        不需要鉴权（供监控探针调用）。
        """
        dm = get_degradation_manager()

        # 获取依赖状态快照；DegradationManager 未初始化时降级为全不可用
        if dm is not None:
            status_snapshot = dm.get_status()
            neo4j_ok = status_snapshot.get("neo4j", False)
            pgvector_ok = status_snapshot.get("pgvector", False)
            redis_ok = status_snapshot.get("redis", False)
        else:
            neo4j_ok = False
            pgvector_ok = False
            redis_ok = False

        neo4j_status = "healthy" if neo4j_ok else "unreachable"
        pgvector_status = "healthy" if pgvector_ok else "unreachable"
        redis_status = "healthy" if redis_ok else "unreachable"

        deps = [neo4j_status, pgvector_status, redis_status]
        unreachable_count = sum(1 for s in deps if s == "unreachable")
        if unreachable_count == 0:
            overall = "healthy"
        elif unreachable_count >= 2:
            overall = "unhealthy"
        else:
            overall = "degraded"

        return success_json({
            "status": overall,
            "version": MEMORY_SYSTEM_VERSION,
            "neo4j": neo4j_status,
            "pgvector": pgvector_status,
            "redis": redis_status,
            "uptime_seconds": round(time.time() - _SERVICE_START_TIME, 2),
        })

    # =========================================================
    # 辅助方法
    # =========================================================

    @staticmethod
    def _get_neo4j_driver():
        """获取 Neo4j 驱动，不可用时返回 None。"""
        try:
            from flask import current_app

            return current_app.extensions.get("neo4j")
        except RuntimeError:
            return None
