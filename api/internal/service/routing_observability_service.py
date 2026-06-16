from typing import Any

from internal.entity.routing_observability_entity import (
    RoutingLogMetricsSummary,
)


class RoutingObservabilityService:
    def summarize(self, logs: list[Any]) -> dict:
        if not logs:
            result = RoutingLogMetricsSummary().to_dict()
            result["status_count"] = {}
            return result

        total_count = len(logs)
        success_count = sum(1 for log in logs if log.status == "success")
        failure_count = sum(1 for log in logs if log.status != "success")
        fallback_count = sum(1 for log in logs if getattr(log, "fallback_reason", ""))
        total_credits = sum(self._credits(log) for log in logs)
        avg_latency_ms = (
            sum(getattr(log, "latency_ms", 0) for log in logs) / total_count
        )
        status_count = self._status_count(logs)
        summary = RoutingLogMetricsSummary(
            total_count=total_count,
            success_count=success_count,
            failure_count=failure_count,
            fallback_count=fallback_count,
            total_credits=total_credits,
            avg_latency_ms=round(avg_latency_ms, 2),
            agent_pool_hit_rate=self._hit_rate(logs, "agent_pool_hits"),
            tool_pool_hit_rate=self._hit_rate(logs, "tool_pool_hits"),
            agent_hit_rate=self._hit_rate(logs, "agent_candidates"),
            tool_success_rate=self._tool_success_rate(logs),
        ).to_dict()
        summary["status_count"] = status_count
        return summary

    @staticmethod
    def _credits(log: Any) -> float:
        cost_summary = getattr(log, "cost_summary", {}) or {}
        return cost_summary.get("total_credits", 0)

    @staticmethod
    def _hit_rate(logs: list[Any], attribute: str) -> float:
        hits = sum(1 for log in logs if getattr(log, attribute, []))
        return round(hits / len(logs), 2)

    @staticmethod
    def _tool_success_rate(logs: list[Any]) -> float:
        tool_calls = []
        for log in logs:
            tool_calls.extend(getattr(log, "tool_candidates", []) or [])
        if not tool_calls:
            return 0
        success_count = sum(
            1 for item in tool_calls if item.get("status") == "success"
        )
        return round(success_count / len(tool_calls), 2)

    @staticmethod
    def _status_count(logs: list[Any]) -> dict:
        result = {}
        for log in logs:
            result[log.status] = result.get(log.status, 0) + 1
        return result
