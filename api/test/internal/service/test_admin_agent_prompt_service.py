"""管理端 Agent 系统提示词构造测试（AGENTS.md 强制规则）。

提示词内容必须来自 YAML seed / DB `prompt_template`，**不得**硬编码在 .py；
Agent 的 prompt_key 为空时回退到内置默认 `admin_agent_board_agent`。

真实路径说明（对应审查 M-4）：本文件里替换 `_render_template` 的用例（
`test_uses_agent_prompt_key_when_present` / `test_falls_back_to_default_key_when_agent_has_none`）
只锁定"key 解析 + 变量组装"这一层；真实渲染路径由不替换 `_render_template`、
仅打桩 `PromptSyncService.get_prompt` 的用例覆盖（缺失/残留占位符/默认路径），
因此前者的"弱"不会掩盖后者。
"""
from uuid import uuid4

import pytest

from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel
from internal.exception import FailException
from internal.service.admin_agent_prompt_service import (
    DEFAULT_ADMIN_AGENT_PROMPT_KEY,
    AdminAgentPromptService,
)
from internal.service.prompt_sync_service import PromptSyncService


def _principal(automation_policy=None, permissions=frozenset({"builtin_tool:read"})):
    return AdminAgentPrincipal(
        admin_user_id=uuid4(),
        agent_id=uuid4(),
        agent_name="运维 Agent",
        effective_permissions=permissions,
        automation_policy=(
            {"builtin_tool": AutomationLevel.SUPERVISED}
            if automation_policy is None
            else automation_policy
        ),
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
    # 精确断言：避免 substring 断言放过 "builtin_tool:read:extra" 一类前缀污染
    assert captured["variables"]["agent_name"] == "运维 Agent"
    assert captured["variables"]["granted_permissions"] == "builtin_tool:read"
    assert captured["variables"]["automation_policy"] == "builtin_tool=supervised"


def test_falls_back_to_default_key_when_agent_has_none():
    captured = {}

    service = AdminAgentPromptService()
    service._render_template = lambda key, variables: captured.setdefault("key", key) or "x"

    service.build_system_prompt(_principal(), prompt_key=None)

    assert captured["key"] == DEFAULT_ADMIN_AGENT_PROMPT_KEY


def test_raises_when_prompt_content_missing(monkeypatch):
    """不变量 1：取不到提示词必须显式失败，不得退化为空串。"""
    monkeypatch.setattr(
        PromptSyncService,
        "get_prompt",
        staticmethod(lambda prompt_key, **variables: None),
    )

    service = AdminAgentPromptService()

    with pytest.raises(FailException):
        service.build_system_prompt(_principal(), prompt_key="ops_agent")


def test_raises_when_prompt_keeps_unfilled_placeholders(monkeypatch):
    """不变量 1b（I-2 真缺陷）：渲染后仍残留注入变量占位符 → 显式失败。

    `PromptSyncService.get_prompt` 在 `content.format(**variables)` 抛错时只记
    warning 并返回**未渲染原文**（prompt_sync_service.py:196-203）。若本服务不看
    内容就返回，Agent 会照着字面 `{granted_permissions}` 行事、行为约束静默失效。
    """
    unrendered = (
        "你是「{agent_name}」。\n"
        "# 当前生效权限\n{granted_permissions}\n"
        "# 各板块自动化级别\n{automation_policy}\n"
    )
    monkeypatch.setattr(
        PromptSyncService,
        "get_prompt",
        staticmethod(lambda prompt_key, **variables: unrendered),
    )

    service = AdminAgentPromptService()

    with pytest.raises(FailException) as exc_info:
        service.build_system_prompt(_principal(), prompt_key="ops_agent")

    message = str(exc_info.value)
    assert "ops_agent" in message
    assert "agent_name" in message
    assert "granted_permissions" in message
    assert "automation_policy" in message


def test_allows_legitimate_literal_braces_when_rendered(monkeypatch):
    """口径说明：只检测**本次注入变量名**的占位符形态，合法的字面花括号不误伤。

    提示词正文里出现 JSON 示例 `{"board": "builtin_tool"}` 或其它非注入变量的
    花括号（如 `{board}`）都属于合法内容，不能被当成"未渲染"。
    """
    rendered = (
        "你是「运维 Agent」。\n"
        "只读动作返回示例：{\"board\": \"builtin_tool\", \"ok\": true}\n"
        "板块名占位（非本服务变量）：{board}\n"
    )
    monkeypatch.setattr(
        PromptSyncService,
        "get_prompt",
        staticmethod(lambda prompt_key, **variables: rendered),
    )

    service = AdminAgentPromptService()

    assert service.build_system_prompt(_principal(), prompt_key="ops_agent") == rendered


def test_literal_brace_shaped_as_injected_variable_fails_closed(monkeypatch):
    """口径边界（保守取值，故意如此）：`{{agent_name}}` 渲染后就是字面 `{agent_name}`，
    与"填充失败留下的占位符"在渲染结果上不可区分（本模块只拿得到渲染结果）。
    本服务选择 fail loud 而非放过——宁可提示词构造失败，也不要 Agent 看到残缺约束。
    """
    rendered = "你是「{{agent_name}}」的字面示例。"  # 模拟 `{{agent_name}}` 被 format 后的结果
    monkeypatch.setattr(
        PromptSyncService,
        "get_prompt",
        staticmethod(lambda prompt_key, **variables: rendered.replace("{{", "{").replace("}}", "}")),
    )

    service = AdminAgentPromptService()

    with pytest.raises(FailException):
        service.build_system_prompt(_principal(), prompt_key="ops_agent")


def test_default_path_calls_prompt_sync_service_with_variables(monkeypatch):
    """不变量 2：默认路径真的走到 PromptSyncService.get_prompt 且变量完整。"""
    calls = []

    def _fake_get_prompt(prompt_key, **variables):
        calls.append((prompt_key, variables))
        return "渲染后的提示词：运维 Agent / builtin_tool:read / builtin_tool=supervised"

    monkeypatch.setattr(
        PromptSyncService,
        "get_prompt",
        staticmethod(_fake_get_prompt),
    )

    service = AdminAgentPromptService()

    result = service.build_system_prompt(_principal(), prompt_key="ops_agent")

    assert result == "渲染后的提示词：运维 Agent / builtin_tool:read / builtin_tool=supervised"
    assert len(calls) == 1
    key, variables = calls[0]
    assert key == "ops_agent"
    assert variables["agent_name"] == "运维 Agent"
    assert variables["granted_permissions"] == "builtin_tool:read"
    assert variables["automation_policy"] == "builtin_tool=supervised"


def test_falls_back_to_default_key_when_prompt_key_blank(monkeypatch):
    captured = {}

    def _fake_get_prompt(prompt_key, **variables):
        captured["key"] = prompt_key
        return "x"

    monkeypatch.setattr(
        PromptSyncService,
        "get_prompt",
        staticmethod(_fake_get_prompt),
    )

    service = AdminAgentPromptService()

    for blank in ("", "   "):
        service.build_system_prompt(_principal(), prompt_key=blank)
        assert captured["key"] == DEFAULT_ADMIN_AGENT_PROMPT_KEY


def test_format_policy_marks_unconfigured_boards_as_supervised():
    """不变量 3：未配置板块的语义是"按 supervised 处理"，必须写进提示词。"""
    result = AdminAgentPromptService._format_policy(_principal(automation_policy={}))

    assert "supervised" in result


def test_format_policy_accepts_string_levels():
    """I-5 负向：policy 里存的是字符串（跨层透传/反序列化后常见）时，
    级别经 `principal.automation_level_for()` 归一化取得，不得 AttributeError。
    """
    principal = _principal(automation_policy={"builtin_tool": "autonomous"})

    result = AdminAgentPromptService._format_policy(principal)

    assert result == "builtin_tool=autonomous"


def test_format_policy_fails_closed_on_invalid_level():
    """非法级别同样 fail closed 到 supervised（与 automation_level_for 一致）。"""
    principal = _principal(automation_policy={"builtin_tool": "not-a-level"})

    assert AdminAgentPromptService._format_policy(principal) == "builtin_tool=supervised"
