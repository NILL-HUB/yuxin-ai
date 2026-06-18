from dataclasses import dataclass
from uuid import UUID

from injector import inject

from internal.lib.helper import datetime_to_timestamp
from internal.model import RoutingLog
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


@inject
@dataclass
class UserRoutingSummaryService(BaseService):
    db: SQLAlchemy

    def get_user_summary(self, account_id: UUID, limit: int = 20) -> dict:
        normalized_limit = max(min(int(limit), 100), 1)
        logs = (
            self.db.session.query(RoutingLog)
            .filter(RoutingLog.account_id == account_id)
            .order_by(RoutingLog.created_at.desc())
            .limit(normalized_limit)
            .all()
        )
        items = [self._simplify(log) for log in logs]
        total_credits = sum(item["total_credits"] for item in items)
        success_count = sum(1 for item in items if item["status"] == "success")
        fallback_count = sum(1 for item in items if item["status"] == "fallback")
        return {
            "recent": items,
            "summary": {
                "total_count": len(items),
                "success_count": success_count,
                "fallback_count": fallback_count,
                "total_credits": round(total_credits, 4),
            },
        }

    @staticmethod
    def _simplify(log: RoutingLog) -> dict:
        cost_summary = log.cost_summary or {}
        decision = log.routing_decision or {}
        events = list(decision.get("routing_events") or [])
        last_event = events[-1].get("event_type") if events else ""
        progress = UserRoutingSummaryService._progress(log.status, last_event)
        return {
            "id": str(log.id),
            "status": log.status,
            "created_at": datetime_to_timestamp(log.created_at),
            "total_credits": float(cost_summary.get("total_credits") or 0),
            "progress": progress,
            "event_count": len(events),
        }

    @staticmethod
    def _progress(status: str, last_event: str) -> str:
        if status == "success":
            return "completed"
        if status == "fallback":
            return "fallback"
        if last_event == "routing_failed":
            return "failed"
        if last_event == "synthesis_completed":
            return "completed"
        if last_event:
            return "in_progress"
        return "pending"
