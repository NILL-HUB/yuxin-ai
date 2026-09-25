import sys

from internal.core.tools.mcp_tools.providers.mcp_stdio_client import McpStdioClient


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


def test_raw_protocol_serializes_non_scalar_argument_as_json():
    """非标量参数按 JSON 传，不是 Python repr（便于 CLI 侧 json.loads）。"""
    import json

    client = McpStdioClient()
    binding = {
        "protocol": "raw",
        "command": sys.executable,
        "args": ["-c", "import sys; print(sys.argv[1])", "{items}"],
        "env": {},
        "timeout_seconds": 30,
        "tool_schema": {
            "echo_list": {
                "description": "回显数组",
                "parameters": {
                    "type": "object",
                    "properties": {"items": {"type": "array", "items": {"type": "string"}}},
                },
            }
        },
    }

    result = client.call_tool_sync(binding, "echo_list", {"items": ["a", "b"]})

    assert result["isError"] is False
    assert result["content"][0]["text"].strip() == json.dumps(["a", "b"])


def test_raw_protocol_reports_bad_command_as_structured_error():
    """缺 command 时返回结构化错误，而不是冒泡成工厂通用兜底文案。"""
    client = McpStdioClient()
    binding = {
        "protocol": "raw",
        "command": "",
        "args": [],
        "env": {},
        "tool_schema": {
            "echo": {"description": "回声", "parameters": {"type": "object", "properties": {}}}
        },
    }

    result = client.call_tool_sync(binding, "echo", {})

    assert result["isError"] is True
    assert "CLI 参数构建失败" in result["content"][0]["text"]


def test_raw_protocol_drops_optional_flag_pair_when_argument_missing():
    """整 token 占位符未提供时，连同其前置 flag 一起丢弃，绝不传字面量 `{limit}`。

    可选参数（如 --limit）被模型省略时，正确行为是按 CLI 默认值执行，
    即去掉 `--limit {limit}` 这一对；否则 CLI 会收到字面量 `{limit}`。
    """
    client = McpStdioClient()
    binding = {
        "protocol": "raw",
        "command": sys.executable,
        "args": ["-c", "import json,sys;print(json.dumps(sys.argv[1:]))", "--limit", "{limit}"],
        "env": {},
        "timeout_seconds": 30,
        "tool_schema": {
            "search": {
                "description": "搜索",
                "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
            }
        },
    }

    result = client.call_tool_sync(binding, "search", {})

    assert result["isError"] is False
    assert result["content"][0]["text"].strip() == "[]"


def test_raw_protocol_keeps_flag_pair_when_argument_provided():
    """整 token 占位符提供了值时，flag 与其值都应保留。"""
    client = McpStdioClient()
    binding = {
        "protocol": "raw",
        "command": sys.executable,
        "args": ["-c", "import json,sys;print(json.dumps(sys.argv[1:]))", "--limit", "{limit}"],
        "env": {},
        "timeout_seconds": 30,
        "tool_schema": {
            "search": {
                "description": "搜索",
                "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
            }
        },
    }

    result = client.call_tool_sync(binding, "search", {"limit": 5})

    assert result["isError"] is False
    assert result["content"][0]["text"].strip() == '["--limit", "5"]'


def test_raw_protocol_reports_inline_missing_placeholder_as_structured_error():
    """内联占位符无法安全丢弃，未提供时必须结构化报错，不得传字面量。"""
    client = McpStdioClient()
    binding = {
        "protocol": "raw",
        "command": sys.executable,
        "args": ["-c", "print('x={a}')"],
        "env": {},
        "timeout_seconds": 30,
        "tool_schema": {
            "echo": {
                "description": "回声",
                "parameters": {"type": "object", "properties": {"a": {"type": "string"}}},
            }
        },
    }

    result = client.call_tool_sync(binding, "echo", {})

    assert result["isError"] is True
    assert "a" in result["content"][0]["text"]
