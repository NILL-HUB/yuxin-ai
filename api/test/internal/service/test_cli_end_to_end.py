"""CLI 工具来源端到端验收。

覆盖「装配 → 真实执行 → 取 stdout」链路：用 `python -c "print('hello-cli')"`
作为最小纯 CLI（无 GUI 依赖），验证 `CliService.build_selected_tools`
经 `McpToolFactory`（`protocol=raw`）真实 spawn 子进程并回传 stdout。

候选进池与选择器命中见 test_tool_inventory_cli.py。
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

from internal.service.cli_service import CliService


def _demo_provider() -> SimpleNamespace:
    return SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        name="demo-cli",
        label="Demo CLI",
        description="演示 CLI",
        command=sys.executable,
        args=["-c", "print('hello-cli')"],
        env={},
        timeout_seconds=30,
        tool_schema={
            "echo": {
                "description": "输出 hello-cli",
                "parameters": {"type": "object", "properties": {}},
            }
        },
        enabled=True,
    )


def test_cli_tool_executes_and_returns_stdout():
    tools = CliService.build_selected_tools([_demo_provider()], tool_names=["echo"])

    assert tools, "应至少装配出一个 CLI 工具"

    result = tools[0].invoke({})

    assert "hello-cli" in str(result)


def test_cli_tool_result_is_json_friendly():
    """工具应可被 LangChain 正常调用并返回可序列化结果（不抛异常）。"""
    tools = CliService.build_selected_tools([_demo_provider()], tool_names=["echo"])

    tool = tools[0]
    assert getattr(tool, "name", "") != ""
    output = tool.invoke({})
    assert isinstance(output, (str, dict, list))


def test_cli_provider_without_matching_tool_name_yields_no_tool():
    """tool_names 与 tool_schema 不匹配时不应装配出工具（避免误挂载）。"""
    tools = CliService.build_selected_tools([_demo_provider()], tool_names=["not-exist"])

    assert tools == []
