from internal.model.routing_log import RoutingLog


def test_routing_log_should_include_phase7_observability_columns():
    columns = RoutingLog.__table__.columns

    for name in [
        "user_query",
        "task_classification",
        "model_selection",
        "agent_pool_hits",
        "tool_pool_hits",
        "key_usage",
        "cost_summary",
        "latency_ms",
        "fallback_reason",
        "redaction_enabled",
        "retention_expires_at",
    ]:
        assert name in columns


def test_routing_log_should_index_phase7_common_filters():
    indexes = {index.name for index in RoutingLog.__table__.indexes}

    assert "routing_log_retention_expires_at_idx" in indexes
    assert "routing_log_latency_ms_idx" in indexes
