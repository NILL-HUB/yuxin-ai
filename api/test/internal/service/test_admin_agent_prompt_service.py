"""管理端 Agent 系统提示词构造测试（AGENTS.md 强制规则）。

提示词内容必须来自 YAML seed / DB `prompt_template`，**不得**硬编码在 .py；
Agent 的 prompt_key 为空时回退到内置默认 `admin_agent_board_agent`。
"""
from types import SimpleNamespace
from uuid import uuid4

from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel
from internal.service.admin_agent_prompt_service import (
    DEFAULT_ADMIN_AGENT_PROMPT_KEY,
    AdminAgentPromptService,
)


def _principal():
    return AdminAgentPrincipal(
        admin_user_id=uuid4(),
        agent_id=uuid4(),
        agent_name="运维 Agent",
        effective_permissions=frozenset({"builtin_tool:read"}),
        automation_policy={"builtin_tool": AutomationLevel.SUPERVISED},
    )


def test_uses_agent_prompt_key_when_present():
    captured = {}

    def _get(content_key, variables):
        captured["key"] = content_key
        captured["variables"] = variables
        return "渲染后的提示词"

    service = AdminAgentPromptService()
    service._render_template = _get

    result = service.build_system_prompt(_principal(), prompt_key="ops_agent")

    assert result == "渲染后的提示词"
    assert captured["key"] == "ops_agent"
    assert captured["variables"]["agent_name"] == "运维 Agent"
    assert "builtin_tool:read" in captured["variables"]["granted_permissions"]


def test_falls_back_to_default_key_when_agent_has_none():
    captured = {}

    service = AdminAgentPromptService()
    service._render_template = lambda key, variables: captured.setdefault("key", key) or "x"

    service.build_system_prompt(_principal(), prompt_key=None)

    assert captured["key"] == DEFAULT_ADMIN_AGENT_PROMPT_KEY
