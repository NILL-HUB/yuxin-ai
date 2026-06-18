from datetime import UTC, datetime
from uuid import UUID

from injector import inject

from internal.entity.routing_quality_entity import RoutingOptimizationSuggestion
from internal.exception import NotFoundException
from internal.model import PolicyChangeDraftModel, RoutingOptimizationSuggestionModel
from pkg.sqlalchemy import SQLAlchemy


class RoutingOptimizationSuggestionService:
    @inject
    def __init__(self, db: SQLAlchemy = None):
        self.db = db

    def generate_suggestions(self, metrics: dict) -> list[dict]:
        suggestions = []
        if metrics.get("feedback_count", 0) < 3:
            suggestions.append(self._suggestion(
                target_type="routing_quality",
                target_id="feedback",
                suggestion_type="collect_more_feedback",
                severity="medium",
                reason="Feedback sample is too small for confident tuning",
                evidence={
                    "feedback_count": metrics.get("feedback_count", 0),
                    "total_count": metrics.get("total_count", 0),
                },
            ))
        if metrics.get("fallback_rate", 0) >= 0.3:
            suggestions.append(self._suggestion(
                target_type="routing",
                target_id="fallback_rate",
                suggestion_type="review_fallback_rate",
                severity="high",
                reason="Fallback rate is above the review threshold",
                evidence={"fallback_rate": metrics.get("fallback_rate", 0)},
            ))
        suggestions.extend(self._model_cost_suggestions(metrics))
        suggestions.extend(self._tool_health_suggestions(metrics))
        return suggestions

    def accept_suggestion(self, suggestion_id: UUID, admin_user_id: UUID) -> dict:
        suggestion = self._get_suggestion(suggestion_id)
        if suggestion.status not in ("open", "accepted"):
            raise ValueError(f"建议当前状态为 {suggestion.status}，无法采纳")
        suggestion.status = "accepted"
        self.db.session.commit()
        return {"suggestion_id": str(suggestion.id), "status": suggestion.status}

    def dismiss_suggestion(self, suggestion_id: UUID, admin_user_id: UUID, reason: str) -> dict:
        suggestion = self._get_suggestion(suggestion_id)
        if suggestion.status == "dismissed":
            return {"suggestion_id": str(suggestion.id), "status": suggestion.status}
        if suggestion.status == "applied":
            raise ValueError("已应用的建议无法驳回")
        suggestion.status = "dismissed"
        suggestion.dismiss_reason = reason or ""
        self.db.session.commit()
        return {"suggestion_id": str(suggestion.id), "status": suggestion.status}

    def mark_applied(
        self,
        suggestion_id: UUID,
        admin_user_id: UUID,
        draft_id: UUID,
    ) -> dict:
        suggestion = self._get_suggestion(suggestion_id)
        if suggestion.status != "accepted":
            raise ValueError(f"建议当前状态为 {suggestion.status}，需先采纳后才能应用")
        suggestion.status = "applied"
        suggestion.applied_by = admin_user_id
        suggestion.applied_at = datetime.now(UTC).replace(tzinfo=None)
        suggestion.policy_change_draft_id = draft_id
        self.db.session.commit()
        return {"suggestion_id": str(suggestion.id), "status": suggestion.status}

    def list_suggestions(self, status: str = "") -> list[dict]:
        query = self.db.session.query(RoutingOptimizationSuggestionModel)
        if status:
            query = query.filter(RoutingOptimizationSuggestionModel.status == status)
        suggestions = query.order_by(RoutingOptimizationSuggestionModel.created_at.desc()).all()
        return [self._model_to_dict(s) for s in suggestions]

    def _get_suggestion(self, suggestion_id: UUID) -> RoutingOptimizationSuggestionModel:
        suggestion = (
            self.db.session.query(RoutingOptimizationSuggestionModel)
            .filter_by(id=suggestion_id)
            .one_or_none()
        )
        if suggestion is None:
            raise NotFoundException("调优建议不存在")
        return suggestion

    @staticmethod
    def _model_to_dict(suggestion: RoutingOptimizationSuggestionModel) -> dict:
        return {
            "id": str(suggestion.id),
            "target_type": suggestion.target_type,
            "target_id": suggestion.target_id,
            "suggestion_type": suggestion.suggestion_type,
            "severity": suggestion.severity,
            "reason": suggestion.reason,
            "evidence": suggestion.evidence or {},
            "status": suggestion.status,
            "dismiss_reason": suggestion.dismiss_reason or "",
            "applied_by": str(suggestion.applied_by) if suggestion.applied_by else None,
            "applied_at": suggestion.applied_at.isoformat() if suggestion.applied_at else None,
            "policy_change_draft_id": str(suggestion.policy_change_draft_id) if suggestion.policy_change_draft_id else None,
        }

    def _model_cost_suggestions(self, metrics: dict) -> list[dict]:
        suggestions = []
        for model, values in metrics.get("quality_by_model", {}).items():
            avg_rating = values.get("avg_rating", 0)
            avg_cost = values.get("avg_cost_credits", 0)
            if avg_rating and avg_rating < 3 and avg_cost >= 5:
                suggestions.append(self._suggestion(
                    target_type="model",
                    target_id=model,
                    suggestion_type="review_model_cost",
                    severity="medium",
                    reason="Model has high cost with low quality rating",
                    evidence={
                        "avg_rating": avg_rating,
                        "avg_cost_credits": avg_cost,
                        "count": values.get("count", 0),
                    },
                ))
        return suggestions

    def _tool_health_suggestions(self, metrics: dict) -> list[dict]:
        suggestions = []
        for tool_pool, values in metrics.get("quality_by_tool_pool", {}).items():
            avg_rating = values.get("avg_rating", 0)
            if avg_rating and avg_rating < 3 and values.get("count", 0) >= 3:
                suggestions.append(self._suggestion(
                    target_type="tool_pool",
                    target_id=tool_pool,
                    suggestion_type="review_tool_health",
                    severity="medium",
                    reason="Tool pool quality rating is below the review threshold",
                    evidence={
                        "avg_rating": avg_rating,
                        "count": values.get("count", 0),
                    },
                ))
        return suggestions

    @staticmethod
    def _suggestion(
        *,
        target_type: str,
        target_id: str,
        suggestion_type: str,
        severity: str,
        reason: str,
        evidence: dict,
    ) -> dict:
        return RoutingOptimizationSuggestion(
            target_type=target_type,
            target_id=target_id,
            suggestion_type=suggestion_type,
            severity=severity,
            reason=reason,
            evidence=evidence,
        ).to_dict()
