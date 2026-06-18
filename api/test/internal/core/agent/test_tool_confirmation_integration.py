from types import SimpleNamespace
from uuid import uuid4

from internal.core.agent.entities.tool_policy_entity import ToolPolicy


class TestToolConfirmationIntegration:
    def test_tool_policy_should_identify_dangerous_tools(self):
        policy = ToolPolicy()
        assert policy.is_dangerous_tool("drop_table") is True
        assert policy.is_dangerous_tool("format_disk") is True
        assert policy.is_dangerous_tool("execute_shell") is True
        assert policy.is_dangerous_tool("safe_tool") is False
        assert policy.is_dangerous_tool("") is False
        assert policy.is_dangerous_tool(None) is False

    def test_tool_policy_should_identify_high_risk_tools(self):
        policy = ToolPolicy()
        assert policy.is_high_risk_tool("send_email") is True
        assert policy.is_high_risk_tool("execute_sql") is True
        assert policy.is_high_risk_tool("deploy_application") is True
        assert policy.is_high_risk_tool("delete_resource") is True
        assert policy.is_high_risk_tool("modify_billing") is True
        assert policy.is_high_risk_tool("transfer_funds") is True
        assert policy.is_high_risk_tool("safe_tool") is False
        assert policy.is_high_risk_tool("") is False

    def test_tool_policy_should_not_treat_safe_tool_as_dangerous(self):
        policy = ToolPolicy()
        assert policy.is_dangerous_tool("dataset_retrieval") is False
        assert policy.is_high_risk_tool("dataset_retrieval") is False

    def test_tool_policy_high_risk_and_dangerous_should_be_disjoint(self):
        policy = ToolPolicy()
        for name in policy.high_risk_tool_names:
            assert policy.is_dangerous_tool(name) is False
        for name in policy.dangerous_tool_names:
            assert policy.is_high_risk_tool(name) is False

    def test_risk_level_should_include_sensitive_and_dangerous(self):
        from internal.entity.tool_inventory_entity import RiskLevel
        assert RiskLevel.DANGEROUS.value == "dangerous"
        assert RiskLevel.SENSITIVE.value == "sensitive"
        assert RiskLevel.SAFE.value == "safe"
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"

    def test_tool_invoker_security_error_should_reject_dangerous(self):
        from internal.entity.tool_inventory_entity import RiskLevel
        from internal.service.tool_invoker_service import ToolInvokerService

        tool = SimpleNamespace(metadata={"risk_level": RiskLevel.DANGEROUS.value, "user_scope": "system"})
        request = SimpleNamespace(account_id=str(uuid4()))
        result = ToolInvokerService._security_error(tool, request, confirmed=False)
        assert result is not None
        assert result["error_code"] == "forbidden"

    def test_tool_invoker_security_error_should_require_confirmation_for_sensitive(self):
        from internal.entity.tool_inventory_entity import RiskLevel
        from internal.service.tool_invoker_service import ToolInvokerService

        tool = SimpleNamespace(metadata={"risk_level": RiskLevel.SENSITIVE.value, "user_scope": "system"})
        request = SimpleNamespace(account_id=str(uuid4()))
        result = ToolInvokerService._security_error(tool, request, confirmed=False)
        assert result is not None
        assert result["error_code"] == "confirmation_required"

        result_confirmed = ToolInvokerService._security_error(tool, request, confirmed=True)
        assert result_confirmed is None

    def test_tool_invoker_security_error_should_require_confirmation_for_high(self):
        from internal.entity.tool_inventory_entity import RiskLevel
        from internal.service.tool_invoker_service import ToolInvokerService

        tool = SimpleNamespace(metadata={"risk_level": RiskLevel.HIGH.value, "user_scope": "system"})
        request = SimpleNamespace(account_id=str(uuid4()))
        result = ToolInvokerService._security_error(tool, request, confirmed=False)
        assert result is not None
        assert result["error_code"] == "confirmation_required"

    def test_tool_invoker_security_error_should_pass_safe_tool(self):
        from internal.entity.tool_inventory_entity import RiskLevel
        from internal.service.tool_invoker_service import ToolInvokerService

        tool = SimpleNamespace(metadata={"risk_level": RiskLevel.SAFE.value, "user_scope": "system"})
        request = SimpleNamespace(account_id=str(uuid4()))
        result = ToolInvokerService._security_error(tool, request, confirmed=False)
        assert result is None
