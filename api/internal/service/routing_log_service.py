from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from injector import inject

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
    ):
        """创建 pending 状态的 routing_log 记录，供编排过程中追加事件。

        编排开始时调用，获取 routing_log_id 供 _emit 追加离散事件。
        编排完成后通过 finalize 更新为最终状态。
        """
        return self.create(
            RoutingLog,
            account_id=account_id,
            message_id=None,
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
