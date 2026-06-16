from internal.entity.routing_quality_entity import RoutingOptimizationSuggestion


class RoutingOptimizationSuggestionService:
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
