class OrchestrationReleaseCheckService:
    def build_report(
        self,
        *,
        test_status: dict | None = None,
        migration_status: dict | None = None,
        feature_flags: list[dict] | None = None,
        security_checklist: dict | None = None,
        cost_metrics: dict | None = None,
        routing_metrics: dict | None = None,
        warnings: list[str] | None = None,
    ) -> dict:
        return {
            "test_status": test_status or self._default_test_status(),
            "migration_status": migration_status or self._default_migration_status(),
            "feature_flags": feature_flags or [],
            "security_checklist": security_checklist
            or self._default_security_checklist(),
            "cost_metrics": cost_metrics or {},
            "routing_metrics": routing_metrics or {},
            "rollback_plan": self._rollback_plan(),
            "warnings": warnings or [],
        }

    @staticmethod
    def _default_test_status() -> dict:
        return {
            "backend": "not_provided",
            "frontend_type_check": "not_provided",
            "frontend_lint": "not_provided",
            "frontend_unit": "not_provided",
        }

    @staticmethod
    def _default_migration_status() -> dict:
        return {
            "heads_current": "not_provided",
            "latest_revision": "unknown",
        }

    @staticmethod
    def _default_security_checklist() -> dict:
        return {
            "admin_only_flags": True,
            "user_safe_payload": True,
            "rollback_available": True,
        }

    @staticmethod
    def _rollback_plan() -> dict:
        return {
            "primary_action": "disable_feature_flags",
            "fallback_flow": "legacy_assistant_agent",
            "steps": [
                "Disable high-risk orchestration flags",
                "Keep legacy Assistant Agent flow available",
                "Review routing logs and fallback warnings",
            ],
        }
