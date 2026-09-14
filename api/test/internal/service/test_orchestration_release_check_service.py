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


def _capture_sensitive_tools_query(monkeypatch):
    """替换 current_app.injector，捕获敏感工具治理检查实际使用的过滤条件。"""
    from internal.model.tool_governance_entity import ToolGovernancePolicy
    from internal.service import orchestration_release_check_service as module

    captured: dict = {}

    class _Query:
        def filter(self, *criteria):
            captured["criteria"] = criteria
            return self

        def count(self):
            return 1

    class _Session:
        def query(self, model):
            captured["model"] = model
            return _Query()

    class _Db:
        session = _Session()

    class _Injector:
        def get(self, _cls):
            return _Db()

    class _App:
        injector = _Injector()

    monkeypatch.setattr(module, "current_app", _App())
    return captured, ToolGovernancePolicy


def test_sensitive_tools_governed_uses_enabled_not_status(monkeypatch):
    """敏感工具治理检查必须按 enabled 判定（表中不存在 status 列）。

    历史实现引用 ToolGovernancePolicy.status，触发 AttributeError 被 except 吞掉，
    导致安全检查恒为 False。此测试锁定：查询条件基于 enabled，且异常不再静默。
    """
    captured, ToolGovernancePolicy = _capture_sensitive_tools_query(monkeypatch)

    service = _make_service()
    assert service._check_sensitive_tools_governed() is True
    assert captured["model"] is ToolGovernancePolicy

    # 断言查询条件里出现了 enabled 列，且没有引用不存在的 status
    criteria_text = " ".join(str(c) for c in captured["criteria"])
    assert "enabled" in criteria_text
    assert "status" not in criteria_text


def test_sensitive_tools_governed_degrades_safely(monkeypatch):
    """查询异常时返回 False（保守失败），不得抛断主流程。"""
    from internal.service import orchestration_release_check_service as module

    class _App:
        class injector:
            @staticmethod
            def get(_cls):
                raise RuntimeError("db unavailable")

    monkeypatch.setattr(module, "current_app", _App())

    assert _make_service()._check_sensitive_tools_governed() is False
