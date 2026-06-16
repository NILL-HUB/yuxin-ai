from dataclasses import dataclass
from uuid import UUID

from injector import inject

from internal.entity.routing_quality_entity import RoutingQualityFeedback
from internal.model import RoutingLog, RoutingQualityFeedbackModel
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


@inject
@dataclass
class RoutingQualityFeedbackService(BaseService):
    db: SQLAlchemy

    def create_feedback(
        self,
        *,
        routing_log_id: UUID,
        source: str,
        rating: int,
        dimension_scores: dict,
        comment: str,
        metadata: dict,
        created_by: UUID | None,
    ) -> dict:
        feedback = RoutingQualityFeedback(
            routing_log_id=str(routing_log_id),
            source=source,
            rating=rating,
            dimension_scores=dimension_scores or {},
            comment=comment or "",
            metadata=metadata or {},
        )
        if self._find_routing_log(routing_log_id) is None:
            raise ValueError("Routing log does not exist")
        created = self.create(
            RoutingQualityFeedbackModel,
            routing_log_id=routing_log_id,
            source=feedback.source,
            rating=feedback.rating,
            dimension_scores=feedback.dimension_scores,
            comment=feedback.comment,
            meta=feedback.metadata,
            created_by=created_by,
        )
        return self.serialize_feedback(created)

    def list_feedback(
        self,
        *,
        routing_log_id: UUID | None = None,
        source: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[dict]:
        query = self.db.session.query(RoutingQualityFeedbackModel)
        if routing_log_id:
            query = query.filter(
                RoutingQualityFeedbackModel.routing_log_id == routing_log_id
            )
        if source:
            query = query.filter(RoutingQualityFeedbackModel.source == source)
        safe_page = max(page, 1)
        safe_page_size = min(max(page_size, 1), 100)
        feedback_items = (
            query.order_by(RoutingQualityFeedbackModel.created_at.desc())
            .limit(safe_page_size)
            .offset((safe_page - 1) * safe_page_size)
            .all()
        )
        return [self.serialize_feedback(feedback) for feedback in feedback_items]

    @staticmethod
    def serialize_feedback(feedback) -> dict:
        return {
            "id": str(feedback.id) if getattr(feedback, "id", None) else None,
            "routing_log_id": str(feedback.routing_log_id),
            "source": feedback.source,
            "rating": feedback.rating,
            "dimension_scores": feedback.dimension_scores or {},
            "comment": feedback.comment or "",
            "metadata": getattr(feedback, "meta", None) or {},
            "created_by": str(feedback.created_by)
            if getattr(feedback, "created_by", None)
            else None,
            "created_at": feedback.created_at.isoformat()
            if getattr(feedback, "created_at", None)
            else None,
        }

    def _find_routing_log(self, routing_log_id: UUID):
        return (
            self.db.session.query(RoutingLog)
            .filter(RoutingLog.id == routing_log_id)
            .first()
        )
