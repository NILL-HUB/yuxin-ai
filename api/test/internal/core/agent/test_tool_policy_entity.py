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
