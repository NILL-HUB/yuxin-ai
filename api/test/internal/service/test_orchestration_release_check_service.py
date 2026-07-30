from internal.service.orchestration_release_check_service import (
    OrchestrationReleaseCheckService,
)


def _make_service():
    """构建 OrchestrationReleaseCheckService 实例（注入 mock flag service）。"""
    class _MockFlagService:
        @staticmethod
        def list_flags():
            return []
    return OrchestrationReleaseCheckService(
        orchestration_feature_flag_service=_MockFlagService(),
    )


def test_release_check_should_return_complete_empty_report():
    report = _make_service().build_report()

    assert set(report) == {
        "test_status",
        "migration_status",
        "feature_flags",
        "security_checklist",
        "cost_metrics",
        "routing_metrics",
        "rollback_plan",
        "warnings",
    }
    assert report["rollback_plan"]["primary_action"] == "disable_feature_flags"
    assert report["rollback_plan"]["fallback_flow"] == "legacy_assistant_agent"


def test_release_check_should_embed_feature_flags_and_routing_metrics():
    flags = [{"code": "ENABLE_ORCHESTRATOR", "enabled": True}]
    routing_metrics = {"total_count": 10, "fallback_count": 1}

    report = _make_service().build_report(
        feature_flags=flags,
        routing_metrics=routing_metrics,
        warnings=["routing fallback rate requires review"],
    )

    assert report["feature_flags"] == flags
    assert report["routing_metrics"] == routing_metrics
    assert report["warnings"] == ["routing fallback rate requires review"]
