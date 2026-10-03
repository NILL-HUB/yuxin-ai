from __future__ import annotations

from internal.core.skills.skill_tool_factory import SkillToolFactory
from internal.exception import FailException


class _StubExecutor:
    """替身：SkillToolFactory 只应「委托执行」，协议选择由 SkillExecutor 负责。"""

    def __init__(self, *, result=None, error=None):
        self.calls = []
        self._result = result
        self._error = error

    def execute_skill(self, payload):
        self.calls.append(payload)
        if self._error is not None:
            raise self._error
        return self._result


def _scf_package_payload() -> dict:
    return {
        "skill_id": "skill-1",
        "source_key": "demo_skill",
        "name": "演示技能",
        "label": "演示技能",
        "executor_type": "scf",
        "bundle": {"skill.py": "def demo(params):\n    return params\n"},
    }


def _demo_tool_definitions() -> list[dict]:
    return [
        {
            "name": "demo",
            "label": "演示",
            "description": "演示工具",
            "entrypoint": "demo",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
    ]


def test_skill_tool_factory_should_delegate_execution_to_skill_executor():
    executor = _StubExecutor(result={"status": "ok", "echo": {"query": "hello"}})
    factory = SkillToolFactory(skill_executor=executor)

    tools = factory.build_tools(
        package_payload=_scf_package_payload(),
        tool_definitions=_demo_tool_definitions(),
        runtime_context={"app_id": "app-1"},
    )

    result = tools[0].invoke({"query": "hello"})

    assert "ok" in result
    payload = executor.calls[0]
    assert payload["tool_name"] == "demo"
    assert payload["entrypoint"] == "demo"
    assert payload["input"] == {"query": "hello"}
    assert payload["bundle"]["skill.py"].startswith("def demo")
    assert payload["runtime_context"]["app_id"] == "app-1"


def test_skill_tool_factory_should_surface_original_error():
    """回归：不再「先试 SCF 再兜沙箱」，原始错误必须原样透出（此前会被兜底错误替换）。"""
    executor = _StubExecutor(error=FailException("云函数执行超时"))
    factory = SkillToolFactory(skill_executor=executor)

    tools = factory.build_tools(
        package_payload=_scf_package_payload(),
        tool_definitions=_demo_tool_definitions(),
        runtime_context={"app_id": "app-1"},
    )

    result = tools[0].invoke({"query": "hello"})

    assert "技能执行失败" in result
    assert "云函数执行超时" in result


def test_skill_tool_factory_should_skip_prompt_only_packages():
    factory = SkillToolFactory(skill_executor=_StubExecutor(result={}))

    tools = factory.build_tools(
        package_payload={
            "skill_id": "skill-1",
            "source_key": "demo_skill",
            "name": "演示技能",
            "label": "演示技能",
            "executor_type": "prompt",
            "bundle": {"skill.py": "def demo(params):\n    return params\n"},
        },
        tool_definitions=[
            {
                "name": "demo",
                "label": "演示",
                "description": "演示工具",
                "entrypoint": "demo",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
        runtime_context={"app_id": "app-1"},
    )

    assert tools == []


def test_skill_tool_factory_should_not_require_version_in_package_payload():
    executor = _StubExecutor(result={"status": "ok"})
    factory = SkillToolFactory(skill_executor=executor)

    tools = factory.build_tools(
        package_payload=_scf_package_payload(),
        tool_definitions=[
            {
                "name": "demo",
                "label": "演示",
                "description": "演示工具",
                "entrypoint": "demo",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
        runtime_context={"app_id": "app-1"},
    )

    assert tools
    assert tools[0].invoke({})
    assert "version" not in executor.calls[0]
