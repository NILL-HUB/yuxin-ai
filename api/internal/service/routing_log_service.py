from dataclasses import dataclass
from datetime import datetime, UTC
from uuid import UUID

from injector import inject
from sqlalchemy import func, cast, Integer, literal_column, case

from internal.lib.helper import datetime_to_timestamp
from internal.model import RoutingLog
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


@inject
@dataclass
class RoutingLogService(BaseService):
    db: SQLAlchemy

    def create_pending(
        self,
        *,
        account_id,
        user_query: str | None = None,
        invoke_from: str | None = None,
        message_id=None,
    ):
        """创建 pending 状态的 routing_log 记录，供编排过程中追加事件。

        编排开始时调用，获取 routing_log_id 供 _emit 追加离散事件。
        编排完成后通过 finalize 更新为最终状态。
        """
        return self.create(
            RoutingLog,
            account_id=account_id,
            message_id=message_id,
            routing_decision={"status": "pending"},
            agent_candidates=[],
            filtered_out_agents=[],
            tool_candidates=[],
            filtered_out_tools=[],
            knowledge_hits=[],
            billing_events=[],
            status="pending",
            user_query=user_query,
            invoke_from=invoke_from,
        )

    def finalize(self, routing_log_id, **fields) -> None:
        """更新 routing_log 记录为最终状态。"""
        with self.db.auto_commit():
            log = (
                self.db.session.query(RoutingLog)
                .filter(RoutingLog.id == routing_log_id)
                .first()
            )
            if log is None:
                return
            for key, value in fields.items():
                if hasattr(log, key):
                    setattr(log, key, value)

    def record(
        self,
        *,
        account_id: UUID,
        message_id: UUID | None,
        routing_decision: dict,
        agent_candidates: list[dict],
        filtered_out_agents: list[dict],
        tool_candidates: list[dict],
        filtered_out_tools: list[dict],
        knowledge_hits: list[dict],
        billing_events: list[dict],
        status: str = "success",
        user_query: str | None = None,
        task_classification: dict | None = None,
        model_selection: dict | None = None,
        agent_pool_hits: list[dict] | None = None,
        tool_pool_hits: list[dict] | None = None,
        key_usage: dict | None = None,
        cost_summary: dict | None = None,
        latency_ms: int = 0,
        fallback_reason: str | None = None,
        redaction_enabled: bool = False,
        retention_expires_at: datetime | None = None,
    ) -> RoutingLog:
        return self.create(
            RoutingLog,
            account_id=account_id,
            message_id=message_id,
            routing_decision=routing_decision,
            agent_candidates=agent_candidates,
            filtered_out_agents=filtered_out_agents,
            tool_candidates=tool_candidates,
            filtered_out_tools=filtered_out_tools,
            knowledge_hits=knowledge_hits,
            billing_events=billing_events,
            status=status,
            user_query=user_query,
            task_classification=task_classification or {},
            model_selection=model_selection or {},
            agent_pool_hits=agent_pool_hits or [],
            tool_pool_hits=tool_pool_hits or [],
            key_usage=key_usage or {},
            cost_summary=cost_summary or {},
            latency_ms=latency_ms,
            fallback_reason=fallback_reason,
            redaction_enabled=redaction_enabled,
            retention_expires_at=retention_expires_at,
        )

    def page(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        account_id: UUID | None = None,
        status: str | None = None,
        agent_id: str | None = None,
        agent_pool: str | None = None,
        tool_name: str | None = None,
        tool_pool: str | None = None,
        model_id: str | None = None,
        key_id: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> dict:
        filters = {
            "account_id": account_id,
            "status": status,
            "agent_id": agent_id,
            "agent_pool": agent_pool,
            "tool_name": tool_name,
            "tool_pool": tool_pool,
            "model_id": model_id,
            "key_id": key_id,
            "start_at": start_at,
            "end_at": end_at,
        }
        count_query = self._filtered_query(**filters)
        list_query = self._filtered_query(**filters)
        total_record = count_query.count()
        logs = (
            list_query.order_by(RoutingLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        serialized_list = [self._serialize(log) for log in logs]
        return {
            "list": serialized_list,
            "paginator": {
                "current_page": page,
                "page_size": page_size,
                "total_record": total_record,
                "total_page": (total_record + page_size - 1) // page_size,
            },
            "summary": self._build_summary(serialized_list, total_record),
        }

    # ------------------------------------------------------------------
    # 观测中心聚合接口：stats_overview / trend / distribution
    # 与 page() 的「当前页窗口统计」不同，这里全部基于 SQL 全量聚合，
    # 支持 start_at/end_at（秒级时间戳，naive UTC）时间窗过滤。
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_window(start_at, end_at):
        """把秒级时间戳/字符串/datetime 统一成 naive UTC datetime。"""
        if start_at is None or start_at == "" or start_at == 0:
            start_at = None
        else:
            if isinstance(start_at, datetime):
                dt = start_at
                if dt.tzinfo is not None:
                    dt = dt.astimezone(UTC).replace(tzinfo=None)
            else:
                try:
                    dt = datetime.fromtimestamp(int(start_at), tz=UTC).replace(tzinfo=None)
                except (TypeError, ValueError, OSError):
                    start_at = None
                    dt = None
            if dt is not None:
                start_at = dt
        if end_at is None or end_at == "" or end_at == 0:
            end_at = None
        else:
            if isinstance(end_at, datetime):
                dt = end_at
                if dt.tzinfo is not None:
                    dt = dt.astimezone(UTC).replace(tzinfo=None)
            else:
                try:
                    dt = datetime.fromtimestamp(int(end_at), tz=UTC).replace(tzinfo=None)
                except (TypeError, ValueError, OSError):
                    end_at = None
                    dt = None
            if dt is not None:
                end_at = dt
        return start_at, end_at

    @staticmethod
    def _credits_sql_expr():
        # cost_summary 实际写入 estimated_credits，老数据兼容 total_credits。
        return literal_column(
            "CAST(COALESCE(NULLIF(cost_summary->>'estimated_credits', ''), "
            "NULLIF(cost_summary->>'total_credits', ''), '0') AS NUMERIC)"
        )

    @staticmethod
    def _windowed(query, start_at, end_at):
        start_at, end_at = RoutingLogService._normalize_window(start_at, end_at)
        if start_at is not None:
            query = query.filter(RoutingLog.created_at >= start_at)
        if end_at is not None:
            query = query.filter(RoutingLog.created_at <= end_at)
        return query

    @staticmethod
    def _normalize_dimension_value(value):
        """把空串/None 统一成 unknown，避免图表出现空维度名。"""
        if value is None or str(value).strip() == "":
            return "unknown"
        return str(value)

    def stats_overview(
        self,
        *,
        start_at=None,
        end_at=None,
        status: str | None = None,
        invoke_from: str | None = None,
    ) -> dict:
        """全量窗口聚合（SQL 级）：成功率/回退率/积分/延迟/命中率。"""
        credits_col = cast(self._credits_sql_expr(), Integer)

        agg = self.db.session.query(
            func.count().label("total_count"),
            func.coalesce(
                func.sum(func.cast(case(
                    (RoutingLog.status == "success", 1),
                    else_=0,
                ), Integer)),
                0,
            ).label("success_count"),
            func.coalesce(
                func.sum(func.cast(case(
                    (RoutingLog.status == "fallback", 1),
                    else_=0,
                ), Integer)),
                0,
            ).label("fallback_count"),
            func.coalesce(func.sum(credits_col), 0).label("total_credits"),
            func.coalesce(func.avg(RoutingLog.latency_ms), 0).label("avg_latency_ms"),
            func.coalesce(func.avg(func.cast(case(
                (func.jsonb_array_length(RoutingLog.agent_pool_hits) > 0, 1),
                else_=0,
            ), Integer)), 0).label("agent_pool_hit_rate"),
            func.coalesce(func.avg(func.cast(case(
                (func.jsonb_array_length(RoutingLog.tool_pool_hits) > 0, 1),
                else_=0,
            ), Integer)), 0).label("tool_pool_hit_rate"),
        )
        agg = self._windowed(agg, start_at, end_at)
        if status:
            agg = agg.filter(RoutingLog.status == status)
        if invoke_from:
            agg = agg.filter(RoutingLog.invoke_from == invoke_from)
        row = agg.first()

        total_count = int(row.total_count or 0)
        total_credits = int(row.total_credits or 0)
        avg_latency_ms = round(float(row.avg_latency_ms or 0), 2)
        agent_pool_hit_rate = round(float(row.agent_pool_hit_rate or 0), 4)
        tool_pool_hit_rate = round(float(row.tool_pool_hit_rate or 0), 4)
        success_count = int(row.success_count or 0)
        fallback_count = int(row.fallback_count or 0)

        status_rows = self.db.session.query(
            RoutingLog.status,
            func.count().label("count"),
            func.coalesce(func.sum(credits_col), 0).label("credits"),
        ).select_from(RoutingLog)
        status_rows = self._windowed(status_rows, start_at, end_at)
        if status:
            status_rows = status_rows.filter(RoutingLog.status == status)
        if invoke_from:
            status_rows = status_rows.filter(RoutingLog.invoke_from == invoke_from)
        status_rows = status_rows.group_by(RoutingLog.status).all()

        by_status = {}
        for s in status_rows:
            key = self._normalize_dimension_value(s.status)
            by_status[key] = {
                "count": int(s.count or 0),
                "credits": int(s.credits or 0),
            }

        return {
            "total_count": total_count,
            "success_count": success_count,
            "fallback_count": fallback_count,
            "success_rate": round(success_count / total_count, 4) if total_count else 0.0,
            "fallback_rate": round(fallback_count / total_count, 4) if total_count else 0.0,
            "total_credits": total_credits,
            "avg_latency_ms": avg_latency_ms,
            "agent_pool_hit_rate": agent_pool_hit_rate,
            "tool_pool_hit_rate": tool_pool_hit_rate,
            "by_status": by_status,
        }

    def trend(
        self,
        *,
        start_at=None,
        end_at=None,
        granularity: str = "day",
        status: str | None = None,
        invoke_from: str | None = None,
    ) -> dict:
        """按 day/hour 聚合时间序列：请求量 / success / fallback / credits / avg_latency。"""
        trunc = "day" if granularity != "hour" else "hour"
        credits_col = cast(self._credits_sql_expr(), Integer)
        ts_col = func.date_trunc(trunc, RoutingLog.created_at).label("ts")

        query = self.db.session.query(
            ts_col,
            func.count().label("request_count"),
            func.coalesce(
                func.sum(func.cast(case(
                    (RoutingLog.status == "success", 1),
                    else_=0,
                ), Integer)),
                0,
            ).label("success_count"),
            func.coalesce(
                func.sum(func.cast(case(
                    (RoutingLog.status == "fallback", 1),
                    else_=0,
                ), Integer)),
                0,
            ).label("fallback_count"),
            func.coalesce(func.sum(credits_col), 0).label("total_credits"),
            func.coalesce(func.avg(RoutingLog.latency_ms), 0).label("avg_latency_ms"),
        ).select_from(RoutingLog)
        query = self._windowed(query, start_at, end_at)
        if status:
            query = query.filter(RoutingLog.status == status)
        if invoke_from:
            query = query.filter(RoutingLog.invoke_from == invoke_from)
        query = query.group_by(ts_col).order_by(ts_col)

        rows = query.all()
        points = []
        for r in rows:
            ts_val = r.ts
            if ts_val and ts_val.tzinfo is None:
                ts_val = ts_val.replace(tzinfo=UTC)
            points.append({
                "timestamp": int(ts_val.timestamp()) if ts_val else 0,
                "request_count": int(r.request_count or 0),
                "success_count": int(r.success_count or 0),
                "fallback_count": int(r.fallback_count or 0),
                "total_credits": int(r.total_credits or 0),
                "avg_latency_ms": round(float(r.avg_latency_ms or 0), 2),
            })

        return {"granularity": trunc, "points": points}

    def distribution(
        self,
        *,
        start_at=None,
        end_at=None,
        dimension: str = "execution_mode",
        limit: int = 20,
    ) -> dict:
        """按维度做分布聚合（SQL 级，JSONB #>> 取值，空值归 unknown）。"""
        credits_col = cast(self._credits_sql_expr(), Integer)
        dimension_expr = self._dimension_expression(dimension)

        query = self.db.session.query(
            dimension_expr.label("name"),
            func.count().label("count"),
            func.coalesce(func.sum(credits_col), 0).label("credits"),
            func.coalesce(func.avg(RoutingLog.latency_ms), 0).label("avg_latency_ms"),
        ).select_from(RoutingLog)
        query = self._windowed(query, start_at, end_at)
        query = query.group_by(dimension_expr).order_by(func.count().desc())
        rows = query.limit(limit).all()

        total_rows = self.db.session.query(func.count().label("total")).select_from(RoutingLog)
        total_rows = self._windowed(total_rows, start_at, end_at)
        grand_total = int(total_rows.first().total or 0)

        items = []
        for r in rows:
            count = int(r.count or 0)
            credits = int(r.credits or 0)
            items.append({
                "name": self._normalize_dimension_value(r.name),
                "count": count,
                "credits": credits,
                "avg_latency_ms": round(float(r.avg_latency_ms or 0), 2),
                "percentage": round(count / grand_total * 100, 2) if grand_total else 0.0,
            })

        return {
            "dimension": dimension,
            "items": items,
            "total_count": grand_total,
        }

    def _dimension_expression(self, dimension: str):
        """构造 JSONB #>> 取值表达式（与 cost-stats 风格一致）。"""
        if dimension == "status":
            return self._normalize_dimension_value(RoutingLog.status).label("name")
        if dimension == "invoke_from":
            return self._normalize_dimension_value(RoutingLog.invoke_from).label("name")
        if dimension == "execution_mode":
            return self._dimension_value_expr("routing_decision->>'execution_mode'").label("name")
        if dimension == "intent":
            return self._dimension_value_expr("routing_decision->>'intent'").label("name")
        if dimension == "model_tier":
            return self._dimension_value_expr(
                "routing_decision->>'recommended_model_tier'"
            ).label("name")
        if dimension == "complexity":
            return self._dimension_value_expr(
                "COALESCE(task_classification->>'complexity', "
                "routing_decision->>'complexity')"
            ).label("name")
        if dimension == "model":
            return self._dimension_value_expr(
                "COALESCE(NULLIF(model_selection->>'model_display_name', ''), "
                "NULLIF(model_selection->>'execution_model', ''), "
                "NULLIF(model_selection->>'model_id', ''), "
                "NULLIF(model_selection->>'model_tier', ''))"
            ).label("name")
        # fallback 到 account_id
        return self._dimension_value_expr("routing_log.account_id::text").label("name")

    @staticmethod
    def _dimension_value_expr(expr: str):
        return literal_column(f"COALESCE(NULLIF(({expr})::text, ''), 'unknown')")

    def _filtered_query(
        self,
        *,
        account_id: UUID | None,
        status: str | None,
        agent_id: str | None,
        agent_pool: str | None,
        tool_name: str | None,
        tool_pool: str | None,
        model_id: str | None,
        key_id: str | None,
        start_at: datetime | None,
        end_at: datetime | None,
    ):
        query = self.db.session.query(RoutingLog)
        if account_id is not None:
            query = query.filter(RoutingLog.account_id == account_id)
        if status:
            query = query.filter(RoutingLog.status == status)
        if agent_id:
            query = query.filter(
                RoutingLog.agent_candidates.contains([{"agent_id": agent_id}])
            )
        if agent_pool:
            query = query.filter(
                RoutingLog.agent_pool_hits.contains([{"pool": agent_pool}])
            )
        if tool_name:
            query = query.filter(
                RoutingLog.tool_candidates.contains([{"name": tool_name}])
            )
        if tool_pool:
            query = query.filter(
                RoutingLog.tool_pool_hits.contains([{"pool": tool_pool}])
            )
        if model_id:
            query = query.filter(
                RoutingLog.model_selection.contains({"model_id": model_id})
            )
        if key_id:
            query = query.filter(RoutingLog.key_usage.contains({"key_id": key_id}))
        if start_at:
            query = query.filter(RoutingLog.created_at >= start_at)
        if end_at:
            query = query.filter(RoutingLog.created_at <= end_at)
        return query

    @staticmethod
    def _serialize(log: RoutingLog) -> dict:
        return {
            "id": str(log.id),
            "account_id": str(log.account_id),
            "message_id": str(log.message_id) if log.message_id else "",
            "routing_decision": log.routing_decision,
            "agent_candidates": log.agent_candidates,
            "filtered_out_agents": log.filtered_out_agents,
            "tool_candidates": log.tool_candidates,
            "filtered_out_tools": log.filtered_out_tools,
            "knowledge_hits": log.knowledge_hits,
            "billing_events": log.billing_events,
            "invoke_from": log.invoke_from,
            "user_query": log.user_query,
            "task_classification": log.task_classification,
            "model_selection": log.model_selection,
            "agent_pool_hits": log.agent_pool_hits,
            "tool_pool_hits": log.tool_pool_hits,
            "key_usage": log.key_usage,
            "cost_summary": log.cost_summary,
            "latency_ms": log.latency_ms,
            "fallback_reason": log.fallback_reason or "",
            "redaction_enabled": log.redaction_enabled,
            "retention_expires_at": datetime_to_timestamp(log.retention_expires_at),
            "status": log.status,
            "created_at": datetime_to_timestamp(log.created_at),
        }

    @staticmethod
    def _build_summary(items: list[dict], total_record: int) -> dict:
        success_count = 0
        fallback_count = 0
        total_credits = 0.0
        latency_sum = 0.0
        latency_n = 0
        agent_pool_hit = 0
        tool_pool_hit = 0
        item_count = len(items)
        for item in items:
            try:
                if item.get("status") == "success":
                    success_count += 1
            except Exception:
                pass
            try:
                if item.get("status") == "fallback":
                    fallback_count += 1
            except Exception:
                pass
            try:
                cost_summary = item.get("cost_summary") or {}
                credits = cost_summary.get("credits")
                if credits is not None:
                    total_credits += float(credits)
            except Exception:
                pass
            try:
                latency_ms = item.get("latency_ms")
                if latency_ms is not None:
                    latency_sum += float(latency_ms)
                    latency_n += 1
            except Exception:
                pass
            try:
                if item.get("agent_pool_hits"):
                    agent_pool_hit += 1
            except Exception:
                pass
            try:
                if item.get("tool_pool_hits"):
                    tool_pool_hit += 1
            except Exception:
                pass
        try:
            avg_latency_ms = latency_sum / latency_n if latency_n else 0.0
        except Exception:
            avg_latency_ms = 0.0
        try:
            agent_pool_hit_rate = (
                agent_pool_hit / item_count if item_count else 0.0
            )
        except Exception:
            agent_pool_hit_rate = 0.0
        try:
            tool_pool_hit_rate = (
                tool_pool_hit / item_count if item_count else 0.0
            )
        except Exception:
            tool_pool_hit_rate = 0.0
        return {
            "total_count": total_record,
            "success_count": success_count,
            "fallback_count": fallback_count,
            "total_credits": total_credits,
            "avg_latency_ms": avg_latency_ms,
            "agent_pool_hit_rate": agent_pool_hit_rate,
            "tool_pool_hit_rate": tool_pool_hit_rate,
        }
