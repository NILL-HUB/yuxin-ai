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
        return {
            "list": [self._serialize(log) for log in logs],
            "paginator": {
                "current_page": page,
                "page_size": page_size,
                "total_record": total_record,
                "total_page": (total_record + page_size - 1) // page_size,
            },
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
