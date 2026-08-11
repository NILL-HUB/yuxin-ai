"""用户侧路由迁移批次 9（Quart 异步端点）。

迁移来源：internal/router/router.py 中以下 handler 的注册段：
    public_app_handler / showcase_handler / public_workflow_handler /
    audio_handler / platform_handler / wechat_handler / routing_log_handler /
    ai_handler / redeem_code_handler / memory_handler

实现来源：internal/handler/ 下对应的 *_handler.py。

通过 ``register_routes(quart_app)`` 一次性注册全部端点；使用模块级
``_registered`` 标志保证幂等，重复调用直接返回。
"""

import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

from quart import request

_MEMORY_SYSTEM_VERSION = "1.0.0"
_SERVICE_START_TIME = time.time()

_registered = False


def _int_arg(name, default):
    raw = request.args.get(name)
    try:
        return int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def _to_int(value, default):
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _flask_ext(name):
    from app.http.app import app as flask_app

    return flask_app.extensions.get(name)


def _neo4j_to_json_safe(value):
    """将 Neo4j 返回值递归转为 JSON 可序列化的 Python 原生类型。"""
    if hasattr(value, "items") and callable(value.items):
        return {k: _neo4j_to_json_safe(v) for k, v in value.items()}
    if hasattr(value, "isoformat") and callable(value.isoformat):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_neo4j_to_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _neo4j_to_json_safe(v) for k, v in value.items()}
    return value


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    # =====================================================
    # redeem_code_handler
    # =====================================================
    @quart_app.post("/redeem-codes/redeem")
    async def redeem_code_redeem():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.redeem_code_schema import RedeemCodeResp
        from internal.service.redeem_code_service import RedeemCodeService

        payload = await request.get_json(force=True, silent=True) or {}
        code = str(payload.get("code") or "").strip()
        if not code or len(code) < 6:
            return a._json_resp(
                code="validate_error",
                message="code不能为空",
                data={"code": ["code不能为空"]},
                status=400,
            )
        result = await a._to_thread(
            a._get_service(RedeemCodeService).redeem, account.id, code
        )
        return a._ok(RedeemCodeResp().dump(result))

    @quart_app.get("/membership/summary")
    async def redeem_code_summary():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.redeem_code_schema import MembershipSummaryResp
        from internal.service.redeem_code_service import RedeemCodeService

        result = await a._to_thread(
            a._get_service(RedeemCodeService).get_membership_summary, account.id
        )
        return a._ok(MembershipSummaryResp().dump(result))

    @quart_app.get("/membership/redeem-records")
    async def redeem_code_records():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.redeem_code_schema import RedeemRecordListResp
        from internal.service.redeem_code_service import RedeemCodeService

        result = await a._to_thread(
            a._get_service(RedeemCodeService).list_redeem_records, account.id
        )
        return a._ok(RedeemRecordListResp().dump(result))

    # =====================================================
    # memory_handler
    # =====================================================
    @quart_app.post("/memory/write")
    async def memory_write():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.memory_schema import MemoryWriteResp
        from internal.service.memory.memory_write_service import MemoryWriteService

        payload = await request.get_json(force=True, silent=True) or {}
        content = str(payload.get("content") or "")
        if not content.strip():
            return a._json_resp(
                code="validate_error",
                message="content不能为空",
                data={"content": ["content不能为空"]},
                status=400,
            )
        memory_type = str(payload.get("memory_type") or "user_message")

        from internal.model.memory_models import EventSource, MemoryEvent

        event = MemoryEvent(
            event_id=uuid4(),
            timestamp=datetime.now(UTC),
            source=EventSource.USER_MESSAGE,
            content=content,
            context_messages=[],
            metadata={
                "memory_type": memory_type,
                "source": "api",
            },
            user_id=str(account.id),
        )
        result = await a._to_thread(
            a._get_service(MemoryWriteService).write_from_event, event
        )
        if result is None:
            return a._ok({
                "status": "skipped",
                "memory_id": None,
                "created_at": datetime.now(UTC).isoformat(),
                "score": 0.0,
            })
        return a._ok(MemoryWriteResp().dump(result))

    @quart_app.get("/memory/health")
    async def memory_health():
        from app.http import asgi_app as a

        from internal.service.memory.degradation_manager import get_degradation_manager

        dm = get_degradation_manager()
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

        return a._ok({
            "status": overall,
            "version": _MEMORY_SYSTEM_VERSION,
            "neo4j": neo4j_status,
            "pgvector": pgvector_status,
            "redis": redis_status,
            "uptime_seconds": round(time.time() - _SERVICE_START_TIME, 2),
        })

    @quart_app.post("/memory/retrieve")
    async def memory_retrieve():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.model.memory_models import RetrievalOptions
        from internal.schema.memory_schema import MemoryRetrieveResp
        from internal.service.memory.digest_manager import DigestManager
        from internal.service.memory.funnel_compressor import FunnelCompressor
        from internal.service.memory.retriever import MemoryRetriever

        payload = await request.get_json(force=True, silent=True) or {}
        query = str(payload.get("query") or "")
        if not query.strip():
            return a._json_resp(
                code="validate_error",
                message="query不能为空",
                data={"query": ["query不能为空"]},
                status=400,
            )
        top_k = _to_int(payload.get("top_k"), 20)
        time_range_days = payload.get("time_range_days")
        budget_tokens = _to_int(payload.get("budget_tokens"), 2000)

        user_id = str(account.id)
        options = RetrievalOptions(
            top_k=top_k,
            time_range_days=time_range_days,
            budget_tokens=budget_tokens,
        )

        retriever = MemoryRetriever(digest_manager=a._get_service(DigestManager))
        results = await a._to_thread(retriever.retrieve, query, user_id, options)

        summary = None
        retrieval_path = "system2"
        if results and budget_tokens > 0:
            if len(results) == 1 and results[0].source == "digest_cache":
                retrieval_path = "system1"
                summary = results[0].content
            else:
                try:
                    compressor = FunnelCompressor()
                    summary = await a._to_thread(
                        compressor.compress, results, budget_tokens
                    )
                except Exception:
                    summary = None

        resp_data = MemoryRetrieveResp().dump({
            "results": [
                r.model_dump() if hasattr(r, "model_dump") else r.dict()
                for r in results
            ],
            "summary": summary,
            "intent": "",
            "retrieval_path": retrieval_path,
            "latency_ms": round(0.0, 2),
        })
        return a._ok(resp_data)

    @quart_app.get("/memory/digest/<string:user_id>")
    async def memory_digest(user_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.memory_schema import MemoryDigestResp
        from internal.service.memory.digest_manager import DigestManager

        user_id = str(account.id)
        refresh = request.args.get("refresh", "false").lower() in ("true", "1", "yes")
        digest_manager = a._get_service(DigestManager)

        if refresh:
            digest_text = await a._to_thread(digest_manager.update_digest, user_id)
            cached = False
        else:
            digest_text = await a._to_thread(digest_manager.get_digest, user_id)
            cached = bool(digest_text)

        resp_data = MemoryDigestResp().dump({
            "user_id": user_id,
            "digest": digest_text or "",
            "cached": cached,
        })
        return a._ok(resp_data)

    @quart_app.post("/memory/consolidate/<string:user_id>")
    async def memory_consolidate(user_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.memory_schema import ConsolidationResp

        user_id = str(account.id)
        async_mode = request.args.get("async_mode", "false").lower() in ("true", "1", "yes")

        if async_mode:
            try:
                from internal.task.consolidation_tasks import run_daily_consolidation

                task = await a._to_thread(run_daily_consolidation.delay, [user_id])
                resp_data = ConsolidationResp().dump({
                    "user_id": user_id,
                    "success": True,
                    "total_items": 0,
                    "phase_results": {"task_id": task.id},
                    "errors": [],
                    "task_id": task.id,
                })
                return a._ok(resp_data)
            except Exception as exc:
                resp_data = ConsolidationResp().dump({
                    "user_id": user_id,
                    "success": False,
                    "total_items": 0,
                    "phase_results": {},
                    "errors": [f"提交异步任务失败: {exc}"],
                    "task_id": None,
                })
                return a._ok(resp_data)

        from internal.service.memory.consolidation_engine import ConsolidationEngine

        try:
            engine = ConsolidationEngine()
            report = await a._to_thread(engine.run_consolidation, user_id)
            resp_data = ConsolidationResp().dump({
                "user_id": user_id,
                "success": report.is_success,
                "total_items": report.total_items_processed,
                "phase_results": report.phases,
                "errors": report.errors,
                "task_id": None,
            })
        except Exception as exc:
            resp_data = ConsolidationResp().dump({
                "user_id": user_id,
                "success": False,
                "total_items": 0,
                "phase_results": {},
                "errors": [f"巩固执行失败: {exc}"],
                "task_id": None,
            })
        return a._ok(resp_data)

    @quart_app.get("/memory/graph/<string:user_id>")
    async def memory_get_memory_graph(user_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.memory_schema import GraphResp
        from internal.service.memory.degradation_manager import get_degradation_manager

        user_id = str(account.id)

        dm = get_degradation_manager()
        if dm is not None and not dm.memory_engine_enabled:
            return a._ok({"error": "memory_engine_unavailable", "code": 503})

        driver = _flask_ext("neo4j")
        if driver is None:
            return a._ok(GraphResp().dump({
                "user_id": user_id,
                "clusters": [],
                "total_nodes": 0,
            }))

        def _run_query(driver, user_id):
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
                return list(result)

        try:
            records = await a._to_thread(_run_query, driver, user_id)
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
            return a._ok(resp_data)
        except Exception:
            return a._ok(GraphResp().dump({
                "user_id": user_id,
                "clusters": [],
                "total_nodes": 0,
            }))

    @quart_app.get("/memory/graph/<string:user_id>/cluster/<string:cluster_type>")
    async def memory_get_cluster_subgraph(user_id, cluster_type):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.memory_schema import ClusterSubgraphResp

        user_id = str(account.id)
        driver = _flask_ext("neo4j")
        if driver is None:
            return a._ok(ClusterSubgraphResp().dump({
                "nodes": [], "edges": [], "truncated": False,
            }))

        def _run_query(driver, user_id, cluster_type):
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
                return result.single()

        try:
            record = await a._to_thread(_run_query, driver, user_id, cluster_type)
            if record is None:
                return a._ok(ClusterSubgraphResp().dump({
                    "nodes": [], "edges": [], "truncated": False,
                }))
            nodes = [_neo4j_to_json_safe(n) for n in (record.get("nodes") or [])]
            edges = [
                _neo4j_to_json_safe(r) for r in (record.get("edges") or [])
                if r.get("source") and r.get("target")
            ]
            node_count = record.get("node_count", 0)
            resp_data = ClusterSubgraphResp().dump({
                "nodes": nodes,
                "edges": edges,
                "truncated": node_count >= 200,
            })
            return a._ok(resp_data)
        except Exception:
            return a._ok(ClusterSubgraphResp().dump({
                "nodes": [], "edges": [], "truncated": False,
            }))

    @quart_app.get("/memory/<string:memory_id>")
    async def memory_get_memory_detail(memory_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.memory_schema import MemoryDetailResp

        driver = _flask_ext("neo4j")
        if driver is None:
            return a._ok({})

        user_id = str(account.id)

        def _run_query(driver, memory_id, user_id):
            cypher = """
            MATCH (n {node_id: $memory_id})
            WHERE n.user_id = $user_id OR n.user_id IS NULL
            OPTIONAL MATCH (n)-[r]-(m)
            RETURN n, collect({node: m, weight: r.weight, relation: type(r)}) AS related
            """
            with driver.session() as session:
                return session.run(
                    cypher,
                    memory_id=memory_id,
                    user_id=user_id,
                ).single()

        try:
            record = await a._to_thread(_run_query, driver, memory_id, user_id)
            if record is None:
                return a._ok({})

            node = _neo4j_to_json_safe(record.get("n", {}))
            related = [
                {
                    "node_id": str(r.get("node", {}).get("id", "")),
                    "weight": _neo4j_to_json_safe(r.get("weight", 0.0)),
                    "relation": r.get("relation", ""),
                }
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
            return a._ok(resp_data)
        except Exception:
            return a._ok(MemoryDetailResp().dump({
                "memory_id": memory_id, "content": "", "related": [],
            }))

    @quart_app.post("/memory/<string:memory_id>/edit")
    async def memory_edit_memory(memory_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service.memory.memory_governor import MemoryGovernor

        payload = await request.get_json(force=True, silent=True) or {}
        new_content = str(payload.get("new_content") or "")
        if not new_content.strip():
            return a._json_resp(
                code="validate_error",
                message="new_content不能为空",
                data={"new_content": ["new_content不能为空"]},
                status=400,
            )
        governor = a._get_service(MemoryGovernor)
        new_id = await a._to_thread(
            governor.edit_memory, memory_id, str(account.id), new_content
        )
        if new_id is None:
            return a._ok({"success": False, "error": "编辑失败（权限或依赖问题）"})
        return a._ok({"success": True, "new_memory_id": new_id})

    @quart_app.post("/memory/<string:memory_id>/soft-delete")
    async def memory_soft_delete_memory(memory_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service.memory.memory_governor import MemoryGovernor

        governor = a._get_service(MemoryGovernor)
        deleted = await a._to_thread(
            governor.soft_delete_memory, memory_id, str(account.id)
        )
        return a._ok({"deleted": deleted})

    @quart_app.post("/memory/<string:memory_id>/hard-delete")
    async def memory_hard_delete_memory(memory_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service.memory.memory_governor import MemoryGovernor

        governor = a._get_service(MemoryGovernor)
        deleted = await a._to_thread(
            governor.hard_delete_memory, memory_id, str(account.id)
        )
        return a._ok({"deleted": deleted})

    @quart_app.post("/memory/<string:memory_id>/decay")
    async def memory_decay_memory(memory_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service.memory.hebbian_decay import HebbianDecay

        payload = await request.get_json(force=True, silent=True) or {}
        try:
            decay_factor = float(payload.get("decay_factor") or "0.5")
            decay_factor = max(0.0, min(1.0, decay_factor))
        except (ValueError, TypeError):
            decay_factor = 0.5

        decay = HebbianDecay()
        new_weight = await a._to_thread(
            decay.manual_decay, memory_id, decay_factor
        )
        return a._ok({"memory_id": memory_id, "new_weight": new_weight})

    @quart_app.get("/memory/skills/<string:user_id>")
    async def memory_list_skills(user_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.memory_schema import SkillListResp

        user_id = str(account.id)

        redis_client = _flask_ext("redis")
        if redis_client is not None:
            try:
                cached = await a._to_thread(redis_client.get, f"skill:pool:{user_id}")
                if cached:
                    cached_text = cached.decode("utf-8") if isinstance(cached, bytes) else cached
                    if cached_text:
                        skills = [
                            {"name": line.strip("- ").strip(), "cached": True}
                            for line in cached_text.split("\n")
                            if line.strip()
                        ]
                        return a._ok(SkillListResp().dump({
                            "user_id": user_id,
                            "skills": skills,
                            "total": len(skills),
                        }))
            except Exception:
                pass

        driver = _flask_ext("neo4j")
        if driver is None:
            return a._ok(SkillListResp().dump({
                "user_id": user_id, "skills": [], "total": 0,
            }))

        def _run_query(driver, user_id):
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
                return list(result)

        try:
            records = await a._to_thread(_run_query, driver, user_id)
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

            if redis_client is not None:
                try:
                    cache_text = "\n".join(f"- {s['name']}" for s in skills)
                    await a._to_thread(
                        redis_client.setex, f"skill:pool:{user_id}", 300, cache_text
                    )
                except Exception:
                    pass

            resp_data = SkillListResp().dump({
                "user_id": user_id,
                "skills": skills,
                "total": len(skills),
            })
            return a._ok(resp_data)
        except Exception:
            return a._ok(SkillListResp().dump({
                "user_id": user_id, "skills": [], "total": 0,
            }))

    # =====================================================
    # ai_handler
    # =====================================================
    @quart_app.post("/ai/optimize-prompt")
    async def ai_optimize_prompt():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import AIService

        payload = await request.get_json(force=True, silent=True) or {}
        prompt = str(payload.get("prompt") or "")
        if not prompt.strip():
            return a._json_resp(
                code="validate_error",
                message="预设prompt不能为空",
                data={"prompt": ["预设prompt不能为空"]},
                status=400,
            )
        response = await a._to_thread(
            a._get_service(AIService).optimize_prompt, prompt
        )
        if a._is_sync_iterator(response):
            return a._sse_response(response)
        return a._ok(response.data)

    @quart_app.post("/ai/suggested-questions")
    async def ai_generate_suggested_questions():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import AIService

        payload = await request.get_json(force=True, silent=True) or {}
        try:
            message_id = UUID(str(payload.get("message_id") or ""))
        except (ValueError, TypeError):
            return a._json_resp(
                code="validate_error",
                message="消息id格式必须为uuid",
                data={"message_id": ["消息id格式必须为uuid"]},
                status=400,
            )
        suggested_questions = await a._to_thread(
            a._get_service(AIService).generate_suggested_questions_from_message_id,
            message_id,
            account,
        )
        return a._ok(suggested_questions)

    @quart_app.post("/ai/chat")
    async def ai_code_assistant_chat():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import AIService

        payload = await request.get_json(force=True, silent=True) or {}
        question = str(payload.get("question") or "")
        if not question.strip():
            return a._json_resp(
                code="validate_error",
                message="问题不能为空",
                data={"question": ["问题不能为空"]},
                status=400,
            )
        response = await a._to_thread(
            a._get_service(AIService).code_assistant_chat, question
        )
        if a._is_sync_iterator(response):
            return a._sse_response(response)
        return a._ok(response.data)

    @quart_app.post("/ai/openapi-schema-chat")
    async def ai_openapi_schema_assistant_chat():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import AIService

        payload = await request.get_json(force=True, silent=True) or {}
        question = str(payload.get("question") or "")
        if not question.strip():
            return a._json_resp(
                code="validate_error",
                message="需求描述不能为空",
                data={"question": ["需求描述不能为空"]},
                status=400,
            )
        response = await a._to_thread(
            a._get_service(AIService).openapi_schema_assistant_chat, question
        )
        if a._is_sync_iterator(response):
            return a._sse_response(response)
        return a._ok(response.data)

    @quart_app.post("/ai/mcp-schema-chat")
    async def ai_mcp_schema_assistant_chat():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import AIService

        payload = await request.get_json(force=True, silent=True) or {}
        question = str(payload.get("question") or "")
        if not question.strip():
            return a._json_resp(
                code="validate_error",
                message="需求描述不能为空",
                data={"question": ["需求描述不能为空"]},
                status=400,
            )
        response = await a._to_thread(
            a._get_service(AIService).mcp_schema_assistant_chat, question
        )
        if a._is_sync_iterator(response):
            return a._sse_response(response)
        return a._ok(response.data)

    # =====================================================
    # audio_handler
    # =====================================================
    @quart_app.post("/audio/audio-to-text")
    async def audio_audio_to_text():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import AudioService

        files = await request.files
        file = files.get("file")
        if file is None or not file.filename:
            return a._json_resp(
                code="validate_error",
                message="转换音频文件不能为空",
                data={"file": ["转换音频文件不能为空"]},
                status=400,
            )
        text = await a._to_thread(
            a._get_service(AudioService).audio_to_text, file
        )
        return a._ok({"text": text})

    @quart_app.post("/audio/message-to-audio")
    async def audio_message_to_audio():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import AudioService

        payload = await request.get_json(force=True, silent=True) or {}
        message_id = str(payload.get("message_id") or "")
        if not message_id:
            return a._json_resp(
                code="validate_error",
                message="消息id不能为空",
                data={"message_id": ["消息id不能为空"]},
                status=400,
            )
        response = await a._to_thread(
            a._get_service(AudioService).message_to_audio, message_id, account
        )
        if a._is_sync_iterator(response):
            return a._sse_response(response)
        return a._ok(response.data)

    @quart_app.post("/audio/text-to-audio")
    async def audio_text_to_audio():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import AudioService

        payload = await request.get_json(force=True, silent=True) or {}
        text = str(payload.get("text") or "")
        if not text.strip():
            return a._json_resp(
                code="validate_error",
                message="文本内容不能为空",
                data={"text": ["文本内容不能为空"]},
                status=400,
            )
        message_id = str(payload.get("message_id") or "")
        response = await a._to_thread(
            a._get_service(AudioService).text_to_audio,
            message_id,
            text,
            account,
        )
        if a._is_sync_iterator(response):
            return a._sse_response(response)
        return a._ok(response.data)

    # =====================================================
    # platform_handler
    # =====================================================
    @quart_app.get("/platform/<uuid:app_id>/wechat-config")
    async def platform_get_wechat_config(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.platform_schema import GetWechatConfigResp
        from internal.service import PlatformService

        wechat_config = await a._to_thread(
            a._get_service(PlatformService).get_wechat_config, app_id, account
        )
        return a._ok(GetWechatConfigResp().dump(wechat_config))

    @quart_app.post("/platform/<uuid:app_id>/wechat-config")
    async def platform_update_wechat_config(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service import PlatformService

        payload = await request.get_json(force=True, silent=True) or {}
        req = a.SimpleNamespace(
            wechat_app_id=a._field(str(payload.get("wechat_app_id") or ""), ""),
            wechat_app_secret=a._field(str(payload.get("wechat_app_secret") or ""), ""),
            wechat_token=a._field(str(payload.get("wechat_token") or ""), ""),
        )
        await a._to_thread(
            a._get_service(PlatformService).update_wechat_config, app_id, req, account
        )
        return a._ok_msg("更新Agent应用微信公众号配置成功")

    # =====================================================
    # wechat_handler
    # =====================================================
    @quart_app.get("/wechat/<uuid:app_id>")
    @quart_app.post("/wechat/<uuid:app_id>")
    async def wechat_endpoint(app_id):
        from app.http import asgi_app as a

        from internal.service import WechatService

        # Quart 单栈：HTTP 数据从 Quart request 提取后显式传入，
        # 服务层不再访问 Flask request 上下文（否则 to_thread 线程内必抛异常）
        method = request.method
        body = await request.get_data()
        query = {key: value for key, value in request.args.items()}
        result = await a._to_thread(
            a._get_service(WechatService).wechat, app_id, method, body, query
        )
        # 微信回调协议要求纯文本响应（GET 回显 echostr / POST 返回 XML），
        # 不能走 _ok() 的 JSON 包装。
        return result

    # =====================================================
    # public_app_handler
    # =====================================================
    @quart_app.get("/public/apps")
    async def public_app_get_public_apps_with_page():
        from app.http import asgi_app as a

        from internal.service.public_app_service import PublicAppService

        account = None
        req = a.SimpleNamespace(
            current_page=a._field(_int_arg("current_page", 1), 1),
            page_size=a._field(_int_arg("page_size", 20), 20),
            tags=a._field(request.args.get("tags") or "", ""),
            search_word=a._field(request.args.get("search_word") or "", ""),
        )
        apps, paginator = await a._to_thread(
            a._get_service(PublicAppService).get_public_apps_with_page, req, account
        )
        return a._ok({"list": apps, "paginator": a.asdict(paginator)})

    @quart_app.get("/public/apps/tags")
    async def public_app_get_app_tags():
        from app.http import asgi_app as a

        from internal.schema.public_app_schema import GetAppTagsResp

        return a._ok(GetAppTagsResp().dump({}))

    @quart_app.get("/public/apps/<string:app_id>")
    async def public_app_get_public_app_detail(app_id):
        from app.http import asgi_app as a

        from internal.service.public_app_service import PublicAppService

        account = None
        app_detail = await a._to_thread(
            a._get_service(PublicAppService).get_public_app_detail, app_id, account
        )
        return a._ok(app_detail)

    @quart_app.post("/public/apps/<string:app_id>/a2a/messages")
    async def public_app_send_public_app_a2a_message(app_id):
        from app.http import asgi_app as a

        from internal.service.public_agent_a2a_service import PublicAgentA2AService

        try:
            a2a_service = a._get_service(PublicAgentA2AService)
        except Exception:
            a2a_service = None
        if not a2a_service:
            return a._json_resp(
                {"error": "A2A service unavailable"}, code="fail", status=503
            )
        payload = await request.get_json(force=True, silent=True) or {}
        response = await a._to_thread(a2a_service.stream_message, app_id, payload)
        if a._is_sync_iterator(response):
            return a._sse_response(response)
        return a._ok(response.data)

    @quart_app.get("/public/apps/<string:app_id>/a2a/conversations/<string:conversation_id>/messages")
    async def public_app_get_public_app_a2a_conversation_messages(app_id, conversation_id):
        from app.http import asgi_app as a

        from internal.service.public_agent_a2a_service import PublicAgentA2AService

        try:
            a2a_service = a._get_service(PublicAgentA2AService)
        except Exception:
            a2a_service = None
        if not a2a_service:
            return a._json_resp(
                {"error": "A2A service unavailable"}, code="fail", status=503
            )
        messages = await a._to_thread(
            a2a_service.list_public_app_conversation_messages,
            app_id,
            conversation_id,
        )
        return a._ok(messages)

    @quart_app.post("/apps/<uuid:app_id>/share-to-square")
    async def public_app_share_app_to_square(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service.public_app_service import PublicAppService

        payload = await request.get_json(force=True, silent=True) or {}
        tags = payload.get("tags")
        tags = tags if tags else None
        await a._to_thread(
            a._get_service(PublicAppService).share_app_to_square,
            app_id,
            tags,
            account,
        )
        return a._ok_msg("应用已共享到广场")

    @quart_app.post("/apps/<uuid:app_id>/unshare-from-square")
    async def public_app_unshare_app_from_square(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service.public_app_service import PublicAppService

        await a._to_thread(
            a._get_service(PublicAppService).unshare_app_from_square,
            app_id,
            account,
        )
        return a._ok_msg("应用已从广场取消共享")

    @quart_app.post("/public/apps/<string:app_id>/fork")
    async def public_app_fork_public_app(app_id):
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.public_app_schema import ForkAppResp
        from internal.service.public_app_service import PublicAppService

        app = await a._to_thread(
            a._get_service(PublicAppService).fork_public_app, app_id, account
        )
        return a._ok(ForkAppResp().dump({"id": str(app.id), "name": app.name}))

    # =====================================================
    # routing_log_handler
    # =====================================================
    @quart_app.get("/routing-logs/summary")
    async def routing_log_summary():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.service.user_routing_summary_service import UserRoutingSummaryService

        result = await a._to_thread(
            a._get_service(UserRoutingSummaryService).get_user_summary, account.id
        )
        return a._ok(result)

    # =====================================================
    # showcase_handler
    # =====================================================
    @quart_app.post("/showcase/cases")
    async def showcase_create_case():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.showcase_schema import ShowcaseCaseResp
        from internal.service.showcase_service import ShowcaseService

        payload = await request.get_json(force=True, silent=True) or {}
        conversation_id = str(payload.get("conversation_id") or "")
        title = str(payload.get("title") or "")
        summary = str(payload.get("summary") or "")
        query = str(payload.get("query") or "")
        answer = str(payload.get("answer") or "")
        for field_name, value in (
            ("conversation_id", conversation_id),
            ("title", title),
            ("summary", summary),
            ("query", query),
            ("answer", answer),
        ):
            if not value.strip():
                return a._json_resp(
                    code="validate_error",
                    message=f"{field_name}不能为空",
                    data={field_name: [f"{field_name}不能为空"]},
                    status=400,
                )
        tags = payload.get("tags") or []
        rating = payload.get("rating") if payload.get("rating") is not None else 5
        result = await a._to_thread(
            a._get_service(ShowcaseService).create_case,
            account_id=account.id,
            conversation_id=conversation_id,
            title=title,
            summary=summary,
            query=query,
            answer=answer,
            tags=tags,
            rating=rating,
        )
        return a._ok(ShowcaseCaseResp().dump(result))

    @quart_app.get("/showcase/cases")
    async def showcase_list_cases():
        from app.http import asgi_app as a

        account, err = await a._resolve_account()
        if err is not None:
            return err

        from internal.schema.showcase_schema import ShowcaseCasePageResp
        from internal.service.showcase_service import ShowcaseService

        result = await a._to_thread(
            a._get_service(ShowcaseService).list_public_cases,
            page=_int_arg("current_page", 1),
            per_page=_int_arg("page_size", 20),
            tag=request.args.get("tag") or "",
            keyword=request.args.get("keyword") or "",
        )
        return a._ok(ShowcaseCasePageResp().dump(result))

    @quart_app.get("/admin/showcase/cases")
    async def showcase_admin_list_cases():
        from app.http import asgi_app as a

        from internal.schema.showcase_schema import ShowcaseCasePageResp
        from internal.service.showcase_service import ShowcaseService

        result = await a._to_thread(
            a._get_service(ShowcaseService).admin_list_cases,
            page=_int_arg("current_page", 1),
            per_page=_int_arg("page_size", 20),
            status=request.args.get("status") or "all",
        )
        return a._ok(ShowcaseCasePageResp().dump(result))

    @quart_app.post("/admin/showcase/cases/<uuid:case_id>/approve")
    async def showcase_approve_case(case_id):
        from app.http import asgi_app as a

        from internal.schema.showcase_schema import ShowcaseCaseResp
        from internal.service.showcase_service import ShowcaseService

        admin_id = request.headers.get("X-Admin-Id") or request.args.get("admin_id") or ""
        result = await a._to_thread(
            a._get_service(ShowcaseService).approve_case,
            case_id,
            admin_id=admin_id,
        )
        return a._ok(ShowcaseCaseResp().dump(result))

    @quart_app.post("/admin/showcase/cases/<uuid:case_id>/reject")
    async def showcase_reject_case(case_id):
        from app.http import asgi_app as a

        from internal.schema.showcase_schema import ShowcaseCaseResp
        from internal.service.showcase_service import ShowcaseService

        payload = await request.get_json(force=True, silent=True) or {}
        reason = str(payload.get("reason") or "")
        admin_id = request.headers.get("X-Admin-Id") or request.args.get("admin_id") or ""
        result = await a._to_thread(
            a._get_service(ShowcaseService).reject_case,
            case_id,
            admin_id=admin_id,
            reason=reason,
        )
        return a._ok(ShowcaseCaseResp().dump(result))

    @quart_app.post("/admin/showcase/cases/<uuid:case_id>/offline")
    async def showcase_offline_case(case_id):
        from app.http import asgi_app as a

        from internal.schema.showcase_schema import ShowcaseCaseResp
        from internal.service.showcase_service import ShowcaseService

        admin_id = request.headers.get("X-Admin-Id") or request.args.get("admin_id") or ""
        result = await a._to_thread(
            a._get_service(ShowcaseService).offline_case,
            case_id,
            admin_id=admin_id,
        )
        return a._ok(ShowcaseCaseResp().dump(result))
