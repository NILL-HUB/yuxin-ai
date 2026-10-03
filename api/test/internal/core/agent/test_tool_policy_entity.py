from internal.core.agent.entities.tool_policy_entity import (
    KNOWLEDGE_RETRIEVAL_TOOL_NAME,
    ToolPolicy,
)


def test_tool_policy_should_expose_default_shared_strategy():
    policy = ToolPolicy()

    assert policy.dataset_retrieval_tool_name == "dataset_retrieval"
    assert policy.resolve_tool_name("recall_dataset") == KNOWLEDGE_RETRIEVAL_TOOL_NAME
    assert policy.resolve_tool_name("dataset_retrieval") == KNOWLEDGE_RETRIEVAL_TOOL_NAME
    assert policy.is_hard_fail_tool("qwen_image_edit")
    assert policy.is_hard_fail_tool("qwen_image_edit_2509")
    assert policy.is_image_result_tool("qwen_image_text_to_image")


def test_tool_policy_should_support_custom_overrides():
    policy = ToolPolicy(
        hard_fail_tool_names=("custom_hard_fail_tool",),
        tool_alias_synonyms={"custom_alias": "custom_tool"},
        image_result_tool_names=("custom_image_tool",),
    )

    assert policy.resolve_tool_name("custom_alias") == "custom_tool"
    assert policy.is_hard_fail_tool("custom_hard_fail_tool")
    assert policy.is_image_result_tool("custom_image_tool")
    assert not policy.is_hard_fail_tool("qwen_image_edit")
    assert not policy.is_image_result_tool("qwen_image_text_to_image")


def test_computer_action_is_image_result_tool_by_default():
    policy = ToolPolicy()

    assert policy.is_image_result_tool("computer_action")
    # 截图回填不改变审批语义：computer_action 仍只属高风险、不属 hard-fail
    assert not policy.is_hard_fail_tool("computer_action")
    assert policy.is_high_risk_tool("computer_action")
    # 原有默认成员不回归
    assert policy.is_image_result_tool("qwen_image_text_to_image")
    assert policy.is_hard_fail_tool("qwen_image_edit")


def test_requires_confirmation_skips_observation_only_computer_actions():
    """纯观察动作（截图/元素树/列表）零写入零焦点影响，免确认——GUI 任务不被逐步打断。"""
    policy = ToolPolicy()

    assert policy.requires_confirmation(
        "computer_action", {"actions": [{"action": "capture"}]}
    ) is False
    assert policy.requires_confirmation(
        "computer_action",
        {"actions": [{"action": "screenshot"}, {"action": "list_windows"}]},
    ) is False
    assert policy.requires_confirmation(
        "computer_action", {"actions": [{"action": "list_apps"}]}
    ) is False


def test_requires_confirmation_keeps_mutating_computer_actions():
    """会改变 GUI 状态的动作（含观察+操作混合序列）仍按高风险确认。"""
    policy = ToolPolicy()

    assert policy.requires_confirmation(
        "computer_action", {"actions": [{"action": "click", "x": 10, "y": 20}]}
    ) is True
    assert policy.requires_confirmation(
        "computer_action",
        {"actions": [{"action": "capture"}, {"action": "click", "x": 10, "y": 20}]},
    ) is True
    assert policy.requires_confirmation(
        "computer_action", {"actions": [{"action": "type", "text": "hi"}]}
    ) is True


def test_requires_confirmation_falls_back_when_actions_missing():
    """actions 缺失/为空时按保守语义确认（无法证明是纯观察）。"""
    policy = ToolPolicy()

    assert policy.requires_confirmation("computer_action", None) is True
    assert policy.requires_confirmation("computer_action", {}) is True
    assert policy.requires_confirmation("computer_action", {"actions": []}) is True
    # 非法条目（非 dict）不能通过观察判定
    assert policy.requires_confirmation(
        "computer_action", {"actions": ["capture"]}
    ) is True


def test_requires_confirmation_other_tools_unaffected():
    """其他高风险工具维持确认；非高风险工具依旧免确认。"""
    policy = ToolPolicy()

    assert policy.requires_confirmation("send_email", {}) is True
    assert policy.requires_confirmation("execute_code", {"command": "print(1)"}) is True
    assert policy.requires_confirmation("browser_action", {"action": "snapshot"}) is True
    assert policy.requires_confirmation("os_file_task", {"op": "read", "path": "x"}) is False
    assert policy.requires_confirmation("os_terminal", {"command": "ls"}) is False
