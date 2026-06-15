from dataclasses import dataclass
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
        )

    def page(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        account_id: UUID | None = None,
        status: str | None = None,
    ) -> dict:
        count_query = self._filtered_query(account_id=account_id, status=status)
        list_query = self._filtered_query(account_id=account_id, status=status)
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

    def _filtered_query(self, *, account_id: UUID | None, status: str | None):
        query = self.db.session.query(RoutingLog)
        if account_id is not None:
            query = query.filter(RoutingLog.account_id == account_id)
        if status:
            query = query.filter(RoutingLog.status == status)
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
            "status": log.status,
            "created_at": datetime_to_timestamp(log.created_at),
        }
