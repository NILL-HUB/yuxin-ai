from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from injector import inject
from sqlalchemy.orm.attributes import flag_modified

from internal.entity.routing_observability_entity import ROUTING_EVENT_TYPES
from internal.model import RoutingLog
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


@inject
@dataclass
class RoutingEventLogger(BaseService):
    db: SQLAlchemy

    def log_event(self, event_type: str, routing_log_id: UUID, detail: dict | None = None) -> dict | None:
        if routing_log_id is None or event_type not in ROUTING_EVENT_TYPES:
            return None
        with self.db.auto_commit():
            log = (
                self.db.session.query(RoutingLog)
                .filter(RoutingLog.id == routing_log_id)
                .first()
            )
            if log is None:
                return None
            event = self._build_event(event_type, routing_log_id, detail)
            self._append_event(log, event)
            return event

    def log_events(self, events: list[dict]) -> list[dict]:
        if not events:
            return []
        grouped: dict[UUID, list[dict]] = {}
        order: list[UUID] = []
        for raw in events:
            routing_log_id = raw.get("routing_log_id")
            event_type = raw.get("event_type")
            if routing_log_id is None or event_type not in ROUTING_EVENT_TYPES:
                continue
            grouped.setdefault(routing_log_id, []).append(raw)
            if routing_log_id not in order:
                order.append(routing_log_id)
        appended: list[dict] = []
        with self.db.auto_commit():
            for routing_log_id in order:
                log = (
                    self.db.session.query(RoutingLog)
                    .filter(RoutingLog.id == routing_log_id)
                    .first()
                )
                if log is None:
                    continue
                for raw in grouped[routing_log_id]:
                    event = self._build_event(
                        raw.get("event_type"),
                        routing_log_id,
                        raw.get("detail"),
                        occurred_at=raw.get("occurred_at"),
                    )
                    self._append_event(log, event)
                    appended.append(event)
        return appended

    @staticmethod
    def _build_event(
        event_type: str,
        routing_log_id: UUID,
        detail: dict | None,
        occurred_at: str | None = None,
    ) -> dict:
        return {
            "event_type": event_type,
            "routing_log_id": str(routing_log_id),
            "detail": detail or {},
            "occurred_at": occurred_at or datetime.now(UTC).isoformat(),
        }

    @staticmethod
    def _append_event(log: RoutingLog, event: dict) -> None:
        decision = dict(log.routing_decision or {})
        events = list(decision.get("routing_events") or [])
        events.append(event)
        decision["routing_events"] = events
        log.routing_decision = decision
        flag_modified(log, "routing_decision")
