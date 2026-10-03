"""system_prompts.yaml 内容契约：首页助手提示词必须含 observe-act 电脑控制协议。"""
from pathlib import Path

import internal.core
import yaml


def _preset_content() -> str:
    path = Path(internal.core.__file__).parent / "prompts" / "system_prompts.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for item in data.get("prompts") or []:
        if item.get("key") == "assistant_agent_markdown_preset":
            return str(item.get("content") or "")
    raise AssertionError("assistant_agent_markdown_preset 未在 system_prompts.yaml 登记")


def test_assistant_preset_contains_observe_act_protocol():
    content = _preset_content()
    for token in (
        "capture",
        "element_index",
        "元素树",
        "escalation",
        "vision_analyze",
        "return_base64",
    ):
        assert token in content, f"observe-act 规则缺少 token: {token}"


def test_assistant_preset_keeps_existing_tool_rules():
    content = _preset_content()
    assert "os_file_task" in content
    assert "os_recycle_bin" in content
