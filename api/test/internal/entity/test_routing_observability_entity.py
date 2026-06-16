from datetime import datetime, timezone

from internal.entity.routing_observability_entity import (
    RoutingLogMetricsSummary,
    RoutingLogRedactionPolicy,
    RoutingLogRetentionPolicy,
    RoutingLogSearchFilters,
)


def test_retention_policy_should_default_to_30_days():
    policy = RoutingLogRetentionPolicy()

    assert policy.retention_days == 30
    assert policy.to_dict() == {"retention_days": 30}


def test_redaction_policy_should_define_default_sensitive_fields():
    policy = RoutingLogRedactionPolicy(redaction_enabled=True)

    assert policy.redaction_enabled is True
    assert policy.sensitive_fields == [
        "prompt",
        "raw_prompt",
        "api_key",
        "secret",
        "token",
        "headers",
        "arguments",
    ]


def test_search_filters_should_serialize_phase7_filters():
    start_at = datetime(2026, 6, 16, tzinfo=timezone.utc)
    end_at = datetime(2026, 6, 17, tzinfo=timezone.utc)
    filters = RoutingLogSearchFilters(
        account_id="account-1",
        status="success",
        agent_id="agent-1",
        agent_pool="research",
        tool_name="search",
        tool_pool="web",
        model_id="deepseek-chat",
        key_id="key-1",
        start_at=start_at,
        end_at=end_at,
    )

    assert filters.to_dict() == {
        "account_id": "account-1",
        "status": "success",
        "agent_id": "agent-1",
        "agent_pool": "research",
        "tool_name": "search",
        "tool_pool": "web",
        "model_id": "deepseek-chat",
        "key_id": "key-1",
        "start_at": "2026-06-16T00:00:00+00:00",
        "end_at": "2026-06-17T00:00:00+00:00",
    }


def test_metrics_summary_should_default_to_zero_values():
    summary = RoutingLogMetricsSummary()

    assert summary.to_dict() == {
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
    }
