import sys

from internal.core.tools.mcp_tools.providers.mcp_stdio_client import McpStdioClient


def _python_command(script: str) -> str:
    return f'{sys.executable} -c "{script}"'


def test_raw_protocol_lists_declared_tools():
    client = McpStdioClient()
    binding = {
        "protocol": "raw",
        "command": sys.executable,
        "args": [],
        "env": {},
        "tool_schema": {
            "echo_text": {
                "description": "回声文本",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            }
        },
    }

    tools = client.list_tools_sync(binding)

    assert [tool["name"] for tool in tools] == ["echo_text"]
    assert tools[0]["description"] == "回声文本"
    assert tools[0]["inputSchema"]["properties"]["text"]["type"] == "string"


def test_raw_protocol_substitutes_argv_placeholders():
    client = McpStdioClient()
    binding = {
        "protocol": "raw",
        "command": sys.executable,
        "args": ["-c", "print('hello', '{text}')"],
        "env": {},
        "timeout_seconds": 30,
        "tool_schema": {
            "echo_text": {
                "description": "回声文本",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            }
        },
    }

    result = client.call_tool_sync(binding, "echo_text", {"text": "world"})

    assert result["isError"] is False
    assert "hello world" in result["content"][0]["text"]


def test_raw_protocol_reports_nonzero_exit_as_error():
    client = McpStdioClient()
    binding = {
        "protocol": "raw",
        "command": sys.executable,
        "args": ["-c", "import sys; sys.stderr.write('boom'); sys.exit(2)"],
        "env": {},
        "timeout_seconds": 30,
        "tool_schema": {
            "fail_cmd": {
                "description": "必然失败",
                "parameters": {"type": "object", "properties": {}},
            }
        },
    }

    result = client.call_tool_sync(binding, "fail_cmd", {})

    assert result["isError"] is True
    assert "boom" in result["content"][0]["text"]


def test_raw_protocol_rejects_undeclared_tool():
    client = McpStdioClient()
    binding = {
        "protocol": "raw",
        "command": sys.executable,
        "args": [],
        "env": {},
        "tool_schema": {},
    }

    result = client.call_tool_sync(binding, "not_declared", {})

    assert result["isError"] is True
    assert "未声明" in result["content"][0]["text"]
