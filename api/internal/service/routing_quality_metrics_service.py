from dataclasses import dataclass
from datetime import datetime

from internal.model import RoutingLog, RoutingQualityFeedbackModel
from pkg.sqlalchemy import SQLAlchemy


@dataclass
class RoutingQualityMetricsService:
    db: SQLAlchemy | None = None

    def build_metrics(
        self,
        *,
        routing_logs: list | None = None,
        feedback_items: list | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> dict:
        logs = (
            routing_logs
            if routing_logs is not None
            else self._load_routing_logs(start_at, end_at)
        )
        feedback = (
            feedback_items
            if feedback_items is not None
            else self._load_feedback(start_at, end_at)
        )
        feedback_by_log_id = self._feedback_by_log_id(feedback)
        return {
            "total_count": len(logs),
            "feedback_count": len(feedback),
            "avg_rating": self._round_avg([item.rating for item in feedback]),
            "fallback_rate": self._round_ratio(self._fallback_count(logs), len(logs)),
            "avg_latency_ms": self._round_avg([log.latency_ms for log in logs]),
            "avg_cost_credits": self._round_avg([
                self._cost_credits(log) for log in logs
            ]),
            "quality_by_task_type": self._group_quality(
                logs,
                feedback_by_log_id,
                self._task_type,
            ),
            "quality_by_agent_pool": self._group_quality(
                logs,
                feedback_by_log_id,
                self._agent_pools,
            ),
            "quality_by_tool_pool": self._group_quality(
                logs,
                feedback_by_log_id,
                self._tool_pools,
            ),
            "quality_by_model": self._group_quality(
                logs,
                feedback_by_log_id,
                self._model_tier,
            ),
        }

    def _load_routing_logs(self, start_at, end_at) -> list:
        if self.db is None:
            return []
        query = self.db.session.query(RoutingLog)
        if start_at:
            query = query.filter(RoutingLog.created_at >= start_at)
        if end_at:
            query = query.filter(RoutingLog.created_at <= end_at)
        return query.all()

    def _load_feedback(self, start_at, end_at) -> list:
        if self.db is None:
            return []
        query = self.db.session.query(RoutingQualityFeedbackModel)
        if start_at:
            query = query.filter(RoutingQualityFeedbackModel.created_at >= start_at)
        if end_at:
            query = query.filter(RoutingQualityFeedbackModel.created_at <= end_at)
        return query.all()

    @staticmethod
    def _feedback_by_log_id(feedback_items: list) -> dict:
        result = {}
        for item in feedback_items:
            result.setdefault(str(item.routing_log_id), []).append(item.rating)
        return result

    @staticmethod
    def _fallback_count(logs: list) -> int:
        return len([log for log in logs if getattr(log, "fallback_reason", "")])

    @staticmethod
    def _round_avg(values: list) -> float:
        clean_values = [value for value in values if value is not None]
        if not clean_values:
            return 0
        return round(sum(clean_values) / len(clean_values), 2)

    @staticmethod
    def _round_ratio(count: int, total: int) -> float:
        if total == 0:
            return 0
        return round(count / total, 2)

    @staticmethod
    def _cost_credits(log) -> float:
        cost_summary = getattr(log, "cost_summary", None) or {}
        return cost_summary.get("estimated_credits", 0)

    @staticmethod
    def _decision(log) -> dict:
        return getattr(log, "routing_decision", None) or {}

    def _task_type(self, log) -> list[str]:
        return [self._decision(log).get("intent") or "unknown"]

    def _agent_pools(self, log) -> list[str]:
        return self._decision(log).get("agent_subset", {}).get(
            "matched_agent_pools",
            ["unknown"],
        ) or ["unknown"]

    def _tool_pools(self, log) -> list[str]:
        return self._decision(log).get("tool_subset", {}).get(
            "matched_tool_pools",
            ["unknown"],
        ) or ["unknown"]

    def _model_tier(self, log) -> list[str]:
        return [self._decision(log).get("recommended_model_tier") or "unknown"]

    def _group_quality(self, logs: list, feedback_by_log_id: dict, key_fn) -> dict:
        groups = {}
        for log in logs:
            ratings = feedback_by_log_id.get(str(log.id), [])
            for key in key_fn(log):
                group = groups.setdefault(key, {"count": 0, "ratings": []})
                group["count"] += 1
                group["ratings"].extend(ratings)
        return {
            key: {
                "count": value["count"],
                "avg_rating": self._round_avg(value["ratings"]),
            }
            for key, value in groups.items()
        }
