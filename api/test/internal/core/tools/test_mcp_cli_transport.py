import sys

from internal.core.tools.mcp_tools.providers.mcp_tool_factory import McpToolFactory


def _cli_binding() -> dict:
    return {
        "name": "cli_echo",
        "transport": "cli",
        "command": sys.executable,
        "args": ["-c", "print('{text}')"],
        "env": {},
        "timeout_seconds": 30,
        "tool_schema": {
            "echo": {
                "description": "回声文本",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            }
        },
    }


def test_cli_transport_builds_langchain_tool(monkeypatch):
    factory = McpToolFactory()
    tools = factory.get_tools([_cli_binding()], mcp_tool_snapshots=None)

    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "mcp__cli_echo__echo"
    assert tool.invoke({"text": "hello-cli"}) == "hello-cli"


def test_cli_binding_disabled_without_command():
    factory = McpToolFactory()
    binding = _cli_binding()
    binding["command"] = ""

    assert factory.get_tools([binding], mcp_tool_snapshots=None) == []


def test_unknown_transport_is_still_skipped():
    factory = McpToolFactory()
    binding = _cli_binding()
    binding["transport"] = "carrier-pigeon"

    assert factory.get_tools([binding], mcp_tool_snapshots=None) == []
