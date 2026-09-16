"""AdminAgentPrincipal 身份对象测试（设计 §5）。"""
from uuid import uuid4

import pytest

from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel


class TestAdminAgentPrincipal:
    def test_is_frozen(self):
        """身份对象不可变——避免执行中途被篡改权限。"""
        principal = AdminAgentPrincipal(
            admin_user_id=uuid4(),
            agent_id=uuid4(),
            agent_name="运维 Agent",
            effective_permissions=frozenset({"model_pool:read"}),
            automation_policy={"model_pool": AutomationLevel.SUPERVISED},
        )
        with pytest.raises(Exception):
            principal.agent_name = "改名"

    def test_automation_level_for_unconfigured_board_is_supervised(self):
        """fail closed：未配置的板块默认 supervised，不是 autonomous。"""
        principal = AdminAgentPrincipal(
            admin_user_id=uuid4(),
            agent_id=uuid4(),
            agent_name="a",
            effective_permissions=frozenset(),
            automation_policy={},
        )
        assert principal.automation_level_for("model_pool") is AutomationLevel.SUPERVISED

    def test_automation_level_reads_configured_value(self):
        principal = AdminAgentPrincipal(
            admin_user_id=uuid4(),
            agent_id=uuid4(),
            agent_name="a",
            effective_permissions=frozenset(),
            automation_policy={"prompt_template": AutomationLevel.AUTONOMOUS},
        )
        assert (
            principal.automation_level_for("prompt_template")
            is AutomationLevel.AUTONOMOUS
        )

    def test_has_permission(self):
        principal = AdminAgentPrincipal(
            admin_user_id=uuid4(),
            agent_id=uuid4(),
            agent_name="a",
            effective_permissions=frozenset({"model_pool:read"}),
            automation_policy={},
        )
        assert principal.has_permission("model_pool:read") is True
        assert principal.has_permission("model_pool:update") is False

    def test_automation_level_values(self):
        assert AutomationLevel.SUPERVISED.value == "supervised"
        assert AutomationLevel.AUTONOMOUS.value == "autonomous"
        assert AutomationLevel.BLOCKED.value == "blocked"
