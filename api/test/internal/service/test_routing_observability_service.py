from types import SimpleNamespace

from internal.service.routing_observability_service import RoutingObservabilityService


def _log(**kwargs):
    defaults = {
        "status": "success",
        "fallback_reason": "",
        "agent_pool_hits": [{"pool": "research"}],
        "agent_candidates": [{"agent_id": "agent-1"}],
        "tool_pool_hits": [{"pool": "web"}],
        "tool_candidates": [{"name": "search", "status": "success"}],
        "cost_summary": {"total_credits": 3},
        "latency_ms": 1000,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_observability_service_should_return_zero_summary_for_empty_logs():
    summary = RoutingObservabilityService().summarize([])

    assert summary == {
        "total_count": 0,
        "success_count": 0,
        "failure_count": 0,
        "fallback_count": 0,
        "total_credits": 0,
        "avg_latency_ms": 0,
        "agent_pool_hit_rate": 0,
        "tool_pool_hit_rate": 0,
        "agent_hit_rate": 0,
        "tool_success_rate": 0,
        "status_count": {},
    }


def test_observability_service_should_summarize_routing_logs():
    logs = [
        _log(),
        _log(
            status="failed",
            fallback_reason="quota_exhausted",
            agent_pool_hits=[],
            agent_candidates=[],
            tool_pool_hits=[],
            tool_candidates=[{"name": "delete", "status": "failed"}],
            cost_summary={"total_credits": 2},
            latency_ms=2000,
        ),
    ]

    summary = RoutingObservabilityService().summarize(logs)

    assert summary == {
        "total_count": 2,
        "success_count": 1,
        "failure_count": 1,
        "fallback_count": 1,
        "total_credits": 5,
        "avg_latency_ms": 1500,
        "agent_pool_hit_rate": 0.5,
        "tool_pool_hit_rate": 0.5,
        "agent_hit_rate": 0.5,
        "tool_success_rate": 0.5,
        "status_count": {"success": 1, "failed": 1},
    }
